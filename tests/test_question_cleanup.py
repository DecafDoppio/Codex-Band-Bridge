import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('cleanup_hook',Path(__file__).resolve().parents[1]/'codex-hook/bridge_hook.py')
hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)

class CleanupTests(unittest.TestCase):
    def payload(self):
        return {'hook_event_name':'PreToolUse','tool_name':'request_user_input_async','session_id':'session-a','turn_id':'turn','tool_use_id':'call-question','tool_input':{'questions':[{'title':'第一问？'},{'title':'第二问？'}]}}
    def reply(self,index=0,session='session-a'):
        item={'questionItemId':json.dumps(['request_user_input_async','call-question',index]),'answer':'已确认'}
        return {'hook_event_name':'UserPromptSubmit','session_id':session,'prompt':'<send_user_message_question_reply>'+json.dumps([item])+'</send_user_message_question_reply>'}
    def test_each_question_has_its_own_stable_id_and_body(self):
        with patch.object(hook,'exchange',return_value={'enabled':True,'online':True}) as exchange:
            self.assertIsNone(hook.run(self.payload(),{}))
        posts=[item for call in exchange.call_args_list if call.args[2]=='/v1/questions' for item in call.args[3]['requests']]
        self.assertEqual(len(posts),2)
        for index,item in enumerate(posts):self.assertEqual(item['id'],hook.question_id('session-a','call-question',index))
        self.assertIn('第一问',posts[0]['content']);self.assertNotIn('第二问',posts[0]['content'])
    def test_async_acknowledgement_never_hides_unanswered_question(self):
        payload={**self.payload(),'hook_event_name':'PostToolUse','tool_response':{'accepted':True}}
        with patch.object(hook,'exchange') as exchange:hook.run(payload,{});exchange.assert_not_called()
    def test_answer_clears_only_the_answered_index(self):
        with patch.object(hook,'exchange',return_value={'ok':True}) as exchange:hook.run(self.reply(),{})
        exchange.assert_called_once_with({},'POST','/v1/requests/cancel-batch',{'ids':[hook.question_id('session-a','call-question',0)]})
    def test_sync_completion_clears_its_group_only(self):
        payload={**self.payload(),'hook_event_name':'PostToolUse','tool_name':'request_user_input','tool_response':{'answers':{'q1':'yes'}}}
        with patch.object(hook,'exchange',return_value={'ok':True}) as exchange:hook.run(payload,{})
        self.assertEqual(exchange.call_count,1)
        self.assertEqual(exchange.call_args.args[3]['ids'],[hook.question_id('session-a','call-question',i) for i in range(2)])
    def test_regular_text_and_malformed_reply_do_not_clear_requests(self):
        for prompt in ('随便一句新消息','<send_user_message_question_reply>bad json</send_user_message_question_reply>'):
            with patch.object(hook,'exchange') as exchange:hook.run({'hook_event_name':'UserPromptSubmit','session_id':'session-a','prompt':prompt},{});exchange.assert_not_called()
        self.assertEqual(hook.completion_ids(self.reply(index=True)),[])
    def test_session_scoping_and_duplicate_reply(self):
        a=hook.completion_ids(self.reply());b=hook.completion_ids(self.reply(session='session-b'))
        self.assertNotEqual(a,b);self.assertTrue(a[0].startswith('question-'))
        payload=self.reply();payload['prompt']*=2;self.assertEqual(hook.completion_ids(payload),a)
