"""Install only this bridge's hooks; preserve every unrelated hook and config."""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'codex-hook'))
from command_format import format_command, decode_command
OWNER = 'codex-band-bridge'


def read_hooks(path):
    if not path.exists():return {'hooks': {}}
    text=path.read_text(encoding='utf-8-sig')
    # An intentionally cleared file is a valid empty starting point, including
    # BOM-only and whitespace-only files. Its bytes are backed up before writing.
    if not text.strip():return {'hooks': {}}
    try:data=json.loads(text)
    except ValueError as error:
        raise RuntimeError(f'hooks.json 不是有效 JSON（第{error.lineno}行）；保留原文件，请修正内容或将其完全清空。') from error
    if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict):
        raise RuntimeError('hooks.json 必须是包含 hooks 对象的 JSON；保留原文件。')
    return data


def plugin_config():
    base = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'moe.astralsight.astrobox/plugins'
    if not base.exists():
        raise RuntimeError('请先在 AstroBox 安装并启动 Codex Band Bridge 插件。')
    for manifest in base.rglob('manifest.json'):
        try:
            if json.loads(manifest.read_text(encoding='utf-8-sig')).get('name') == 'Codex Band Bridge':
                config = manifest.parent / 'bridge-client.json'
                if config.exists():
                    return config
        except (OSError, ValueError):
            continue
    raise RuntimeError('未找到插件导出的 bridge-client.json。先打开插件、绑定手环并启动桥接；也可传入 --bridge-config 路径。')


def owns(handler):
    script = str(ROOT / 'codex-hook/bridge_hook.py')
    command=decode_command(handler.get('command',''))
    return script in command or (any(name in command for name in ('bridge_hook.py','codex_band_hook.py')) and '--owner codex-band-bridge' in command)


def belongs(group):
    return any(owns(item) for item in group.get('hooks', []))


def owned_snapshot(data):
    return {event:[{**group,'hooks':[h for h in group.get('hooks',[]) if owns(h)]}
        for group in groups if belongs(group)] for event,groups in data.get('hooks',{}).items()
        if isinstance(groups,list) and any(belongs(group) for group in groups)}


def generated_groups(config, include_interrupt=False, entry=None):
    # Codex executes command hooks in the user's shell. Use a PowerShell-native
    # literal invocation, including quoted paths containing Chinese/spaces.
    command = format_command(sys.executable,entry or ROOT/'codex-hook/bridge_hook.py',config)
    handler = {'type': 'command', 'command': command, 'timeout': 60}
    question_handler = {**handler, 'timeout': 5}
    cleanup_handler = {**handler, 'timeout': 3}
    groups = {
        'PermissionRequest': {'hooks': [handler]},
        'PreToolUse': {'matcher': r'(^|\.|__)request_user_input(_async)?$', 'hooks': [question_handler]},
        'PostToolUse': {'matcher': r'(^|\.|__)request_user_input(_async)?$', 'hooks': [cleanup_handler]},
        'UserPromptSubmit': {'hooks': [cleanup_handler]},
        'SessionEnd': {'hooks': [cleanup_handler]},
    }
    if include_interrupt:
        groups['Interrupt']={'hooks':[cleanup_handler]}
    return groups


def validate_launch_status(status):
    compatible=status.get('pluginVersion') in ('1.1.0','1.1.1') or status.get('setupApiVersion')==1
    if not compatible or status.get('deliveryMode')!='launch' or status.get('safetyPaused') is not False or status.get('launchValidated') is not True or status.get('launchFaulted') is not False:
        raise RuntimeError('请先启动兼容的电脑插件，通过仅唤起测试，再启用方案B。Hook保持暂停。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bridge-config', type=Path)
    parser.add_argument('--output', type=Path, help='Generate reviewable hooks file without touching user configuration')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--hooks-only', action='store_true', help='Keep existing local connection config; update only hooks')
    parser.add_argument('--include-interrupt', action='store_true', help='Optional immediate question cleanup on interrupt')
    parser.add_argument('--resume-launch', action='store_true', help='Resume only verified Scheme B; system notification remains disabled')
    parser.add_argument('--activate-local', action='store_true', help='Enable the local adapter; actual delivery remains gated by the plugin master switch and verified connection')
    parser.add_argument('--stable-entry',type=Path)
    parser.add_argument('--stable-pointer',type=Path)
    args = parser.parse_args()
    if bool(args.stable_entry)!=bool(args.stable_pointer):
        raise RuntimeError('Stable entry and pointer must be provided together.')
    config_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    destination = args.output or config_home / 'hooks.json'
    data = read_hooks(destination)
    previous_owned=owned_snapshot(data)
    hooks = data.setdefault('hooks', {})
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise RuntimeError('现有 hooks.json 的结构不符合官方格式；保持原文件不变。')
        hooks[event] = [{**group,'hooks':[item for item in group.get('hooks',[]) if not owns(item)]} for group in groups]
        hooks[event] = [group for group in hooks[event] if group['hooks']]
        if not hooks[event]:
            del hooks[event]
    if not args.uninstall:
        source = ROOT / '.local/bridge.json' if args.hooks_only else args.bridge_config or plugin_config()
        client = json.loads(source.read_text(encoding='utf-8-sig'))
        if not isinstance(client.get('token'), str) or len(client['token']) < 32:
            raise RuntimeError('插件连接配置缺少随机访问令牌。')
        if args.activate_local:
            from urllib.parse import urlparse
            parsed=urlparse(client.get('endpoint',''))
            if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or client.get('deliveryMode')!='launch' or client.get('setupApiVersion')!=1:
                raise RuntimeError('仅允许本机方案B接入；未修改暂停状态。')
            client['safetyPause']=False
            client['desktopApproval']=True
        if args.resume_launch:
            from urllib.request import Request, build_opener, HTTPRedirectHandler
            from urllib.parse import urlparse
            endpoint=client.get('endpoint','')
            parsed=urlparse(endpoint)
            if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password:
                raise RuntimeError('方案B仅允许本机回环连接。')
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    raise RuntimeError('拒绝桥接状态接口重定向，Hook保持暂停。')
            with build_opener(NoRedirect()).open(Request(endpoint+'/v1/status',headers={'Authorization':'Bearer '+client['token']}),timeout=5) as reply:
                status=json.load(reply)
            validate_launch_status(status)
            client['safetyPause']=False
            client['desktopApproval']=True
        # Config always stays local and is never included in distributable packages.
        config = ROOT / '.local/bridge.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve()!=config.resolve() or args.resume_launch or args.activate_local:
            paused = config.exists() and json.loads(config.read_text(encoding='utf-8-sig')).get('safetyPause') is True
            if paused and not args.resume_launch and not args.activate_local:
                client['safetyPause'] = True
            if config.exists():shutil.copy2(config,config.with_name(config.name+'.backup'))
            staging=config.with_name(config.name+'.tmp')
            with staging.open('w',encoding='utf-8') as stream:
                stream.write(json.dumps(client,ensure_ascii=False,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
            staging.replace(config)
        for event, group in generated_groups(args.stable_pointer or config,args.include_interrupt,args.stable_entry).items():
            hooks.setdefault(event, []).append(group)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.copy2(destination, destination.with_name(destination.name + '.band-backup-' + str(time.time_ns())))
    temporary = destination.with_name(destination.name + '.band-tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        stream.write(json.dumps(data,ensure_ascii=False,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    temporary.replace(destination)
    if args.uninstall:
        print('已移除本插件钩子，其他配置保留。')
    elif previous_owned==owned_snapshot(data):
        print('HOOK_DEFINITIONS_UNCHANGED')
        print('钩子定义未变，已信任者无需重复信任。')
    else:
        print('钩子定义已更新，请进入 ChatGPT 客户端 → 设置 → 钩子 → 信任全部。')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
