"""Local icon teaching and honest unknown-queue state; no live-mod claims."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageOps
from tc_reminder.queue_samples import VillagerSamples
from test_queue_skins import villagers,recolour,queue_frame

ROOT=Path(__file__).parent


def custom_tile():
    # Deliberately different art, derived from a public fixture. Not the user's screenshot.
    return ImageOps.mirror(recolour(villagers()[1],(90,120,145))).crop((0,0,37,37))


class SampleTests(unittest.TestCase):
    def test_sample_roundtrip_and_count_badge_change(self):
        tile=np.asarray(custom_tile()).copy();samples=VillagerSamples();samples.add(tile)
        restored=VillagerSamples(samples.encoded());tile[:16,:12]=(220,220,220)
        self.assertIsNotNone(restored.match(tile))
        self.assertEqual(len(restored.entries),1)

    def test_blank_malformed_and_oversized_samples_are_rejected(self):
        self.assertEqual(len(VillagerSamples(['bad','x'*6000,None]).entries),0)
        self.assertEqual(len(VillagerSamples({'wrong':'root'}).entries),0)
        with self.assertRaises(ValueError):VillagerSamples().add(np.zeros((37,37,3),dtype=np.uint8))
        with self.assertRaises(ValueError):VillagerSamples().add(np.zeros((1,1,3),dtype=np.uint8))

    def test_samples_are_bounded_and_duplicate_learning_is_free(self):
        samples=VillagerSamples();tile=np.asarray(custom_tile()).copy()
        samples.add(tile);samples.add(tile)
        self.assertEqual(len(samples.entries),1)
        for n in range(20):
            modified=tile.copy();modified[0,0,0]=n;samples.add(modified)
        self.assertEqual(len(samples.entries),samples.LIMIT)

    def test_draft_and_source_are_independent(self):
        samples=VillagerSamples();draft=samples.copy();draft.add(np.asarray(custom_tile()))
        self.assertEqual(len(samples.entries),0)
        self.assertEqual(len(draft.entries),1)

    def test_learned_portrait_rejects_unrelated_icons_and_noise(self):
        samples=VillagerSamples();samples.add(np.asarray(custom_tile()))
        profile=json.loads((ROOT/'tc_reminder/calibration.json').read_text())
        for meta in profile['templates']:
            if meta['kind'] not in ('research','research_waiting','non_tc'):continue
            with Image.open(ROOT/'tc_reminder'/meta['file']) as opened:art=opened.convert('RGB')
            tile=Image.new('RGB',(37,37),(90,120,145));tile.paste(art,(14,2))
            self.assertIsNone(samples.match(np.asarray(tile)),meta['file'])
        rng=np.random.default_rng(4)
        for _ in range(20):self.assertIsNone(samples.match(rng.integers(0,256,(37,37,3),dtype=np.uint8)))


class LearningIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def calibrator(self,path=None):
        from hud_regions import HudRegions
        from hud_calibration import HudCalibrator
        from tc_reminder.vision import Detector
        from villager_reader import VillagerReader
        c=HudCalibrator((0,'test',(0,0,2560,1440)),HudRegions(path),Detector(),VillagerReader(),frame=queue_frame([custom_tile()]))
        self.addCleanup(c.close);c.select('queue')
        return c

    def test_learn_preview_then_save_is_used_by_live_detector(self):
        from hud_regions import HudRegions
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hud.json';c=self.calibrator(path)
            c.test_read();self.assertIn('1 unrecognized',c.readouts['queue'])
            c.learn_button.click();self.assertIn('1 villager',c.readouts['queue'])
            self.assertEqual(len(c.regions.villager_samples.entries),0)
            self.assertFalse(path.exists())
            c.save();restored=HudRegions(path)
            self.assertEqual(len(restored.villager_samples.entries),1)
            c.detector.regions=restored
            result=c.detector.analyze_queue(restored.build_canvas(c.frame))
            self.assertEqual(result['busy'],1);self.assertEqual(result['unclassified'],0)

    def test_cancel_does_not_save_a_learned_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hud.json';c=self.calibrator(path)
            c.learn_first_villager();c.close()
            self.assertFalse(path.exists());self.assertEqual(len(c.regions.villager_samples.entries),0)

    def test_failed_save_preserves_previous_calibration(self):
        c=self.calibrator();before=dict(c.regions.boxes);c.learn_first_villager()
        with patch.object(c.regions,'save',side_effect=OSError('Disk full')):c.save()
        self.assertEqual(c.regions.boxes,before)
        self.assertEqual(len(c.regions.villager_samples.entries),0)
        self.assertIn('Could not save',c.learn_status.text())

    def test_empty_queue_cannot_be_taught_and_forget_is_staged(self):
        c=self.calibrator();c.learn_first_villager()
        self.assertEqual(len(c.learned.entries),1)
        c.forget_villagers();self.assertEqual(len(c.learned.entries),0)
        c.frame=Image.new('RGB',(2560,1440));c.learn_first_villager()
        self.assertEqual(len(c.learned.entries),0)
        self.assertIn('No queue tile',c.learn_status.text())

    def test_known_research_cannot_be_taught_as_villager(self):
        c=self.calibrator()
        result={'hits':[{'kind':'research','box':[4,61,31,77]}],'unknown':[]}
        with patch.object(c.detector,'analyze_queue',return_value=result):c.learn_first_villager()
        self.assertEqual(len(c.learned.entries),0)

    def test_unknown_icon_is_not_confident_idle_evidence(self):
        from tc_reminder.vision import Detector
        from tc_reminder.core import Observation,Reminder
        with Image.open(ROOT/'tc_reminder/samples/selected-three.png') as opened:frame=opened.convert('RGB')
        frame.paste((0,0,0),(0,58,825,95));frame.paste(custom_tile(),(0,58))
        result=Detector().analyze(frame,now=1)
        self.assertTrue(result['gameplay']);self.assertEqual(result['unclassified'],1)
        self.assertFalse(result['confident'])
        reminder=Reminder()
        obs=Observation(busy=result['busy_upper_bound'],foreground=True,gameplay=True,advancing=True,confident=result['confident'])
        for t in (0,5,10):
            text,cue,_=reminder.step(obs,t,validated=True,manual_total=3)
            self.assertEqual(text,'');self.assertFalse(cue)


if __name__=='__main__':unittest.main()
