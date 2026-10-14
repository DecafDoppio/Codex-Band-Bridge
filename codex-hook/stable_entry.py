"""Fixed Hook entry: follow the installed release and read the live plugin export.

No trust records are changed. A missing/invalid installation produces no decision.
"""
import argparse
import json
import re
import runpy
import sys
from pathlib import Path


def resolve_target(pointer):
    pointer=Path(pointer).resolve()
    data=json.loads(pointer.read_text(encoding='utf-8-sig'))
    release=Path(data['path']).resolve()
    releases=(pointer.parent/'releases').resolve()
    if release.parent!=releases or not re.fullmatch(r'[0-9a-f]{64}',release.name) or data.get('sha256')!=release.name:
        raise ValueError('Invalid installed release pointer')
    script=release/'codex-hook/bridge_hook.py'
    config=Path(data['bridgeConfigPath'])
    if not config.is_absolute() or not config.is_file() or not script.is_file():
        raise ValueError('Missing live plugin configuration or Hook script')
    return script,config


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--owner',default='codex-band-bridge')
    args=parser.parse_args()
    try:
        script,config=resolve_target(args.config)
        sys.path.insert(0,str(script.parent))
        sys.argv=[str(script),'--config',str(config),'--owner','codex-band-bridge']
        runpy.run_path(str(script),run_name='__main__')
    except Exception:
        return  # Preserve Codex's native approval path on failure.


if __name__=='__main__':
    main()
