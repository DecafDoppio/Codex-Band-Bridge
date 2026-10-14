import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('deadline_hook',Path(__file__).parents[1]/'codex-hook/bridge_hook.py')
hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)

class DeadlineTests(unittest.TestCase):
    def test_official_hook_timeout_is_also_sixty_seconds(self):
        path=Path(__file__).parents[1]/'scripts/install_hooks.py'
        spec=importlib.util.spec_from_file_location('deadline_installer',path)
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        groups=installer.generated_groups(Path('current.json'))
        self.assertEqual(groups['PermissionRequest']['hooks'][0]['timeout'],60)
        self.assertEqual(groups['PreToolUse']['hooks'][0]['timeout'],5)
        self.assertEqual(groups['SessionEnd']['hooks'][0]['timeout'],3)
    def test_timeout_is_per_request_and_next_request_can_approve(self):
        now=[0.0];calls=[];mode=['pending']
        request={'id':'first','session_id':'s','kind':'approval'}
        config={'desktopApproval':False}
        def exchange(cfg,method,path,body=None,timeout=2):
            calls.append((method,path,timeout))
            if path=='/v1/status':return {'enabled':True,'online':True}
            if method=='GET':return {**request,'state':mode[0]}
            return {}
        with patch.object(hook,'normalize',return_value=request),patch.object(hook,'exchange',side_effect=exchange),patch.object(hook.time,'monotonic',side_effect=lambda:now[0]),patch.object(hook.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
            self.assertIsNone(hook.run({'hook_event_name':'PermissionRequest'},config,timeout=590))
            self.assertEqual(now[0],60)
            self.assertIn(('DELETE','/v1/requests/first',0.5),calls)
            self.assertNotIn('safetyPause',config)
            request['id']='second';mode[0]='allow'
            result=hook.run({'hook_event_name':'PermissionRequest'},config)
            self.assertEqual(result['hookSpecificOutput']['decision']['behavior'],'allow')
            self.assertIn(('POST','/v1/requests',2),calls)

    def test_late_allow_is_ignored_and_network_uses_remaining_budget(self):
        now=[0.0];budgets=[];request={'id':'late','session_id':'s','kind':'approval'}
        def exchange(cfg,method,path,body=None,timeout=2):
            if path=='/v1/status':now[0]=59.5;return {'enabled':True,'online':True}
            if method=='GET':
                budgets.append(timeout);now[0]=60.01
                return {**request,'state':'allow'}
            return {}
        with patch.object(hook,'normalize',return_value=request),patch.object(hook,'exchange',side_effect=exchange),patch.object(hook.time,'monotonic',side_effect=lambda:now[0]):
            self.assertIsNone(hook.run({'hook_event_name':'PermissionRequest'},{'desktopApproval':False}))
        self.assertEqual(budgets,[0.5])

if __name__=='__main__':unittest.main()
