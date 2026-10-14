import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('question_hook',Path(__file__).resolve().parents[1]/'codex-hook/bridge_hook.py')
hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)

class QuestionFormatTests(unittest.TestCase):
    def payload(self,questions):
        return {'hook_event_name':'PreToolUse','tool_name':'request_user_input_async','session_id':'private-session','cwd':'C:/private/project','tool_input':{'questions':questions}}
    def test_async_question_and_options_are_plain_text_without_metadata_or_json(self):
        result=hook.normalize(self.payload([{'title':'是否保留现有设置？','options':['保留','恢复默认']}]))
        self.assertEqual(result['content'],'是否保留现有设置？')
        for irrelevant in ('private-session','C:/private/project','request_user_input','"questions"'):
            self.assertNotIn(irrelevant,result['content'])
    def test_structured_questions_preserve_question_and_option_descriptions(self):
        payload=self.payload([{'id':'q1','header':'短标题','question':'完整问题一？','options':[{'label':'方案 A','description':'保留现有设置'}]}, {'title':'完整问题二？'}])
        payload['tool_name']='request_user_input'
        text=hook.normalize(payload)['content']
        self.assertIn('问题 1\n完整问题一？',text);self.assertNotIn('方案 A',text);self.assertNotIn('保留现有设置',text);self.assertIn('问题 2\n完整问题二？',text)
        self.assertNotIn('短标题',text)
    def test_free_text_question_and_long_question_are_complete(self):
        text='完整问题文字'*200
        result=hook.normalize(self.payload([{'title':text}]))
        self.assertEqual(result['content'],text)
    def test_missing_question_does_not_send_unrelated_raw_data(self):
        for questions in ([],[{'header':'只是标题'}]):
            self.assertIsNone(hook.normalize(self.payload(questions)))
