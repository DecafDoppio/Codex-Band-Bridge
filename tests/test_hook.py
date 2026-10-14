import importlib.util
import json
import threading
import subprocess
import tempfile
import unittest
import io
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location('bridge_hook', Path(__file__).parents[1] / 'codex-hook' / 'bridge_hook.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer ' + self.server.token:
            return self.reply({}, 401)
        if self.path == '/v1/status':
            if getattr(self.server, 'redirect', False):
                self.send_response(302)
                self.send_header('Location', 'http://localhost:' + str(self.server.server_port) + '/steal')
                self.end_headers()
                return
            return self.reply({'enabled': self.server.enabled, 'online': self.server.online})
        if self.path == '/steal':
            self.server.leaked = True
            return self.reply({})
        request = self.server.request
        self.reply({'id': request['id'], 'session_id': self.server.session or request['session_id'], 'state': self.server.state})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/hook-health':
            return self.reply({'ok': True})
        if self.path == '/v1/questions':
            self.server.request=body['requests'][0]
            return self.reply({'created':len(body['requests'])},201)
        self.server.request = body
        self.reply({'id': self.server.request['id']}, 201)

    def do_DELETE(self):
        self.server.cancelled = True
        self.reply({})


class HookTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.token = 'a' * 64
        self.server.enabled = self.server.online = True
        self.server.state = 'allow'
        self.server.session = None
        self.server.request = None
        self.server.cancelled = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = {'desktopApproval':False, 'endpoint': 'http://127.0.0.1:' + str(self.server.server_port), 'token': self.server.token}
        self.payload = {'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash', 'session_id': 'session', 'turn_id': 'turn', 'cwd': 'C:/项目', 'tool_input': {'command': 'echo harmless', 'description': '无害测试'}}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_safety_pause_never_contacts_bridge(self):
        from unittest.mock import patch
        with patch.object(hook, 'exchange', side_effect=AssertionError('unexpected HTTP')):
            self.assertIsNone(hook.run(self.payload, {**self.config, 'safetyPause': True}))
        self.assertIsNone(self.server.request)

    def test_allow_and_deny_map_to_official_output(self):
        for behavior in ('allow', 'deny'):
            self.server.state = behavior
            result = hook.run(self.payload, self.config, timeout=1)
            self.assertEqual(result['hookSpecificOutput']['decision']['behavior'], behavior)
            self.assertTrue(self.server.cancelled)

    def test_companion_exit_does_not_pause_or_cancel_the_watch_request(self):
        class ClosedCard:
            stdin=io.BytesIO()
            def poll(self):return 0
        self.server.state='allow'
        with patch.object(hook.subprocess,'Popen',return_value=ClosedCard()):
            result=hook.run(self.payload,{**self.config,'desktopApproval':True},timeout=1)
        self.assertEqual(result['hookSpecificOutput']['decision']['behavior'],'allow')
        self.assertTrue(self.server.online)

    def test_expired_disabled_and_disconnected_make_no_decision(self):
        self.server.state = 'expired'
        self.assertIsNone(hook.run(self.payload, self.config, timeout=1))
        self.server.online = False
        self.server.request = None
        self.assertIsNone(hook.run(self.payload, self.config))
        self.assertIsNone(self.server.request)

    def test_timeout_cancels_pending_request(self):
        self.server.state = 'pending'
        self.assertIsNone(hook.run(self.payload, self.config, timeout=0.04, poll_interval=0.01))
        self.assertTrue(self.server.cancelled)

    def test_different_session_never_approves(self):
        self.server.session = 'wrong'
        self.assertIsNone(hook.run(self.payload, self.config, timeout=1))

    def test_question_is_fire_and_forget(self):
        for tool in ('request_user_input', 'functions.request_user_input_async'):
            self.payload.update(hook_event_name='PreToolUse', tool_name=tool, tool_input={'questions':[{'question':'保留设置吗？','options':[{'label':'保留'},{'label':'恢复默认'}]}]})
            self.assertIsNone(hook.run(self.payload, self.config))
            self.assertEqual(self.server.request['kind'], 'question')
            self.assertFalse(self.server.cancelled)

    def test_long_input_never_silently_truncates(self):
        self.payload['tool_input']['command'] = '中' * 30000
        self.assertIsNone(hook.normalize(self.payload))
        self.payload['tool_input']['command'] = '中文命令'
        self.assertIn('中文命令', hook.normalize(self.payload)['content'])

    def test_reason_is_exact_codex_text_and_command_remains_complete(self):
        item = hook.normalize(self.payload)
        self.assertEqual(item['reason'], '无害测试')
        self.assertIn('echo harmless', item['content'])
        self.payload['tool_input'].pop('description')
        self.assertEqual(hook.normalize(self.payload)['reason'], '')
        self.payload['tool_input']['justification'] = '读取模拟器状态以检查连接'
        self.assertEqual(hook.normalize(self.payload)['reason'], '读取模拟器状态以检查连接')

    def test_only_loopback_and_valid_token_allowed(self):
        for endpoint in ('https://127.0.0.1:10', 'http://example.com', 'http://127.0.0.1@evil.test'):
            with self.assertRaises(ValueError):
                hook.exchange({'endpoint': endpoint, 'token': 'a' * 64}, 'GET', '/v1/status')

    def test_windows_hook_command_preserves_unicode_input_and_paths(self):
        installer_spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'scripts/install_hooks.py')
        installer = importlib.util.module_from_spec(installer_spec)
        installer_spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / '连接 配置.json'
            config.write_text(json.dumps(self.config), encoding='utf-8')
            command = installer.generated_groups(config)['PermissionRequest']['hooks'][0]['command']
            result = subprocess.run(command, shell=True, input=json.dumps(self.payload, ensure_ascii=False).encode('utf-8'), capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['decision']['behavior'], 'allow')
            self.assertIn('无害测试', self.server.request['content'])

    def test_redirect_never_exports_token_or_request(self):
        self.server.redirect = True
        self.server.leaked = False
        self.assertIsNone(hook.run(self.payload, self.config))
        self.assertFalse(self.server.leaked)

    def test_interrupt_cancels_without_approving(self):
        self.payload['hook_event_name'] = 'Interrupt'
        self.assertIsNone(hook.run(self.payload, self.config))
        self.assertTrue(self.server.cancelled)


if __name__ == '__main__':
    unittest.main()
