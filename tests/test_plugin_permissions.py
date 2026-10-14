"""Regression for the independently gated registration capability in AstroBox."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class PluginPermissionTests(unittest.TestCase):
    def test_clipboard_uses_the_actual_host_write_capability_and_light_scripts_are_declared(self):
        manifest=json.loads((ROOT/'astrobox/manifest.json').read_text(encoding='utf-8'))
        self.assertIn('clipboard.write',manifest['permissions']);self.assertNotIn('clipboard',manifest['permissions'])
        self.assertEqual(set(manifest['additional_files']),{'codex-hooks.zip','tcl-tk.zip','Configure-Codex.ps1','Review-Codex-Hooks.ps1'})
    def test_stable_identity_permission_is_declared_and_token_fallback_is_absent(self):
        manifest=json.loads((ROOT/'astrobox/manifest.json').read_text(encoding='utf-8'))
        self.assertIn('os.device-id',manifest['permissions'])
        source=(ROOT/'astrobox/src/lib.rs').read_text(encoding='utf-8')
        self.assertNotIn('unwrap_or_else(|_| config.token.clone())',source)
        self.assertNotIn('notification',manifest['permissions'])
    def test_receive_registration_has_its_own_declared_permission(self):
        manifest=json.loads((ROOT/'astrobox/manifest.json').read_text(encoding='utf-8'))
        # Official PluginSystem src/v4/host/register.rs calls
        # check_permission_declared(..., "register_interconnect_recv", ...).
        # src/api/host/permission.rs performs exact name matching, no aliases.
        self.assertIn('register_interconnect_recv',manifest['permissions'])
        self.assertIn('interconnect',manifest['permissions'])
        self.assertNotIn('http-server.lan',manifest['permissions'])
        self.assertEqual(len(manifest['permissions']),len(set(manifest['permissions'])))


if __name__=='__main__':
    unittest.main()
