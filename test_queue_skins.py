"""Synthetic skin variations of public screenshots, not live-mod validation."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageDraw
from tc_reminder.queue_portraits import VillagerPortraits

ROOT = Path(__file__).parent
TC = ROOT / 'tc_reminder'


def recolour(tile, colour=(20,100,180)):
    rgb = np.asarray(tile.convert('RGB')).copy()
    background = (rgb.max(2)<55) & (np.ptp(rgb.astype(int),axis=2)<35)
    rgb[background] = colour
    return Image.fromarray(rgb)


def villagers():
    with Image.open(TC/'samples/selected-three.png') as source:
        frame = source.convert('RGB')
    return [frame.crop((round(i*37.5),58,round(i*37.5)+38,95)) for i in range(3)]


def queue_frame(tiles, start=0):
    frame = Image.new('RGB',(2560,1440))
    for i,tile in enumerate(tiles):
        frame.paste(tile,(round((start+i)*37.5),58))
    return frame


class PortraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads((TC/'calibration.json').read_text())
        cls.reader=VillagerPortraits(cls.profile,TC)

    def test_blue_and_cyan_backgrounds_preserve_male_and_female_portraits(self):
        for i,tile in enumerate(villagers()):
            for colour in ((20,100,180),(20,145,160),(40,80,220)):
                for scale in (1,1.5,2):
                    modified=recolour(tile,colour)
                    modified=modified.resize((round(38*scale),round(37*scale)),Image.Resampling.BICUBIC).resize((38,37),Image.Resampling.BICUBIC)
                    with self.subTest(portrait=i,colour=colour,scale=scale):
                        self.assertIsNotNone(self.reader.match(np.asarray(modified)))

    def test_large_count_badge_on_left_does_not_hide_portrait(self):
        for tile in villagers():
            modified=recolour(tile);draw=ImageDraw.Draw(modified)
            draw.rectangle((1,1,13,17),fill=(20,130,160));draw.text((2,1),'4',fill='white')
            self.assertIsNotNone(self.reader.match(np.asarray(modified)))

    def test_green_progress_tint_preserves_blue_skin_portraits(self):
        for tile in villagers():
            rgb=np.asarray(recolour(tile)).astype(float)
            tinted=(rgb*np.array([.6,1,.6])).astype('uint8')
            self.assertIsNotNone(self.reader.match(tinted))

    def test_plain_blue_and_noisy_blue_tiles_are_not_villagers(self):
        rng=np.random.default_rng(42)
        for i in range(30):
            tile=np.full((37,38,3),(20,100,180),dtype=np.uint8)
            if i:tile=np.clip(tile.astype(int)+rng.integers(-45,46,tile.shape),0,255).astype(np.uint8)
            self.assertIsNone(self.reader.match(tile),i)

    def test_research_and_military_templates_are_not_villagers(self):
        for meta in self.profile['templates']:
            if meta['kind'] not in ('research','research_waiting','non_tc'):continue
            with Image.open(TC/meta['file']) as opened:art=opened.convert('RGB')
            # Put unrelated art at the same position as the portrait, on a blue tile.
            for x in (4,16,20):
                tile=Image.new('RGB',(38,37),(20,100,180));tile.paste(recolour(art),(x,3))
                with self.subTest(template=meta['file'],x=x):
                    self.assertIsNone(self.reader.match(np.asarray(tile)))

    def test_tiny_input_is_unreadable(self):
        self.assertIsNone(self.reader.match(np.zeros((0,0,3),dtype=np.uint8)))
        self.assertIsNone(self.reader.match(np.full((3,3,3),(20,100,180),dtype=np.uint8)))


class QueueSkinIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tc_reminder.vision import Detector
        cls.detector=Detector()

    def test_blue_queue_recovers_villagers_missed_by_old_detector(self):
        from queue_reference import ReferenceDetector
        frame=queue_frame([recolour(tile) for tile in villagers()])
        before=ReferenceDetector().analyze_queue(frame)
        after=self.detector.analyze_queue(frame)
        self.assertLess(before['busy'],3)
        self.assertEqual(after['busy'],3)
        self.assertEqual(after['research'],0)
        self.assertEqual(after['busy_upper_bound'],3)

    def test_relocated_scaled_queue_works_after_user_box_remapping(self):
        from hud_regions import HudRegions,REGIONS
        tiles=[recolour(t) for t in villagers()]
        strip=queue_frame(tiles).crop((0,58,114,95)).resize((228,74),Image.Resampling.BICUBIC)
        raw=Image.new('RGB',(2560,1440));raw.paste(strip,(300,200))
        regions=HudRegions()
        regions.boxes={k:tuple(v/(2560 if i%2==0 else 1440) for i,v in enumerate(spec['default'])) for k,spec in REGIONS.items()}
        regions.boxes['queue']=(300/2560,200/1440,528/2560,274/1440)
        self.assertEqual(self.detector.analyze_queue(regions.build_canvas(raw))['busy'],3)

    def test_green_progress_on_blue_villagers_is_not_research(self):
        tiles=[Image.fromarray((np.asarray(recolour(t))*np.array([.6,1,.6])).astype('uint8')) for t in villagers()]
        result=self.detector.analyze_queue(queue_frame(tiles))
        self.assertEqual(result['busy'],3)
        self.assertEqual(result['research'],0)

    def test_isolated_portrait_after_gap_is_not_queue_evidence(self):
        frame=queue_frame([recolour(villagers()[0])],start=4)
        result=self.detector.analyze_queue(frame)
        self.assertFalse(any(h['name'].endswith('-portrait') for h in result['hits']))

    def test_recognized_portrait_at_queue_boundary_sets_overflow(self):
        frame=queue_frame([recolour(villagers()[0])]*22)
        result=self.detector.analyze_queue(frame)
        self.assertEqual(result['busy'],22)
        self.assertTrue(result['queue_overflow'])

    def test_unsupported_frames_are_reported_by_calibration(self):
        from hud_regions import describe,REGIONS
        detector=SimpleNamespace(population_reader=SimpleNamespace(read=lambda x:None),
            analyze_queue=lambda x:dict(busy=0,research=0,waiting=0,research_waiting=0,housed=0,hits=[],unknown=[[0,58,38,95]],unclassified=1))
        boxes={k:tuple(v/(2560 if i%2==0 else 1440) for i,v in enumerate(spec['default'])) for k,spec in REGIONS.items()}
        result=describe(Image.new('RGB',(2560,1440)),boxes,detector,SimpleNamespace(read=lambda x:None))
        self.assertIn('1 unrecognized',result['queue'])


if __name__=='__main__':unittest.main()
