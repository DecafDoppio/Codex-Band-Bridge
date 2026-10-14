"""Prepare local GitHub assets and AstroBox branch tree; never push or install."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpk', type=Path, help='External accepted RPK, for Connector only')
    args = parser.parse_args()
    watch = (ROOT / 'release.json').exists()
    version = (json.loads((ROOT / 'release.json').read_text(encoding='utf-8-sig'))['versionName'] if watch else (ROOT / 'VERSION').read_text().strip())
    if version != '1.3.1':
        raise RuntimeError('Review publication identity before exporting another version.')
    github = ROOT / '.publication/github-release'
    astrobox = ROOT / '.publication/astrobox'
    # Refuse to mix previous generations; remove/rename the local export deliberately before retrying.
    if github.exists() or astrobox.exists():
        raise RuntimeError('Export exists. Preserve or remove .publication before generating a new export.')
    if watch:
        artifact = args.rpk or ROOT / 'downloads/Codex-Band-Connector-1.3.1.rpk'
        expected = json.loads((ROOT / 'RELEASE_STATUS.json').read_text(encoding='utf-8-sig'))['artifactSha256']
        if sha(artifact) != expected:
            raise RuntimeError('RPK differs from the recorded accepted candidate.')
        with zipfile.ZipFile(artifact) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        if manifest['versionName'] != version or manifest['versionCode'] != 13001 or manifest['name'] != 'Codex Band Connector':
            raise RuntimeError('RPK release metadata differs.')
        github.mkdir(parents=True)
        target = github / ('Codex-Band-Connector-' + version + '.rpk')
        shutil.copy2(artifact, target)
        astrobox.mkdir(parents=True)
        shutil.copytree(ROOT / 'media', astrobox / 'media', ignore=shutil.ignore_patterns('cover.svg', 'preview-desktop-*.png'))
        shutil.copy2(ROOT / 'publishing/manifest_v2.json', astrobox / 'manifest_v2.json')
        (astrobox / 'downloads').mkdir()
        shutil.copy2(target, astrobox / 'downloads' / target.name)
        listing = json.loads((astrobox / 'manifest_v2.json').read_text(encoding='utf-8'))
        required = [listing['item'][key] for key in ('icon', 'cover')] + listing['item']['preview']
        required += [record['file_name'] for record in listing['downloads'].values()]
        for name in required:
            if not (astrobox / name).is_file():
                raise RuntimeError('Missing listing file: ' + name)
    else:
        if args.rpk:
            raise RuntimeError('--rpk is only for Connector.')
        manifest = json.loads((ROOT / 'astrobox/manifest.json').read_text(encoding='utf-8'))
        dist = ROOT / 'dist'
        built_manifest = json.loads((dist / 'manifest.json').read_text(encoding='utf-8-sig'))
        if {k:v for k,v in manifest.items() if k not in ('author', 'website')} != {k:v for k,v in built_manifest.items() if k not in ('author', 'website')}:
            raise RuntimeError('Built manifest differs beyond approved author/website metadata.')
        if manifest['version'] != version:
            raise RuntimeError('Plugin version mismatch.')
        extras = ['codex-hooks.zip', 'tcl-tk.zip', 'Configure-Codex.ps1', 'Review-Codex-Hooks.ps1']
        if manifest['additional_files'] != extras:
            raise RuntimeError('Required additional_files changed.')
        names = ['manifest.json', manifest['entry'], manifest['icon']] + extras
        for name in names:
            if not (dist / name).is_file():
                raise RuntimeError('Missing distribution input: ' + name)
        if (dist / manifest['entry']).read_bytes()[:8] != b'\x00asm\x0d\x00\x01\x00':
            raise RuntimeError('WASI component signature missing.')
        github.mkdir(parents=True)
        release = astrobox / 'release'
        release.mkdir(parents=True)
        shutil.copy2(ROOT / 'publishing/index.txt', astrobox / 'index.txt')
        for name in names:
            if name == 'manifest.json':
                shutil.copy2(ROOT / 'astrobox/manifest.json', release / name)
            elif name == 'codex-hooks.zip':
                with zipfile.ZipFile(dist / name) as source, zipfile.ZipFile(release / name, 'w', zipfile.ZIP_DEFLATED) as target_zip:
                    for info in source.infolist():
                        data = source.read(info.filename)
                        if info.filename in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
                            data = (ROOT / info.filename).read_bytes()
                        target_zip.writestr(info, data)
            else:
                shutil.copy2(dist / name, release / name)
        target = github / ('Codex-Band-Bridge-' + version + '.abp')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.write(release / name, name)
    checksums = ''.join(sha(path) + '  ' + path.name + '\n' for path in sorted(github.iterdir()) if path.is_file())
    (github / 'SHA256SUMS.txt').write_text(checksums, encoding='utf-8')
    print(json.dumps({'version':version, 'artifact':target.name, 'sha256':sha(target), 'astroboxFiles':sorted(p.relative_to(astrobox).as_posix() for p in astrobox.rglob('*') if p.is_file()), 'pushed':False}, ensure_ascii=False))

if __name__ == '__main__':
    main()
