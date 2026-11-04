"""Small, local-only villager references explicitly taught in HUD setup."""
import base64
import binascii
import numpy as np


class VillagerSamples:
    LIMIT = 8
    SIZE = 37

    def __init__(self, encoded=None):
        self.entries = ()
        if isinstance(encoded, list):
            for value in encoded[:self.LIMIT]:
                if not isinstance(value, str) or len(value) > 5500:
                    continue
                try:
                    data = base64.b64decode(value, validate=True)
                    if len(data) != self.SIZE*self.SIZE*3:
                        continue
                    self.add(np.frombuffer(data,dtype=np.uint8).reshape(self.SIZE,self.SIZE,3))
                except (ValueError, binascii.Error):
                    continue

    def copy(self):
        result = VillagerSamples()
        result.entries = self.entries
        return result

    def encoded(self):
        return [base64.b64encode(rgb.tobytes()).decode('ascii') for rgb,_,_ in self.entries]

    def add(self, tile):
        rgb = np.asarray(tile,dtype=np.uint8)
        if rgb.shape != (self.SIZE,self.SIZE,3):
            raise ValueError('The first queue icon must be a complete square.')
        rgb = rgb.copy()
        # The left count badge and the lower-right hotkey are not identity.
        patch = rgb[2:28,14:33].astype(np.float32)
        gray = patch @ np.array([.299,.587,.114],dtype=np.float32)
        gradient = np.zeros_like(gray)
        gradient[1:-1,1:-1] = (np.abs(gray[2:,1:-1]-gray[:-2,1:-1]) +
                               np.abs(gray[1:-1,2:]-gray[1:-1,:-2]))
        mask = (gradient>8) & (np.ptp(patch,axis=2)>20) & (patch.max(2)>45)
        values = gray[mask]
        if len(values)<60 or values.std()<12:
            raise ValueError('No detailed portrait found. Place a training villager first in the queue.')
        values = values-values.mean()
        reference = values/np.linalg.norm(values)
        if any(np.array_equal(rgb,entry[0]) for entry in self.entries):
            return
        self.entries = (*self.entries,(rgb,mask,reference))[-self.LIMIT:]

    def match(self, tile, threshold=.96):
        if not self.entries or tile.shape[0]<30 or tile.shape[1]<35:
            return None
        gray = tile.astype(np.float32) @ np.array([.299,.587,.114],dtype=np.float32)
        best = None
        for _,mask,reference in self.entries:
            for top in range(0,min(4,gray.shape[0]-26)+1):
                for left in range(12,min(16,gray.shape[1]-19)+1):
                    values = gray[top:top+26,left:left+19][mask]
                    if values.std()<12:
                        continue
                    values = values-values.mean()
                    score = float(np.dot(values/np.linalg.norm(values),reference))
                    if score>=threshold and (best is None or score>best['score']):
                        best = {'kind':'villager','box':[left,top,left+19,top+26],
                                'score':score,'name':'learned-villager-portrait'}
        return best
