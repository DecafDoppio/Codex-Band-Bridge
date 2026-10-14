import importlib.util
import json
import subprocess
import sys
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', root / 'scripts/install_hooks.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_cleared_hooks_install_and_backup_the_original_bytes(self):
        for raw in (b'',b' \r\n\t',b'\xef\xbb\xbf'):
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as folder:
                base=Path(folder);output=base/'hooks.json';config=base/'client.json';output.write_bytes(raw)
                config.write_text(json.dumps({'endpoint':'http://127.0.0.1:37121','token':'x'*64,'deliveryMode':'launch','setupApiVersion':1}),encoding='utf-8')
                with patch.object(installer,'ROOT',base),patch.object(sys,'argv',['install_hooks.py','--bridge-config',str(config),'--output',str(output),'--activate-local']):installer.main()
                data=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(set(data['hooks']),set(installer.generated_groups(config)))
                self.assertEqual(next(base.glob('hooks.json.band-backup-*')).read_bytes(),raw)

    def test_invalid_nonempty_hooks_are_preserved_without_installing(self):
        for raw in ('broken JSON','[]','{"hooks":null}'):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'hooks.json';path.write_text(raw,encoding='utf-8')
                with self.assertRaises(RuntimeError):installer.read_hooks(path)
                self.assertEqual(path.read_text(encoding='utf-8'),raw)

    def test_lightweight_activation_keeps_the_plugin_gate_and_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);config=base/'client.json';output=base/'hooks.json'
            config.write_text(json.dumps({'endpoint':'http://127.0.0.1:37121','token':'x'*64,'deliveryMode':'launch','setupApiVersion':1,'safetyPause':True}),encoding='utf-8')
            other={'hooks':[{'type':'command','command':'echo untouched'}]}
            output.write_text(json.dumps({'hooks':{'PermissionRequest':[other]}}),encoding='utf-8')
            with patch.object(installer,'ROOT',base),patch.object(sys,'argv',['install_hooks.py','--bridge-config',str(config),'--output',str(output),'--activate-local']):
                installer.main()
            saved=json.loads((base/'.local/bridge.json').read_text(encoding='utf-8'))
            self.assertFalse(saved['safetyPause']);self.assertNotIn('allow',saved)
            data=json.loads(output.read_text(encoding='utf-8'));self.assertIn(other,data['hooks']['PermissionRequest'])
    def test_resume_requires_verified_enabled_launch_mode(self):
        status={'pluginVersion':'1.1.0','deliveryMode':'launch','safetyPaused':False,'launchValidated':True,'launchFaulted':False}
        installer.validate_launch_status(status)
        for key,value in [('pluginVersion','1.0.2'),('deliveryMode','notification'),('safetyPaused',True),('launchValidated',False),('launchFaulted',True)]:
            with self.assertRaises(RuntimeError):installer.validate_launch_status({**status,key:value})
        with self.assertRaises(RuntimeError):installer.validate_launch_status({})
    def test_minimal_profile_keeps_question_lifecycle_and_omits_optional_interrupt(self):
        groups=installer.generated_groups(root/'.local/bridge.json')
        self.assertEqual(set(groups),{'PermissionRequest','PreToolUse','PostToolUse','UserPromptSubmit','SessionEnd'})
        self.assertIn('request_user_input',groups['PreToolUse']['matcher'])
        self.assertIn('Interrupt',installer.generated_groups(root/'.local/bridge.json',True))
    def test_uninstall_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'hooks.json'
            ours = installer.generated_groups(root / '.local/bridge.json')['PermissionRequest']
            other = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'echo other'}]}
            target.write_text(json.dumps({'description': 'user', 'hooks': {'PermissionRequest': [other, ours]}}), encoding='utf-8')
            result = subprocess.run([sys.executable, str(root / 'scripts/install_hooks.py'), '--output', str(target), '--uninstall'], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(target.read_text())['hooks']['PermissionRequest'], [other])
            self.assertEqual(json.loads(target.read_text())['description'], 'user')
            self.assertEqual(len(list(target.parent.glob('*.band-backup-*'))), 1)

    def test_groups_use_only_documented_fields_and_no_trust_bypass(self):
        for group in installer.generated_groups(root / '.local/bridge.json').values():
            self.assertLessEqual(set(group), {'matcher', 'hooks'})
            for handler in group['hooks']:
                self.assertNotIn('bypass', handler['command'])
                self.assertIn('powershell.exe -NoProfile -NonInteractive', handler['command'])


if __name__ == '__main__':
    unittest.main()
