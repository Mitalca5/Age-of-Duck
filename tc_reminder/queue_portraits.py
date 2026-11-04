"""Conservative portrait fallback for blue/cyan production-queue skins.

Only searched inside an already detected queue frame. A coloured background is
not itself production evidence: the foreground must match a villager portrait.
"""
from pathlib import Path
import numpy as np
from PIL import Image


class VillagerPortraits:
    def __init__(self, profile, root):
        self.templates = []
        pitch = profile['queue_pitch']
        queue_y = profile['regions']['queue'][1]
        for meta in profile['templates']:
            if meta['kind'] != 'villager' or 'crop' not in meta:
                continue
            with Image.open(root / meta['file']) as image:
                rgb = np.asarray(image.convert('RGB')).astype(np.float32)
            # Keep coloured portrait interiors; remove dark background, white
            # count/hotkey glyphs, and their anti-aliased boundaries.
            mask = (rgb.max(2) > 60) & (np.ptp(rgb, axis=2) > 20)
            interior = np.zeros_like(mask)
            interior[1:-1, 1:-1] = (mask[1:-1, 1:-1] & mask[:-2, 1:-1] &
                mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:])
            background = rgb.max(2) < 45
            if interior.sum() < 20 or background.sum() < 10:
                continue
            luminance = rgb @ np.array([.299, .587, .114], dtype=np.float32)
            values = luminance[interior]
            centered = values - values.mean()
            norm = float(np.linalg.norm(centered))
            if norm < 8 * np.sqrt(len(values)):
                continue
            x = round(meta['crop'][0] % pitch)
            y = meta['crop'][1] - queue_y
            self.templates.append((meta, interior, background, centered / norm, x, y))

    def match(self, tile, threshold=.94):
        """Return one high-confidence foreground match, or None.

        Search only +/-2 pixels around the calibrated portrait location. This
        prevents digits or nearby icons from becoming arbitrary search targets.
        """
        if tile.size == 0:
            return None
        rgb = tile.astype(np.float32)
        blue = (rgb[:, :, 2] > 65) & (rgb[:, :, 2] > rgb[:, :, 0] * 1.25) & (rgb[:, :, 2] > rgb[:, :, 1] * .65)
        if np.count_nonzero(blue) < 10:
            return None
        luminance = rgb @ np.array([.299, .587, .114], dtype=np.float32)
        best = None
        for meta, mask, background, reference, x, y in self.templates:
            h, w = mask.shape
            for top in range(max(0, y-2), min(tile.shape[0]-h, y+2)+1):
                for left in range(max(0, x-2), min(tile.shape[1]-w, x+2)+1):
                    # Require blue/cyan specifically where the reference had
                    # background, not merely on the villager's blue clothing.
                    if blue[top:top+h, left:left+w][background].mean() < .5:
                        continue
                    values = luminance[top:top+h, left:left+w][mask]
                    centered = values - values.mean()
                    norm = float(np.linalg.norm(centered))
                    if norm < 8 * np.sqrt(len(values)):
                        continue
                    score = float(np.dot(centered / norm, reference))
                    if score >= threshold and (best is None or score > best['score']):
                        best = {'kind': 'villager', 'box': [left, top, left+w, top+h],
                                'score': score, 'name': Path(meta['file']).stem+'-portrait'}
        return best
