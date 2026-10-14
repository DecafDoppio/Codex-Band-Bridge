import importlib.util,json,tempfile,unittest,sys
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'codex-hook'))
from stable_entry import resolve_target
spec=importlib.util.spec_from_file_location('stable_installer',ROOT/'scripts/install_hooks.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class StableEntryTests(unittest.TestCase):
    def test_commands_do_not_contain_release_or_plugin_configuration_paths(self):
        root=Path('C:/fixed/bridge')
        with patch.object(installer,'ROOT',root/'releases'/('a'*64)):
            a=installer.generated_groups(root/'current.json',entry=root/'codex_band_hook.py')
        with patch.object(installer,'ROOT',root/'releases'/('b'*64)):
            b=installer.generated_groups(root/'current.json',entry=root/'codex_band_hook.py')
        self.assertEqual(a,b)
        self.assertTrue(all(installer.owns(h) for g in a.values() for h in g['hooks']))

    def test_pointer_switches_release_and_keeps_live_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'bridge-client.json';config.write_text('{}')
            pointer=root/'current.json'
            for tag in ('a'*64,'b'*64):
                release=root/'releases'/tag;script=release/'codex-hook/bridge_hook.py'
                script.parent.mkdir(parents=True);script.write_text('')
                pointer.write_text(json.dumps({'path':str(release),'sha256':tag,'bridgeConfigPath':str(config)}))
                self.assertEqual(resolve_target(pointer),(script.resolve(),config))
                config.write_text('{"token":"changed"}')
                self.assertEqual(resolve_target(pointer)[1],config)

    def test_external_release_and_missing_config_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pointer=root/'current.json'
            pointer.write_text(json.dumps({'path':str(root/'outside'/('a'*64)),'sha256':'a'*64,'bridgeConfigPath':str(root/'missing')}))
            with self.assertRaises(ValueError):resolve_target(pointer)

if __name__=='__main__':unittest.main()
