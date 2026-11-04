"""Functional/equivalence checks for the performance pass; no timing assertions."""
import json
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from PyQt5.QtWidgets import QApplication,QMenu
from build_order_core import Order,Step,Progress
from build_panel import BuildPanel
from companion_controls import CompanionControls
from recs_provider import RecsWorker,PEAK_CACHE_LIMIT,PEAK_TASK_LIMIT
from tc_reminder import native
from tc_reminder.vision import Detector
from queue_reference import ReferenceDetector

APP=QApplication.instance() or QApplication([])
ROOT=Path(__file__).parent

class QueueEquivalenceTests(unittest.TestCase):
    def test_public_screenshots_and_blank_queue_match_reference(self):
        before=ReferenceDetector();after=Detector()
        paths=list((ROOT/'tc_reminder/samples').glob('*.png'))
        paths+=list((ROOT/'fixtures').glob('*queue*.png'))
        self.assertTrue(paths)
        images=[Image.new('RGB',(2560,1440)),Image.new('RGB',(3440,1440))]
        for path in paths:
            with Image.open(path) as opened:
                image=opened.convert('RGB')
            # Actual shipped full frames and queue crops, retaining original geometry.
            images.append(image)
        for image in images:
            with self.subTest(size=image.size):
                self.assertEqual(before.analyze_queue(image),after.analyze_queue(image))

    def test_normalizing_wide_frame_twice_does_not_copy_it_again(self):
        detector=Detector();raw=Image.new('RGB',(3440,1440))
        with patch.object(raw,'resize',wraps=raw.resize) as resize:
            self.assertIs(detector.normalize_frame(raw),raw)
            resize.assert_not_called()

    def test_queue_rgb_copy_is_bounded_to_the_readout(self):
        image=Image.new('RGB',(2560,1440));detector=Detector()
        import tc_reminder.vision as vision
        original=vision.np.asarray;shapes=[]
        def record(value,*args,**kwargs):
            out=original(value,*args,**kwargs);shapes.append(out.shape);return out
        with patch.object(vision.np,'asarray',side_effect=record):detector.analyze_queue(image)
        self.assertNotIn((1440,2560,3),shapes)
        self.assertTrue(all(shape[0]<=99 for shape in shapes))

class ProviderResourceTests(unittest.TestCase):
    def worker(self):
        w=RecsWorker();w.profile_id='1001';self.addCleanup(w.stop)
        return w

    def data(self):return json.loads((ROOT/'fixtures/recs-live-synthetic.json').read_text())['data']

    def test_disconnect_does_not_wait_for_close_handshake(self):
        w=self.worker();w.socket=Mock();w.set_profile('9001')
        w.socket.shutdown.assert_called_once();w.socket.close.assert_not_called()

    def test_old_match_queued_peaks_are_cancelled(self):
        w=self.worker();old=Future();w.peak_tasks[('9000',3)]=old
        w.current_data=self.data()
        with patch.object(w.peak_pool,'submit',return_value=Future()):w.enrich_peaks('1001',0)
        self.assertTrue(old.cancelled());self.assertNotIn(('9000',3),w.peak_tasks)

    def test_clear_cancels_pending_but_retains_running_task(self):
        w=self.worker();pending=Future();running=Future();running.set_running_or_notify_cancel()
        w.peak_tasks={('2',3):pending,('3',3):running};w.clear()
        self.assertTrue(pending.cancelled());self.assertEqual(list(w.peak_tasks),[('3',3)])

    def test_cache_expires_and_stays_bounded(self):
        w=self.worker();now=time.monotonic()
        w.peak_cache={('old',3):(now-600,(None,None))}
        for i in range(PEAK_CACHE_LIMIT+20):w.peak_cache[(str(i),3)]=(now,(1000,'1v1'))
        w.enrich_peaks('1001',0)
        self.assertNotIn(('old',3),w.peak_cache);self.assertLessEqual(len(w.peak_cache),PEAK_CACHE_LIMIT)

    def test_provider_cannot_enqueue_unbounded_work(self):
        w=self.worker();data=self.data();base=data['live']['players'][1]
        data['live']['players']=[dict(base,id=i) for i in range(2000,2100)]
        w.current_data=data
        with patch.object(w.peak_pool,'submit',side_effect=lambda *args:Future()):w.enrich_peaks('1001',0)
        self.assertLessEqual(len(w.peak_tasks),PEAK_TASK_LIMIT)

    def test_stopped_worker_rejects_late_response(self):
        w=self.worker();w.stop();w.accept(self.data(),'1001',0)
        self.assertFalse(w.live);self.assertIsNone(w.current_data)

class UIAndCaptureTests(unittest.TestCase):
    def test_companion_focus_during_capture_discards_frame(self):
        game=(1,'123',(0,0,2560,1440))
        with patch.object(native,'foreground_game',return_value=game),patch.object(native,'companion_focused',side_effect=[False,True]),patch.object(native.ImageGrab,'grab',return_value=object()):
            self.assertIsNone(native.capture(game))

    def test_unchanged_guide_does_not_repeat_layout_work(self):
        progress=Progress(Order('Test','',(Step('3',3,'First'),Step('4',4,'Next'))))
        panel=SimpleNamespace(previous=[Mock() for _ in range(3)],upcoming=[Mock() for _ in range(3)],instruction=Mock(),layout=Mock(),adjustSize=Mock())
        for _ in range(100):BuildPanel.show_progress(panel,progress,True)
        self.assertEqual(panel.adjustSize.call_count,1)
        progress.observe(3,True);progress.observe(3,True);progress.begin()
        BuildPanel.show_progress(panel,progress,True)
        self.assertEqual(panel.adjustSize.call_count,2)
        panel._progress_key=None;BuildPanel.show_progress(panel,progress,True)
        self.assertEqual(panel.adjustSize.call_count,3)

    def test_hidden_panels_do_not_query_cursor_or_window_styles(self):
        from tc_reminder.panel import TCPanel
        hidden=SimpleNamespace(isVisible=lambda:False)
        with patch('build_panel.QCursor.pos') as cursor,patch.object(native.u,'GetWindowLongPtrW') as flags:
            BuildPanel.hit_test(hidden);TCPanel.update_input(hidden)
        cursor.assert_not_called();flags.assert_not_called()

    def test_hidden_controls_do_not_poll_focus(self):
        controls=SimpleNamespace(main=Mock(),volume_row=Mock(),refresh=Mock())
        controls.main.isVisible.return_value=False;controls.volume_row.isVisible.return_value=False
        for _ in range(20):CompanionControls.refresh_if_visible(controls)
        controls.refresh.assert_not_called()
        controls.volume_row.isVisible.return_value=True;CompanionControls.refresh_if_visible(controls)
        controls.refresh.assert_called_once()

    def test_quit_flushes_pending_volume_save(self):
        controls=SimpleNamespace(save_timer=Mock(),save_volume=Mock())
        controls.save_timer.isActive.return_value=True;CompanionControls.flush_volume(controls)
        controls.save_timer.stop.assert_called_once();controls.save_volume.assert_called_once()

    def test_failed_preferences_write_keeps_in_memory_choice(self):
        from build_orders import BuildOrders
        b=SimpleNamespace(prefs={},enabled=True,muted=True,pref_file=Mock())
        b.pref_file.write_text.side_effect=OSError('Disk full')
        with self.assertLogs(level='ERROR'):BuildOrders.save(b)
        self.assertEqual(b.prefs,{'enabled':True,'muted':True})

    def test_unchanged_diagnostics_are_not_rewritten(self):
        from tc_reminder.integration import TCController
        with tempfile.TemporaryDirectory() as tmp:
            menu=QMenu()
            with patch.object(native,'single_instance',return_value=True):c=TCController(APP,menu,Path(tmp)/'prefs.json')
            self.addCleanup(c.close);c.timer.stop()
            self.assertEqual(c.diagnostics.parent,Path(tmp))
            c.diagnostics=Mock()
            with patch.object(native,'foreground_game',return_value=None):
                for now in (10,12,14):
                    with patch('tc_reminder.integration.time.monotonic',return_value=now):c._tick()
            self.assertEqual(c.diagnostics.write_text.call_count,1)

if __name__=='__main__':unittest.main()
