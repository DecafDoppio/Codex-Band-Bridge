"""Run the copied command with Windows PowerShell 5.1 and isolated plugin files."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class HookCommandTests(unittest.TestCase):
    def run_command(self, epoch='current', present=True):
        source = (ROOT/'astrobox/src/hook_commands.rs').read_text(encoding='utf-8')
        template = re.search(r'format!\(r#"(.*?)"#,', source, re.S).group(1)
        version=(ROOT/'VERSION').read_text().strip()
        command = template.format('', name='Configure-Codex.ps1', version=version, epoch='current')
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            base = Path(folder)
            plugin = base/'moe.astralsight.astrobox/plugins/Codex Band Bridge'
            plugin.mkdir(parents=True)
            # Chinese UTF-8 without BOM reproduced the manifest parser failure.
            (plugin/'manifest.json').write_text(json.dumps({'name':'Codex Band Bridge', 'version':version, 'description':'发送授权请求到手环。'}, ensure_ascii=False), encoding='utf-8')
            (plugin/'bridge-client.json').write_text(json.dumps({'setupEpoch':epoch}), encoding='utf-8')
            if present:
                (plugin/'Configure-Codex.ps1').write_text("param([string]$ExpectedEpoch)\nWrite-Output ('STUB_INSTALLED:'+ $ExpectedEpoch)\n", encoding='utf-8-sig')
            file = base/'copied.ps1'
            file.write_text(command, encoding='utf-8-sig')
            env = dict(os.environ, APPDATA=str(base))
            return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(file)], env=env, capture_output=True)

    def test_chinese_manifest_finds_current_instance(self):
        result = self.run_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'STUB_INSTALLED:current', result.stdout)

    def test_stale_instance_stops_before_installer(self):
        result = self.run_command(epoch='stale')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'STUB_INSTALLED:', result.stdout)
        self.assertNotIn(b'File parameter', result.stderr)

    def test_missing_script_stops_before_installer(self):
        result = self.run_command(present=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'STUB_INSTALLED:', result.stdout)


if __name__ == '__main__':
    unittest.main()
