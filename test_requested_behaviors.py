"""Requested tray workflow and match-mode ELO regressions; no live network/game."""
import copy
import ctypes
from ctypes import wintypes
from concurrent.futures import Future
import json
import time
import unittest
from unittest.mock import Mock,patch
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
import test_overlay_layout as layout_tests
from test_overlay_layout import PLAYERS, app
from recs_provider import RecsWorker, normalize_profile, peak_for_mode, fetch_peak
from pathlib import Path

ROOT=Path(__file__).parent

class TrayWorkflowTests(unittest.TestCase):
    def overlay(self):
        return layout_tests.OverlayLayoutTests.make_overlay(self)

    def test_click_allows_activation_for_alt_f4(self):
        overlay=self.overlay()
        self.assertFalse(overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        message=wintypes.MSG();message.message=0x0021
        self.assertEqual(overlay.nativeEvent('windows_generic_MSG',ctypes.addressof(message)),(True,1))

    def test_close_hides_without_stopping_services(self):
        overlay=self.overlay()
        event=QCloseEvent()
        overlay.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(overlay.isVisible())
        self.assertTrue(overlay.worker.running)
        self.assertTrue(overlay.process_checker.running)
        self.assertTrue(overlay.dismissed_to_tray)

    def test_explicit_tray_quit_allows_window_close(self):
        overlay=self.overlay();application=Mock()
        overlay.quit_application(application)
        application.quit.assert_called_once()
        event=QCloseEvent();overlay.closeEvent(event)
        self.assertTrue(event.isAccepted())

    def test_windows_close_command_uses_hide_to_tray(self):
        overlay=self.overlay()
        send=ctypes.windll.user32.SendMessageW
        send.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        send.restype=ctypes.c_ssize_t
        # Alt+F4 ultimately requests SC_CLOSE on the active window.
        send(int(overlay.winId()),0x0112,0xF060,0)
        app.processEvents()
        self.assertFalse(overlay.isVisible())
        self.assertTrue(overlay.worker.running)
        overlay.restore_from_tray()
        self.assertTrue(overlay.isVisible())

    def test_updates_reconnect_and_game_restart_do_not_reopen_dismissed_overlay(self):
        overlay=self.overlay();overlay._aoe2_running=True;overlay.close()
        overlay.update_overlay({},PLAYERS,'RM TG','Arabia')
        overlay.show_waiting()
        overlay.on_aoe2_running_changed(False)
        overlay.on_aoe2_running_changed(True)
        self.assertFalse(overlay.isVisible())
        overlay.restore_from_tray()
        self.assertTrue(overlay.isVisible())
        self.assertFalse(overlay.dismissed_to_tray)


class MatchModePeakTests(unittest.TestCase):
    def data(self):
        return json.loads((ROOT/'fixtures/recs-live-synthetic.json').read_text())['data']

    def worker(self):
        w=RecsWorker();w.profile_id='1001';self.addCleanup(w.stop)
        return w

    def test_each_supported_mode_keeps_its_own_peak_and_live_rating(self):
        for name,ident,peak in [('RM 1v1',3,1600),('RM TG',4,1500),('EW 1v1',13,1450),('EW TG',14,1400)]:
            data=self.data();data['live']['leaderboard']=name
            data['live']['players'][0]['rating']=1234
            result=normalize_profile(data,'1001')
            self.assertEqual(result[0]['leaderboardId'],ident)
            self.assertEqual((result[1][0]['rating'],result[1][0]['peak']),(1234,peak))

    def test_missing_unknown_and_invalid_ladder_do_not_borrow_another_peak(self):
        data=self.data();data['ladders']=[{'id':3,'highest':2400}]
        self.assertEqual(peak_for_mode(data,4),(None,None))
        self.assertEqual(peak_for_mode(data,None),(None,None))
        for bad in [None, True, '2200', float('nan'), float('inf'), -1]:
            self.assertEqual(peak_for_mode({'ladders':[{'id':4,'highest':bad}]},4),(None,None))
        data['live']['leaderboard']='Unranked'
        self.assertIsNone(normalize_profile(data,'1001')[1][0]['peak'])

    def test_linked_account_uses_the_match_mode(self):
        data=self.data();data['accounts'].append({'id':1003})
        data['live']['players'][0]['id']=1003;data['live']['leaderboard']='RM TG'
        self.assertEqual(normalize_profile(data,'1001')[1][0]['peak'],1500)

    def test_opponent_cache_is_scoped_to_mode(self):
        w=self.worker();seen=[];w.data_updated.connect(lambda *args:seen.append(args))
        w.peak_cache[('1002',3)]=(time.monotonic(),(2200,'1v1'))
        w.peak_cache[('1002',4)]=(time.monotonic(),(1700,'Teams'))
        data=self.data();w.accept(data,'1001',0)
        self.assertEqual(seen[-1][1][1]['peak'],2200)
        data=copy.deepcopy(data);data['live']['leaderboard']='RM TG';w.accept(data,'1001',0)
        self.assertEqual(seen[-1][1][1]['peak'],1700)

    def test_late_result_from_previous_mode_is_not_used_in_new_mode(self):
        w=self.worker();seen=[];w.data_updated.connect(lambda *args:seen.append(args))
        future=Future();future.set_result((2500,'1v1'));w.peak_tasks[('1002',3)]=future
        data=self.data();data['live']['leaderboard']='RM TG'
        w.accept(data,'1001',0)
        with patch.object(w.peak_pool,'submit',return_value=Future()) as submit:
            w.enrich_peaks('1001',0)
        self.assertIsNone(seen[-1][1][1]['peak'])
        submit.assert_called_once_with(fetch_peak,'1002',4)

    def test_network_response_selects_requested_ladder(self):
        data=self.data();data['player']['id']=1002
        socket=Mock();socket.recv.return_value=json.dumps({'cls':13,'data':data})
        with patch('recs_provider.websocket.create_connection',return_value=socket):
            self.assertEqual(fetch_peak('1002',4),(1500,'Teams'))
        socket.close.assert_called_once()

if __name__=='__main__':
    unittest.main()
