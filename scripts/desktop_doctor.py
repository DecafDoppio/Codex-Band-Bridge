"""Read-only setup check; prints no access tokens, prompts or answers."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=ROOT/'.local/bridge.json')
    args=parser.parse_args()
    print('Python:',sys.version.split()[0],sys.executable)
    try:
        import tkinter
        print('Tkinter/Tcl:',tkinter.Tcl().eval('info patchlevel'),'可用')
    except Exception:
        print('Tkinter 不可用：请安装 Windows 官方 Python 并勾选 Tcl/Tk。');return 1
    if not args.config.exists():
        print('尚未配置连接：在 AstroBox 启动插件，然后运行 install_hooks.py。');return 1
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    spec=importlib.util.spec_from_file_location('bridge_hook',ROOT/'codex-hook/bridge_hook.py')
    hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
    print('电脑授权窗口:', '启用' if config.get('desktopApproval',True) else '关闭')
    print('通道:', '真机 AstroBox' if config.get('endpoint')=='http://127.0.0.1:37121' else '自定义／模拟器，转真机时需更换插件导出的配置')
    try:
        status=hook.exchange(config,'GET','/v1/status')
        print('桥接服务:', '开启' if status.get('enabled') else '关闭')
        print('设备通道:', '已连接' if status.get('online') else '未连接')
        if 'watchHandshake' in status:
            print('手环应用握手:', '已收到' if status['watchHandshake'] else '尚未收到')
            print('接收帧数:',status.get('watchRxCount','旧版本未提供'))
            print('最近帧类型:',status.get('watchRxKind') or '无')
            print('互联回复:',status.get('watchReplyError') or '未记录失败')
    except Exception:
        print('桥接服务无法访问：检查 AstroBox 插件、端口和本地配置。');return 1
    print('Hook 信任状态需在 Codex 官方审核界面确认；此工具不读取或写入信任记录。')
    return 0


if __name__=='__main__':
    sys.exit(main())
