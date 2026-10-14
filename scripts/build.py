"""Compile locked plugin sources and package the unchanged runtime files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOOK_FILES = [
    'VERSION', 'codex-hook/bridge_hook.py', 'codex-hook/desktop_prompt.py',
    'codex-hook/desktop_queue.py', 'codex-hook/desktop_monitors.py',
    'codex-hook/command_format.py', 'codex-hook/stable_entry.py',
    'scripts/install_hooks.py', 'scripts/desktop_doctor.py',
    'scripts/Review-Codex-Hooks.ps1', 'assets/brand/icon-48.png',
    'assets/brand/icon-96.png',
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_identity():
    paths = [ROOT / name for name in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'VERSION', 'astrobox/manifest.json')]
    for directory in ('astrobox', 'bridge-core', 'codex-hook', 'scripts', 'assets/brand'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(paths))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo', default='cargo', help='Optional installed Cargo executable')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'astrobox/manifest.json').read_text(encoding='utf-8'))
    version = (ROOT / 'VERSION').read_text().strip()
    if manifest['version'] != version:
        raise RuntimeError('Source and plugin manifest versions differ.')
    original_sources = source_identity()
    env = os.environ.copy()
    # Remove usernames/build locations from compiled diagnostic metadata.
    flags = env.get('CARGO_ENCODED_RUSTFLAGS', '').split('\x1f') if env.get('CARGO_ENCODED_RUSTFLAGS') else []
    if not flags and env.get('RUSTFLAGS'):
        raise RuntimeError('Use CARGO_ENCODED_RUSTFLAGS for extra flags so paths containing spaces remain intact.')
    roots = [(ROOT, '/codex-band-bridge')]
    cargo_home = Path(env.get('CARGO_HOME', str(Path.home() / '.cargo'))).resolve()
    roots.append((cargo_home, '/cargo-home'))
    for source, replacement in roots:
        for prefix in set((str(source), source.as_posix())):
            flags.append('--remap-path-prefix=' + prefix + '=' + replacement)
    env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
    command = [args.cargo, 'build', '-p', 'codex-band-bridge', '--target', 'wasm32-wasip3', '--release', '--locked']
    if args.offline:
        command.append('--offline')
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    target = Path(env.get('CARGO_TARGET_DIR', str(ROOT / 'target')))
    if not target.is_absolute():
        target = ROOT / target
    wasm = target / 'wasm32-wasip3/release/codex_band_bridge.wasm'
    if wasm.read_bytes()[:8] != b'\x00asm\x0d\x00\x01\x00':
        raise RuntimeError('Expected WASI component output is missing.')
    if source_identity() != original_sources:
        raise RuntimeError('Product inputs changed during the build.')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    shutil.copy2(wasm, dist / manifest['entry'])
    shutil.copy2(ROOT / 'astrobox/manifest.json', dist / 'manifest.json')
    shutil.copy2(ROOT / 'astrobox/icon.png', dist / 'icon.png')
    with zipfile.ZipFile(dist / 'codex-hooks.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in HOOK_FILES + ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
            archive.write(ROOT / name, name)
        for path in sorted((ROOT / 'LICENSES').rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT).as_posix())
    shutil.copy2(ROOT / 'third_party/tcl-tk/tcl-tk.zip', dist / 'tcl-tk.zip')
    for name in ('Configure-Codex.ps1', 'Review-Codex-Hooks.ps1'):
        shutil.copy2(ROOT / 'scripts' / name, dist / name)
    required_extras = {'codex-hooks.zip', 'tcl-tk.zip', 'Configure-Codex.ps1', 'Review-Codex-Hooks.ps1'}
    if set(manifest['additional_files']) != required_extras:
        raise RuntimeError('Runtime additional_files changed unexpectedly.')
    names = ['manifest.json', manifest['entry'], manifest['icon']] + manifest['additional_files']
    for name in names:
        if not (dist / name).is_file():
            raise RuntimeError('Required distribution file missing: ' + name)
    with zipfile.ZipFile(dist / ('Codex-Band-Bridge-' + version + '.abp'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(dist / name, name)
    record = {'version': version, 'sourceFiles': original_sources,
              'runtimeSourceChanged': False, 'compilerPathRemapping': True,
              'artifacts': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted([dist / name for name in names] + [dist / ('Codex-Band-Bridge-' + version + '.abp')])}}
    (dist / 'build-manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'version': version, 'wasmSha256': digest(dist / manifest['entry']), 'distFiles': names}, ensure_ascii=False))

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
