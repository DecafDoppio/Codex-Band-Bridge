"""Codex hook adapter. Errors produce no decision, preserving native approval UI."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

MAX_INPUT = 128 * 1024
MAX_CONTENT = 64 * 1024
APPROVAL_WAIT_SECONDS = 60
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())  # Local requests cannot leak through proxies or redirects.


def short_tool(name):
    return str(name).split('.')[-1].split('__')[-1]


def question_id(session, call, index):
    if not isinstance(session, str) or not session or not isinstance(call, str) or not call or len(call) > 256 or type(index) is not int or not 0 <= index < 32:
        return None
    return 'question-' + hashlib.sha256((session + '\0' + call + '\0' + str(index)).encode('utf-8')).hexdigest()


def diagnostic(config, record):
    if config.get('diagnosticLog'):
        try:
            with Path(config['diagnosticLog']).open('a', encoding='utf-8') as log:
                log.write(json.dumps({**record, 'at': time.time()}) + '\n')
        except OSError:
            pass


def replied_question_ids(payload):
    prompt = payload.get('prompt')
    if not isinstance(prompt, str):
        return []
    ids = set()
    for block in re.findall(r'<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>', prompt, re.S):
        try:
            replies = json.loads(block)
        except ValueError:
            continue
        if not isinstance(replies, list) or len(replies) > 32:
            continue
        for reply in replies:
            if not isinstance(reply, dict) or 'answer' not in reply or not isinstance(reply.get('questionItemId'), str):
                continue
            try:
                item = json.loads(reply['questionItemId'])
            except ValueError:
                continue
            if not isinstance(item, list) or len(item) != 3 or short_tool(item[0]) not in ('request_user_input', 'request_user_input_async'):
                continue
            id = question_id(payload.get('session_id'), item[1], item[2])
            if id:
                ids.add(id)
    return sorted(ids)


def completion_ids(payload):
    if payload.get('hook_event_name') == 'UserPromptSubmit':
        return replied_question_ids(payload)
    if payload.get('hook_event_name') != 'PostToolUse':
        return []
    name = short_tool(payload.get('tool_name'))
    if name not in ('request_user_input', 'request_user_input_async'):
        return []
    response = payload.get('tool_response')
    if name == 'request_user_input_async':
        # The immediate {accepted:true} is only an acknowledgement, not an answer.
        if not isinstance(response, dict) or not (response.get('answers') or response.get('accepted') is False):
            return []
    tool_input = payload.get('tool_input')
    questions = tool_input.get('questions') if isinstance(tool_input, dict) else None
    if not isinstance(questions, list) or len(questions) > 32:
        return []
    return [id for index in range(len(questions)) if (id := question_id(payload.get('session_id'), payload.get('tool_use_id'), index))]


def exchange(config, method, route, body=None, timeout=2):
    endpoint = config['endpoint']
    url = urlsplit(endpoint)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.query or url.fragment:
        raise ValueError('Bridge endpoint must be HTTP loopback')
    if not isinstance(config.get('token'), str) or len(config['token']) < 32:
        raise ValueError('Missing bridge access token')
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = Request(endpoint.rstrip('/') + route, data=data, method=method,
                      headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read(128 * 1024))


def question_content(tool_input):
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get('questions'), list):
        return None
    blocks = []
    for question in tool_input['questions']:
        if not isinstance(question, dict):
            return None
        text = question.get('question') or question.get('title')
        if not isinstance(text, str) or not text.strip():
            return None
        lines = [text.strip()]
        blocks.append('\n'.join(lines))
    if not blocks:
        return None
    if len(blocks) > 1:
        blocks = ['问题 ' + str(index) + '\n' + block for index, block in enumerate(blocks, 1)]
    return '\n\n'.join(blocks)


def normalize(payload):
    event = payload.get('hook_event_name')
    tool = str(payload.get('tool_name', ''))
    name = short_tool(tool)
    if event == 'PermissionRequest':
        kind, title = 'approval', '请求批准：' + tool
    elif event == 'PreToolUse' and name in ('request_user_input', 'request_user_input_async'):
        kind, title = 'question', 'Codex 有个问题'
    else:
        return None
    if not isinstance(payload.get('session_id'), str) or not payload['session_id']:
        return None
    tool_input = payload.get('tool_input', {})
    reason = ''
    if isinstance(tool_input, dict):
        for field in ('description', 'justification'):
            value = tool_input.get(field)
            if isinstance(value, str) and value.strip():
                reason = value.strip()
                break
    if kind == 'question':
        content = question_content(tool_input)
        if content is None:
            return None
    else:
        content = '\n'.join([
            '会话：' + payload['session_id'], '目录：' + str(payload.get('cwd', '')),
            '工具：' + tool, json.dumps(tool_input, ensure_ascii=False, indent=2),
        ])
    if len(content.encode('utf-8')) > MAX_CONTENT or len(reason.encode('utf-8')) > MAX_CONTENT:
        return None  # Do not silently truncate an approval's actual operation.
    id = question_id(payload['session_id'], payload.get('tool_use_id'), payload.get('_question_index', 0)) if kind == 'question' else None
    return {'id': id or str(uuid.uuid4()), 'kind': kind, 'session_id': payload['session_id'],
            'turn_id': str(payload.get('turn_id', '')), 'title': title[:160], 'content': content,
            'reason': reason, 'presentation': 'human',
            'project': str(payload.get('cwd', '')).replace('\\', '/').rstrip('/').split('/')[-1][:160] or '未命名项目',
            'lifecycle': 'hook'}


def run(payload, config, timeout=APPROVAL_WAIT_SECONDS, poll_interval=0.5):
    if config.get('safetyPause') is True:
        return None
    event = payload.get('hook_event_name')
    if event in ('UserPromptSubmit', 'PostToolUse'):
        ids = completion_ids(payload)
        cleared = 0
        for id in ids:
            try:
                exchange(config, 'DELETE', '/v1/requests/' + id)
                cleared += 1
            except Exception:
                break
        if ids:
            diagnostic(config, {'phase':'question_cleanup','matched':len(ids),'cleared':cleared})
        return None
    if payload.get('hook_event_name') in ('Interrupt', 'SessionEnd'):
        session = payload.get('session_id')
        if isinstance(session, str) and session:
            from urllib.parse import quote
            exchange(config, 'DELETE', '/v1/sessions/' + quote(session, safe=''))
        return None
    if event == 'PreToolUse' and short_tool(payload.get('tool_name')) in ('request_user_input', 'request_user_input_async'):
        tool_input = payload.get('tool_input')
        questions = tool_input.get('questions') if isinstance(tool_input, dict) else None
        if not isinstance(questions, list) or not 1 <= len(questions) <= 32:
            return None
        requests = [normalize({**payload, '_question_index':index, 'tool_input':{**tool_input,'questions':[question]}}) for index, question in enumerate(questions)]
        if any(request is None for request in requests):
            return None
        try:
            status = exchange(config, 'GET', '/v1/status')
            if status.get('enabled') and status.get('online'):
                for request in requests:
                    exchange(config, 'POST', '/v1/requests', request)
        except Exception:
            pass
        return None
    request = normalize(payload)
    if request is None:
        return None
    request_id = request['id']
    created = False
    desktop = None
    deadline = time.monotonic() + min(max(timeout, 0), APPROVAL_WAIT_SECONDS)
    def approval_exchange(method, route, body=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Approval wait expired')
        return exchange(config, method, route, body, timeout=min(2, remaining))
    try:
        status = approval_exchange('GET', '/v1/status')
        if not status.get('enabled') or not status.get('online'):
            return None
        created = True
        approval_exchange('POST', '/v1/requests', request)
        if request['kind'] == 'question':
            return None
        if config.get('desktopApproval', True):
            # Full content travels through a pipe, never command arguments.
            # The companion caches only a short pending-list summary locally.
            desktop = subprocess.Popen([sys.executable, str(Path(__file__).with_name('desktop_prompt.py'))],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            desktop.stdin.write(json.dumps({'config':config,'request':request}, ensure_ascii=False).encode('utf-8'))
            desktop.stdin.close()
        while time.monotonic() < deadline:
            response = approval_exchange('GET', '/v1/requests/' + request_id)
            if time.monotonic() >= deadline:
                return None  # A late answer cannot replace the native prompt.
            state = response.get('state')
            if response.get('id') != request_id or response.get('session_id') != request['session_id']:
                return None
            if state in ('allow', 'deny'):
                return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': {'behavior': state}}}
            if state != 'pending':
                return None
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        return None
    except Exception:
        return None
    finally:
        if desktop is not None and desktop.poll() is None:
            desktop.terminate()
            try:
                desktop.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                desktop.kill()
                desktop.wait(timeout=0.2)
        if desktop is not None and desktop.poll() is not None and isinstance(getattr(desktop,'pid',None),int):
            from desktop_queue import cleanup_process
            directory=Path(__file__).resolve().parents[1]/'.local/desktop-queue'/hashlib.sha256(config['endpoint'].encode()).hexdigest()[:16]
            cleanup_process(directory,getattr(desktop,'pid',None))
        if created and request['kind'] == 'approval':
            try:
                exchange(config, 'DELETE', '/v1/requests/' + request_id, timeout=0.5)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--owner', default='codex-band-bridge')
    args = parser.parse_args()
    try:
        tcl_config = Path(__file__).with_name('tcl-runtime.json')
        if tcl_config.is_file():
            libraries = json.loads(tcl_config.read_text(encoding='utf-8-sig'))
            for key, variable in (('tclLibrary', 'TCL_LIBRARY'), ('tkLibrary', 'TK_LIBRARY')):
                if libraries.get(key):
                    os.environ[variable] = libraries[key]
        if hasattr(sys.stdin, 'reconfigure'):
            sys.stdin.reconfigure(encoding='utf-8')
            sys.stdout.reconfigure(encoding='utf-8')
        raw = sys.stdin.read(MAX_INPUT + 1)
        if len(raw.encode('utf-8')) > MAX_INPUT:
            return
        payload = json.loads(raw)
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        approval_started = time.monotonic()
        if config.get('safetyPause') is True:
            return  # Preserve native approvals without touching the device bridge.
        try:
            exchange(config, 'POST', '/v1/hook-health', {'event':payload.get('hook_event_name')})
        except Exception:
            pass  # Health reporting cannot block or grant an approval.
        # Diagnostic metadata never records user answers, prompts or request bodies.
        preview = normalize(payload)
        diagnostic(config, {'event':payload.get('hook_event_name'),'tool':payload.get('tool_name'),
            'inputKeys':list(payload),'toolInputKeys':list(payload['tool_input']) if isinstance(payload.get('tool_input'),dict) else [],
            'reasonPresent':bool(preview and preview.get('reason'))})
        result = run(payload, config, timeout=max(0, APPROVAL_WAIT_SECONDS - (time.monotonic() - approval_started)))
        decision = result.get('hookSpecificOutput', {}).get('decision', {}).get('behavior') if result else None
        diagnostic(config, {'phase':'completed','event':payload.get('hook_event_name'),'decision':decision})
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except Exception:
        # No hook failure, no approval decision, no command/token leaked to logs.
        return


if __name__ == '__main__':
    main()
