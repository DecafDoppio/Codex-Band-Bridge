"""Isolated UI tests. No real bridge, device, hook health or command execution."""
import importlib
import gc
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'codex-hook'))
from desktop_queue import DesktopQueue, cleanup_process


class QueueTests(unittest.TestCase):
    def test_hook_cleanup_removes_only_its_exited_companions_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            first=DesktopQueue(directory);second=DesktopQueue(directory)
            try:
                first.entry.write_text(json.dumps({'pid':123456789,'summary':{'reason':'A'}}),encoding='utf-8')
                cleanup_process(directory,123456789)
                self.assertFalse(first.entry.exists());self.assertTrue(second.entry.exists())
            finally:first.close();second.close()
    def test_dead_process_is_removed_without_waiting_for_thirty_second_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            first=DesktopQueue(directory);second=DesktopQueue(directory,alive=lambda pid:pid==os.getpid())
            try:
                first.entry.write_text(json.dumps({'pid':999999999,'summary':{}}),encoding='utf-8')
                self.assertTrue(second.acquire());self.assertFalse(first.entry.exists())
            finally:first.close();second.close()

    def test_selecting_a_request_transfers_display_without_resolving_or_deleting_others(self):
        with tempfile.TemporaryDirectory() as directory:
            first=DesktopQueue(directory,summary={'reason':'A'});second=DesktopQueue(directory,summary={'reason':'B'})
            try:
                self.assertTrue(first.acquire());self.assertTrue(first.select(second.entry))
                self.assertFalse(first.acquire());self.assertTrue(second.acquire())
                self.assertEqual([s['reason'] for _,s in first.summaries()],['A','B'])
                second.close();self.assertTrue(first.acquire())
            finally:first.close();second.close()

    def test_fifo_and_hidden_card_releases_only_its_own_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            first=DesktopQueue(directory);second=DesktopQueue(directory);third=DesktopQueue(directory)
            try:
                self.assertTrue(first.acquire());self.assertFalse(second.acquire());self.assertFalse(third.acquire())
                first.close();self.assertTrue(second.acquire());self.assertFalse(third.acquire())
                second.close();self.assertTrue(third.acquire())
                first.close() # Closing a hidden card twice cannot release the next card.
                self.assertTrue(third.acquire())
            finally:first.close();second.close();third.close()

    def test_abandoned_queue_entry_cannot_block_the_next_card(self):
        with tempfile.TemporaryDirectory() as directory:
            first=DesktopQueue(directory);second=DesktopQueue(directory)
            try:
                os.utime(first.entry,(time.time()-60,time.time()-60))
                self.assertTrue(second.acquire())
                self.assertFalse(first.entry.exists())
            finally:first.close();second.close()


@unittest.skipUnless(os.environ.get('CODEX_BAND_GUI_TEST')=='1','Opt-in isolated Tk widget tests')
class PromptTests(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('desktop_prompt');self.calls=[];self.state='pending'
        self.temp=tempfile.TemporaryDirectory()
        self.request={'id':'isolated-card','session_id':'isolated-session','reason':'隔离界面测试，不执行任何操作。','content':'隔离测试\n'*150}
        def exchange(config,method,path,body=None):
            self.calls.append((method,path,body))
            if method=='POST':self.state=body['decision']
            return {'id':self.request['id'],'session_id':self.request['session_id'],'state':self.state,'resolvedBy':'desktop'}
        self.mock=patch.object(self.module,'exchange',exchange);self.mock.start()
        self.root,self.controls=self.module.create_prompt({'endpoint':'http://127.0.0.1:1'},self.request,self.temp.name)
        self.spin(.3)
    def spin(self,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.root.update();time.sleep(.01)
    def tearDown(self):
        self.controls['window_queue'].close()
        try:self.root.destroy()
        except Exception:pass
        self.mock.stop();self.temp.cleanup()
        # Tk interpreters must be released by their creating thread. Otherwise
        # a later HTTP worker's cyclic GC can collect an already destroyed root.
        del self.controls,self.root
        gc.collect()

    def test_repeated_expand_collapse_preserves_controls_and_allows_denial(self):
        for _ in range(3):
            self.controls['details'].event_generate('<Button-1>');self.spin(.05)
            self.assertEqual(self.controls['details'].cget('text'),'收起操作')
            self.controls['details'].event_generate('<Button-1>');self.spin(.05)
            self.assertEqual(self.controls['details'].cget('text'),'查看操作')
        for key in ['allow','deny','details']:
            button=self.controls[key]
            self.assertGreater(button.winfo_height(),0)
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())

    def test_chinese_summary_does_not_orphan_the_version_prefix(self):
        text='【1.3.0 超时后续请求验证】允许仅读取本机时间吗？请确认这次重新出现手环和桌面卡片，再在手环批准，验证超时后仍走双端授权。'
        content=self.controls['content']
        content.configure(state='normal');content.delete('1.0','end');content.insert('1.0',text);content.configure(state='disabled')
        self.spin(.1)
        first_line=content.get('1.0','1.0 display lineend')
        self.assertGreater(len(first_line),len('【1.3.0 ')+2)
        self.assertEqual(content.get('1.0','end-1c'),text)
        self.controls['toggle_details']();self.spin(.05)
        self.assertEqual(content.cget('wrap'),'word')
        self.controls['toggle_details']();self.spin(.05)
        self.assertEqual(content.cget('wrap'),'char')
        self.controls['deny'].event_generate('<Button-1>');time.sleep(.03)
        self.assertTrue(any(method=='POST' and body['decision']=='deny' for method,_,body in self.calls))

    def test_expanded_approval_does_not_require_scrolling(self):
        self.controls['toggle_details']();self.spin(.1)
        self.controls['allow'].event_generate('<Button-1>')
        time.sleep(.03)
        self.assertTrue(any(method=='POST' and body['decision']=='allow' for method,_,body in self.calls))

    def test_close_hides_card_without_cancelling_or_pausing(self):
        self.controls['dismiss']();self.spin(.1)
        self.assertEqual(self.root.state(),'withdrawn')
        self.assertEqual(self.state,'pending')
        self.assertFalse(any(method!='GET' for method,_,_ in self.calls))
        other=DesktopQueue(self.temp.name)
        try:self.assertTrue(other.acquire())
        finally:other.close()

    def test_queue_list_can_select_another_pending_request_without_a_decision(self):
        second=DesktopQueue(self.temp.name,summary={'project':'项目B','time':'13:00','reason':'读取日期'})
        third=DesktopQueue(self.temp.name,summary={'project':'项目C','time':'13:01','reason':'读取星期'})
        try:
            self.spin(.2)
            listing=self.controls['pending_list']
            self.assertEqual(len(listing.items),3)
            self.assertIn('读取日期',listing.items[1][1]['reason']);self.assertIn('读取星期',listing.items[2][1]['reason'])
            for key in ('allow','deny'):
                button=self.controls[key]
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
            listing.event_generate('<Button-1>',x=20,y=listing.stride*2+10)
            self.assertEqual(self.root.state(),'withdrawn');self.assertTrue(third.acquire())
            self.assertTrue(self.controls['window_queue'].entry.exists())
            self.assertFalse(any(method=='POST' for method,_,_ in self.calls))
        finally:second.close();third.close()

    def test_header_drag_preserves_position_when_details_resize_and_keeps_topmost(self):
        self.controls['drag_start'](SimpleNamespace(x_root=100,y_root=100))
        self.controls['drag_move'](SimpleNamespace(x_root=40,y_root=40))
        self.controls['drag_end']();self.spin(.1)
        position=self.root._user_position
        self.controls['toggle_details']();self.spin(.1)
        self.assertEqual(self.root._user_position,position)
        self.assertTrue(self.root.attributes('-topmost'))
        self.assertTrue((self.controls['window_queue'].directory/'position.json').exists())

    def test_scaled_multi_request_layout_preserves_visible_actions(self):
        for scale in (1,1.5,2):
            with tempfile.TemporaryDirectory() as folder:
                root,controls=self.module.create_prompt({'endpoint':'http://127.0.0.1:1'},self.request,folder,test_scale=scale)
                others=[DesktopQueue(folder,summary={'project':'长项目名称测试','time':'14:00','reason':'查看完整请求原因'*8}) for _ in range(2)]
                try:
                    until=time.monotonic()+.25
                    while time.monotonic()<until:root.update();time.sleep(.01)
                    self.assertEqual(len(controls['pending_list'].items),3)
                    controls['toggle_details']()
                    until=time.monotonic()+.15
                    while time.monotonic()<until:root.update();time.sleep(.01)
                    for key in ('allow','deny'):
                        control=controls[key]
                        self.assertGreater(control.winfo_height(),0)
                        self.assertLessEqual(control.winfo_rooty()+control.winfo_height(),root.winfo_rooty()+root.winfo_height())
                finally:
                    controls['window_queue'].close();root.destroy()
                    for other in others:other.close()
                    del controls,root
                    gc.collect()

    def test_terminal_decision_releases_queue_before_tk_pump_or_hook_process_cleanup(self):
        second=DesktopQueue(self.temp.name)
        try:
            self.controls['decide']('deny')
            until=time.monotonic()+1
            while self.controls['window_queue'].entry.exists() and time.monotonic()<until:time.sleep(.01)
            self.assertFalse(self.controls['window_queue'].entry.exists())
            self.assertTrue(second.acquire())
        finally:second.close()
