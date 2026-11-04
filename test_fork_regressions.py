"""Regressions for the integrated fork; synthetic data, no game/network required."""
import copy
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PyQt5.QtWidgets import QApplication
from build_order_core import Order, Step, Progress
from build_orders import BuildOrders
from tc_reminder.voice import RepeatingVoice
from recs_provider import normalize_profile, profile_updates, highest_peak, RecsWorker
from editable_catalog import apply_catalog_edits
from preference_io import valid_position
from game_process import is_game_process

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).parent


class ProcessAndProviderTests(unittest.TestCase):
    def payload(self):
        return json.loads((ROOT/'fixtures/recs-live-synthetic.json').read_text())['data']

    def test_both_distributions_are_detected(self):
        for name in ('AoE2DE.exe', 'AoE2DE_s.exe'):
            self.assertTrue(is_game_process(name))
        for name in (None, '', 'notaoe2de.exe', 'explorer.exe'):
            self.assertFalse(is_game_process(name))

    def test_process_watcher_emits_for_both_names(self):
        from AgeofDuck import ProcessChecker
        for name in ('AoE2DE.exe', 'AoE2DE_s.exe'):
            watcher=ProcessChecker();seen=[]
            watcher.aoe2_running_changed.connect(seen.append)
            with patch('AgeofDuck.psutil.process_iter',return_value=[SimpleNamespace(info={'name':name})]), \
                 patch('AgeofDuck.time.sleep',side_effect=lambda _:watcher.stop()):
                watcher.run()
            self.assertEqual(seen,[True])

    def test_malformed_batches_and_ladders_do_not_disconnect(self):
        for value in (None, 4, 'bad', {}):
            self.assertEqual(list(profile_updates({'cls':3,'data':value})),[])
            self.assertEqual(highest_peak({'ladders':value}),(None,None))
        for value in (float('inf'), float('nan'), True, '2000'):
            self.assertEqual(highest_peak({'ladders':[{'id':3,'highest':value}]}),(None,None))
        self.assertEqual(highest_peak({'ladders':[{'id':[],'highest':2000}]}),(None,None))

    def test_malformed_optional_fields_keep_live_match(self):
        data=self.payload()
        data['ladders']=None;data['accounts']=42
        data['live']['players'].append(None)
        data['live']['players'][1].update(civilization=[],country={},rating=float('inf'),team=True)
        data['live'].update(leaderboard={},rms=[])
        match,players,mode,map_name=normalize_profile(data,'1001')
        self.assertEqual(len(players),2)
        self.assertEqual(players[1]['civ'],'')
        self.assertIsNone(players[1]['rating'])
        self.assertEqual(players[1]['team'],0)
        self.assertEqual(map_name,'Unknown map')

    def test_invalid_owner_or_players_is_not_live(self):
        for owner in ([],4,'wrong'):
            data=self.payload();data['player']=owner
            self.assertIsNone(normalize_profile(data,'1001'))
        for rows in (None,4,{}):
            data=self.payload();data['live']['players']=rows
            self.assertIsNone(normalize_profile(data,'1001'))

    def test_switching_profile_clears_old_match_immediately(self):
        worker=RecsWorker();self.addCleanup(worker.stop);worker.profile_id='1001'
        worker.accept(self.payload(),'1001',0);self.assertTrue(worker.live)
        worker.set_profile('9001')
        self.assertFalse(worker.live);self.assertIsNone(worker.current_data)
        worker.accept(self.payload(),'1001',0)
        self.assertFalse(worker.live)

    def test_stopping_game_clears_old_match(self):
        worker=RecsWorker();self.addCleanup(worker.stop);worker.profile_id='1001'
        worker.accept(self.payload(),'1001',0)
        worker.set_game_running_state(False)
        self.assertFalse(worker.live);self.assertIsNone(worker.current_data)

    def test_player_names_are_plain_text(self):
        from AgeofDuck import PlayerRow
        from PyQt5.QtCore import Qt
        row=PlayerRow();self.addCleanup(row.close)
        row.set_player({'name':'<b>Player</b>','civ':'Britons'})
        self.assertEqual(row.name_label.text(),'<b>Player</b>')
        self.assertEqual(row.name_label.textFormat(),Qt.PlainText)


class SpeechRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        b=BuildOrders.__new__(BuildOrders);self.b=b
        b.folder=Path(tmp.name);b.cache=b.folder;b.assets=ROOT;b.pref_file=b.folder/'prefs.json'
        b.order=Order('Test','',(Step('3',3,'First'),Step('3.1',3,'Next')))
        b.progress=Progress(b.order);b.progress.observe(3,True);b.progress.observe(3,True)
        b.panel=Mock();b.spoken=Mock();b.tc=SimpleNamespace(voice=Mock())
        b.voice=RepeatingVoice('',play=Mock())
        b.enabled=True;b.muted=False;b.view_visible=True;b.in_match=True;b.safe=True
        b.session='test';b.last_frame=10;b.focus_hold_until=0;b.count=3;b.deadline=None
        b.prefs={'selected':'test.json'};b.process=None;b.audio_busy=False;b.current_audio=None
        b.cue_text='';b.cue_until=0;b.voice_failed=False;b.voice_wait_since=None;b.status=''
        self.game=(1,'test',(0,0,2560,1440))
        self.addCleanup(b.pause_audio)
        self.addCleanup(b.stop_generation)

    def tick(self,now):
        self.b.last_frame=now
        with patch('build_orders.native.foreground_game',return_value=self.game), \
             patch('build_orders.native.companion_focused',return_value=False), \
             patch('build_orders.time.monotonic',return_value=now):
            self.b.tick()

    def clip(self,index=0):
        path=self.b.cache/f'{index}.wav'
        with wave.open(str(path),'wb') as f:
            f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*8000)
        return path

    def test_missing_voice_advances_visually_and_releases_priority(self):
        self.tick(10)
        self.assertEqual(self.b.deadline,13);self.assertTrue(self.b.voice_failed)
        with patch('build_orders.time.monotonic',return_value=10):self.assertFalse(self.b.speech_priority)
        self.tick(13.1)
        self.assertEqual(self.b.progress.current.id,'3.1')
        self.assertAlmostEqual(self.b.deadline,23.1)

    def test_corrupt_and_empty_clips_fall_back(self):
        for raw in (b'',b'not a wave'):
            self.b.voice_failed=False;self.b.deadline=None
            (self.b.cache/'0.wav').write_bytes(raw)
            self.tick(10)
            self.assertEqual(self.b.deadline,13)
            self.assertFalse(self.b.audio_busy)

    def test_playback_error_falls_back_without_acknowledging(self):
        self.clip();self.b.voice.play=Mock(side_effect=RuntimeError('No sound device'))
        self.tick(10)
        self.assertEqual(self.b.deadline,13);self.assertIsNone(self.b.voice.last_event)
        self.assertIsNone(self.b.voice.pending_event)

    def test_generation_wait_is_bounded_and_does_not_block_reminders(self):
        process=Mock();process.poll.return_value=None;self.b.process=process
        self.tick(10);self.assertIsNone(self.b.deadline)
        with patch('build_orders.time.monotonic',return_value=10):self.assertFalse(self.b.speech_priority)
        self.tick(20)
        self.assertEqual(self.b.deadline,23);process.kill.assert_called_once()

    def test_completed_clip_can_play_while_other_clips_generate(self):
        self.clip();process=Mock();process.poll.return_value=None;self.b.process=process
        self.tick(10)
        self.assertTrue(self.b.audio_busy)
        self.assertAlmostEqual(self.b.deadline,11.08)
        process.kill.assert_not_called()

    def test_pause_preserves_step_and_silences(self):
        self.clip();self.tick(10);self.b.safe=False;self.tick(10.2)
        self.assertEqual(self.b.progress.current.id,'3')
        self.assertIsNone(self.b.deadline);self.assertFalse(self.b.audio_busy)

    def test_missing_powershell_keeps_selected_order(self):
        path=self.b.folder/'order.json'
        path.write_text(json.dumps({'version':1,'name':'Test','steps':[{'step':'3','unit':'Custom','text':'Go'}]}))
        with patch('build_orders.subprocess.Popen',side_effect=FileNotFoundError('PowerShell')):
            self.b.load(path)
        self.assertEqual(self.b.order.name,'Test');self.assertTrue(self.b.voice_failed)

    def test_failed_reminder_playback_is_throttled(self):
        play=Mock(side_effect=RuntimeError('No audio'))
        voice=RepeatingVoice('missing.wav',play=play)
        self.assertFalse(voice.update(True,1,event='house'))
        self.assertFalse(voice.update(True,2,event='house'))
        self.assertEqual(play.call_count,1)
        self.assertFalse(voice.update(True,6,event='house'))
        self.assertEqual(play.call_count,2)

    def test_failed_volume_conversion_does_not_acknowledge(self):
        voice=RepeatingVoice('missing.wav',play=Mock())
        with patch.object(RepeatingVoice,'volume_percent',50):
            self.assertFalse(voice.update(True,1,event='house'))
        self.assertIsNone(voice.last_event);self.assertIsNone(voice.finishes)
        voice.play.assert_not_called()


class SettingsAndCatalogTests(unittest.TestCase):
    def test_invalid_positions_are_rejected(self):
        for value in ([1],['x',2],[None,3],[True,2],[float('nan'),0],[2**40,0],{}):
            self.assertFalse(valid_position(value),repr(value))
        self.assertTrue(valid_position([-1920,50]))

    def test_build_panel_recovers_invalid_position(self):
        from build_panel import BuildPanel
        owner=SimpleNamespace(prefs={'position':['invalid',None]},scale=1.0)
        # Exercise the real placement method with a QWidget, without constructing all controls.
        from PyQt5.QtWidgets import QWidget
        panel=QWidget();panel.drag=None;panel.owner=owner;self.addCleanup(panel.close)
        BuildPanel.place(panel)

    def test_tc_panel_recovers_invalid_position(self):
        from tc_reminder.panel import TCPanel
        panel=TCPanel();self.addCleanup(panel.close)
        panel.game=(1,'test',(0,0,2560,1440));panel.offset=[None];panel.show()
        with patch('tc_reminder.native.show_overlay') as show:
            panel.place()
        show.assert_called_once()

    def test_partial_catalog_edit_preserves_availability_and_metadata(self):
        catalog={'civs':{'Britons':{'civTeamBonus':'Current','unitsAvailable':{'Range':{'Archer':True}}}},'units':{}}
        seed={'Britons':{'civTeamBonus':'Old','unitsAvailable':{'Archery':{'Archer':True}}}}
        edited={'Britons':{'civTeamBonus':'Custom'}}
        out=apply_catalog_edits(catalog,seed,edited,{}, {})
        self.assertEqual(out['civs']['Britons']['unitsAvailable'],catalog['civs']['Britons']['unitsAvailable'])
        self.assertEqual(out['civs']['Britons']['civTeamBonus'],'Custom')

    def test_invalid_availability_does_not_crash(self):
        catalog={'civs':{'Britons':{'unitsAvailable':{'Range':{'Archer':True}}}},'units':{}}
        result=apply_catalog_edits(catalog,{'Britons':{}},{'Britons':{'unitsAvailable':None}}, {}, {})
        self.assertEqual(result,catalog)

    def test_json_object_loaders_recover_wrong_root_type(self):
        from ConfigDuck import read_json
        from tooltip import load_json
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json'
            for raw in ('[]','null','42'):
                path.write_text(raw)
                self.assertEqual(read_json(str(path),{}),{})
                self.assertEqual(load_json(str(path),{}),{})

    def test_hud_rejects_invalid_runtime_size(self):
        from hud_regions import HudRegions,ORDER
        r=HudRegions();r.boxes={k:(0,0,.1,.1) for k in ORDER};r.size=(2560,1440)
        for size in ((1,), (1920,0), (None,1080)):
            self.assertFalse(r.usable(size))


class CacheAndStartupTests(unittest.TestCase):
    def test_corrupt_cache_is_removed_for_retry(self):
        from speech_clip import prepare_cache
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'0.wav';path.write_bytes(b'broken')
            self.assertFalse(prepare_cache(Path(tmp),1))
            self.assertFalse(path.exists())

    def test_truncated_clip_is_not_treated_as_complete(self):
        from speech_clip import prepare_cache
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'0.wav'
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*8000)
            path.write_bytes(path.read_bytes()[:-100])
            self.assertFalse(prepare_cache(Path(tmp),1))
            self.assertFalse(path.exists())

    def test_complete_clip_is_preserved(self):
        from speech_clip import prepare_cache,clip_duration
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'0.wav'
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*8000)
            self.assertTrue(prepare_cache(Path(tmp),1))
            self.assertEqual(clip_duration(path),1)

    def test_invalid_tc_preference_values_recover_at_startup(self):
        from tc_reminder.integration import TCController
        from PyQt5.QtWidgets import QMenu
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tc.json'
            path.write_text(json.dumps({'enabled':[], 'mute':{},'manual_tcs':float('inf')}))
            menu=QMenu()
            with patch('tc_reminder.native.single_instance',return_value=True):
                controller=TCController(APP,menu,path)
            try:
                controller.timer.stop()
                self.assertTrue(controller.enabled.isChecked())
                self.assertFalse(controller.mute.isChecked())
                self.assertEqual(controller.manual_tcs,0)
            finally:controller.close()

    def test_installer_uses_application_version(self):
        import re
        from AgeofDuck import CURRENT_VERSION
        script=(ROOT/'installer/AgeOfDuckInstaller.iss').read_text()
        self.assertEqual(re.search(r'#define MyAppVersion "([^"]+)"',script)[1],CURRENT_VERSION)
        self.assertIn('OutputBaseFilename=AgeOfDuck-Setup-v{#MyAppVersion}',script)


class UpdateShutdownTests(unittest.TestCase):
    def test_background_discards_completed_download_after_close(self):
        from update_io import start_background
        ready=threading.Event();go=threading.Event();discard=Mock();success=Mock()
        def work():
            ready.set();go.wait(2);return 'download.exe'
        closed=[False]
        thread=start_background(work,success,Mock(),lambda:closed[0],discard)
        self.assertTrue(ready.wait(2));closed[0]=True;go.set();thread.join(2)
        discard.assert_called_once_with('download.exe');success.assert_not_called()

    def test_queued_download_does_not_launch_after_close(self):
        from update_ui import UpdateController
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'setup.exe';path.write_bytes(b'data')
            c=UpdateController(APP,Mock(),Mock(),lambda:None,'unused','2.0.1',str(Path(tmp)/'marker'))
            c.close()
            with patch('update_ui.launch_installer') as launch:c.on_downloaded(str(path))
            launch.assert_not_called();self.assertFalse(path.exists())
            c.deleteLater()

    def test_update_result_is_delivered_on_gui_thread(self):
        from PyQt5.QtCore import QThread
        from PyQt5.QtWidgets import QAction
        from update_ui import UpdateController
        import time
        entered=threading.Event();release=threading.Event();seen=[]
        def fetch(*args):
            entered.set();release.wait(2);return (None,None)
        action=QAction()
        c=UpdateController(APP,Mock(),action,lambda:None,'unused','2.0.1','unused')
        try:
            with patch('update_ui.fetch_update',side_effect=fetch), \
                 patch('update_ui.QMessageBox.information',side_effect=lambda *args:seen.append(QThread.currentThread()==APP.thread())):
                c.check()
                self.assertTrue(entered.wait(2))
                self.assertFalse(action.isEnabled())
                APP.processEvents()  # UI remains responsive while network work is blocked.
                release.set()
                deadline=time.monotonic()+3
                while not seen and time.monotonic()<deadline:
                    APP.processEvents();time.sleep(.01)
            self.assertEqual(seen,[True])
            self.assertTrue(action.isEnabled())
        finally:
            release.set();c.close();c.deleteLater()

    def test_fork_without_release_gets_specific_error(self):
        from update_io import fetch_update
        response=Mock(status_code=404)
        with self.assertRaisesRegex(ValueError,'No release'):
            fetch_update('unused','2.0.1',get=Mock(return_value=response))


if __name__=='__main__':
    unittest.main()


class CalibrationApprovalTests(unittest.TestCase):
    def test_newline_variants_preserve_approval_but_content_changes_do_not(self):
        import tc_reminder.validation_gate as gate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'template.png').write_bytes(b'binary-template')
            files={'calibration.json':'{\n "templates": [{"file":"template.png"}]\n}\n',
                   'clock-calibration.json':'{\n "samples": []\n}\n',
                   'population-glyphs.json':'{\n "glyphs": []\n}\n'}
            with patch.object(gate,'ROOT',root):
                for name,content in files.items():
                    (root/name).write_bytes(content.replace('\n','\r\n').encode())
                expected=gate.fingerprint()
                (root/'validation-approval.json').write_text(json.dumps({'approved':True,'fingerprint':expected}))
                for name,content in files.items():(root/name).write_bytes(content.encode())
                self.assertTrue(gate.approved())
                (root/'template.png').write_bytes(b'changed-template')
                self.assertFalse(gate.approved())
                (root/'template.png').write_bytes(b'binary-template')
                (root/'population-glyphs.json').write_bytes(b'{"glyphs":[1]}')
                self.assertFalse(gate.approved())
