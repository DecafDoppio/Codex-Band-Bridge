"""Run the published installer against a temporary plugin and Codex home."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PS=shutil.which('powershell.exe')

@unittest.skipUnless(PS,'Windows PowerShell required')
class ConfigureIntegrationTests(unittest.TestCase):
    def test_install_is_local_and_repeatable_and_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            base=Path(tmp);plugin=base/'plugin';home=base/'codex';home.mkdir()
            with zipfile.ZipFile(ROOT/'dist/Codex-Band-Bridge-1.3.0.abp') as z:z.extractall(plugin)
            (plugin/'bridge-client.json').write_text(json.dumps({'endpoint':'http://127.0.0.1:39007','token':'t'*64,'deliveryMode':'launch','setupApiVersion':1,'setupEpoch':'isolated'}))
            other={'type':'command','command':'echo unrelated'}
            (home/'hooks.json').write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[other]}]}}))
            # The Codex shell includes bundled PowerShell 7 modules. A real
            # PowerShell 5.1 session uses its own Windows module directory.
            modules=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')
            env=dict(os.environ,LOCALAPPDATA=str(base/'local'),CODEX_HOME=str(home),PYTHONIOENCODING='utf-8',PSModulePath=modules)
            before=Path(sys.executable).stat().st_mtime_ns
            for _ in range(2):
                result=subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(plugin/'Configure-Codex.ps1'),'-PythonPath',sys.executable,'-ExpectedEpoch','isolated'],env=env,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,0,(result.stdout,result.stderr))
                hooks=json.loads((home/'hooks.json').read_text(encoding='utf-8-sig'))
                handlers=[h for groups in hooks['hooks'].values() for g in groups for h in g['hooks']]
                self.assertIn(other,handlers);self.assertEqual(len(handlers),6)
                pointer=json.loads((base/'local/CodexBandBridge/current.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(pointer['pythonPath'],sys.executable)
                self.assertEqual(Path(pointer['bridgeConfigPath']),plugin/'bridge-client.json')
                self.assertTrue((Path(pointer['path'])/'codex-hook/bridge_hook.py').exists())
                self.assertFalse((base/'local/CodexBandBridge/tcl-tk').exists())
                self.assertFalse((base/'local/CodexBandBridge/runtimes').exists())
            self.assertEqual(Path(sys.executable).stat().st_mtime_ns,before)
            self.assertTrue(list(home.glob('hooks.json.band-backup-*')))

if __name__=='__main__':unittest.main()
