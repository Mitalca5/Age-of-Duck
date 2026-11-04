"""Pre-optimization implementation for byte-for-byte result checks and timing."""
from pathlib import Path
import cv2
import numpy as np
from tc_reminder.vision import Detector,gray

class ReferenceDetector(Detector):
    def matches(self, image, category, region, threshold):
        x0, y0, x1, y1 = region
        hay = gray(image.crop(region))
        hits = []
        for meta, template in self.templates:
            if meta['kind'] != category or template.shape[0] > hay.shape[0] or template.shape[1] > hay.shape[1]:
                continue
            search = (hay>210).astype(np.uint8)*255 if meta.get('binary') else hay
            result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            # Bound candidate work even on pathological input.
            for _ in range(64):
                _, score, _, (x, y) = cv2.minMaxLoc(result)
                if score < (max(threshold,.94) if meta.get('reference_only') else threshold) or not np.isfinite(score):
                    break
                h, w = template.shape
                hits.append({'kind': category, 'box': [x+x0, y+y0, x+x0+w, y+y0+h], 'score': score,
                             'name':meta.get('label',Path(meta['file']).stem)})
                result[max(0,y-h//2):y+h//2+1, max(0,x-w//2):x+w//2+1] = -1
        kept = []
        for hit in sorted(hits, key=lambda v: -v['score']):
            x,y,r,b = hit['box']
            if not any(abs(x-h['box'][0]) < (r-x)*0.7 and abs(y-h['box'][1]) < (b-y)*0.7 for h in kept):
                kept.append(hit)
        return sorted(kept, key=lambda v:v['box'][0])

    def analyze_queue(self,image,threshold=.86):
        """Analyze actual queue pixels; usable on supplied top-left crops without claiming gameplay."""
        p=self.profile
        result={'busy':0,'research':0,'research_waiting':0,'waiting':0,'housed':0,
                'busy_upper_bound':0,'non_tc':0,'hits':[],'unknown':[],'unclassified':0,'queue_overflow':False,'possible_housed':False}
        # These small regions are explicitly marked on actual screenshots.
        queue = self.rect('queue', image.size)
        queue[2]=min(queue[2],image.width)
        for kind in ('villager', 'research', 'research_waiting', 'housed', 'non_tc'):
            result['hits'] += self.matches(image, kind, queue, max(.95,threshold) if kind=='non_tc' else threshold)
        # Consolidate variant templates into ONE entry per queue slot.
        slots = {}
        for hit in result['hits']:
            centre = (hit['box'][0]+hit['box'][2])/2
            slot = int((centre - queue[0])/p['queue_pitch'])
            if slot not in slots or slots[slot]['score'] < hit['score']:
                slots[slot] = hit
        rgb = np.asarray(image.convert('RGB'))
        for index, hit in slots.items():
            x = round(queue[0]+index*p['queue_pitch'])
            patch = rgb[queue[1]+2:queue[1]+35,x+2:x+35].astype(float)
            red = np.mean((patch[:,:,0]>90)&(patch[:,:,0]>1.6*patch[:,:,1])&(patch[:,:,0]>1.6*patch[:,:,2]))
            # Observed housed examples: 18–32% red; observed running examples: 0%.
            if hit['kind']=='housed' and red < .12:
                hit['kind']='villager'
            if hit['kind']=='villager' and red >= .12:
                hit['kind'] = 'housed'
            if hit['kind'] in ('research','research_waiting','villager'):
                art=rgb[queue[1]+3:queue[1]+20,x+4:x+31].astype(float)
                gold=np.mean((art[:,:,0]>100)&(art[:,:,1]>65)&(art[:,:,0]>1.4*art[:,:,2])&(art[:,:,1]>1.3*art[:,:,2]))
                # Observed waiting art is >97% gold; active examples are <37%.
                # Grayscale correlation alone confuses these tint variants.
                if hit['kind']=='villager':
                    if gold>.85:hit['kind']='waiting'
                else:hit['kind']='research_waiting' if gold>.85 else 'research'

        result['hits'] = list(slots.values())
        result['non_tc']=sum(h['kind']=='non_tc' for h in result['hits'])
        result['busy'] = sum(h['kind']=='villager' for h in result['hits'])
        result['research'] = sum(h['kind']=='research' for h in result['hits'])
        # Entries may share a TC. Their sum is an upper bound, not an exact TC count.
        # A shortfall even against this bound proves a possible missing busy TC.
        result['busy_upper_bound'] = result['busy'] + result['research']
        result['waiting'] = sum(h['kind']=='waiting' for h in result['hits'])
        result['research_waiting'] = sum(h['kind']=='research_waiting' for h in result['hits'])
        result['housed'] = sum(h['kind'] == 'housed' for h in result['hits'])
        # Tiles that no stored picture matches. They are shown in debug and also counted as
        # possible activity (see below), but only when they continue the row of tiles that
        # starts at the left edge: the queue fills from the left, so isolated "frames" further
        # right are terrain or noise.
        pitch = int(round(p['queue_pitch']))
        tile_count = int((queue[2]-queue[0])/p['queue_pitch'])
        def has_frame(x, y):
            colour = rgb[max(0,y-1):y+p['queue_height']+1, x:x+pitch].astype(float)
            if colour.shape[0] < 8 or colour.shape[1] < pitch:
                return False
            neutral = (colour.max(2)-colour.min(2)<28)&(colour.mean(2)>65)
            # Actual box frames are neutral grey/white. Blue range lines and tan terrain
            # are not frames. Require substantial top AND bottom border support.
            if np.count_nonzero(neutral[:4]) > pitch*.6 and np.count_nonzero(neutral[-4:]) > pitch*.6:
                return True
            # Progress shading hides the frame on some tiles; the white hotkey letter in the
            # bottom-right corner (Q, A, Z ...) is on every queue tile.
            corner = rgb[y+18:y+p['queue_height'], x+14:x+pitch].astype(float)
            return corner.size > 0 and np.count_nonzero(corner.min(2) > 215) >= 14
        framed = {}
        for index in range(tile_count):
            if index in slots:
                continue
            x0 = round(queue[0] + index*p['queue_pitch'])
            # Another skin or a rescaled box can sit a few pixels off the calibrated grid.
            for dy in (0, -1, 1, -2, 2, -3, 3):
                for dx in (0, -1, 1, -2, 2, -3, 3):
                    if has_frame(x0+dx, queue[1]+dy):
                        framed[index] = (x0+dx, queue[1]+dy)
                        break
                if index in framed:
                    break
        row_end = 0
        while row_end in slots or row_end in framed:
            row_end += 1
        for index, (x, y) in sorted(framed.items()):
            if index >= row_end:
                continue
            box = [x, y, x+pitch, y+p['queue_height']]
            result['unknown'].append(box)
            art = rgb[y+2:y+35, x+2:x+35].astype(float)
            red = np.mean((art[:,:,0]>90)&(art[:,:,0]>1.6*art[:,:,1])&(art[:,:,0]>1.6*art[:,:,2]))
            result['possible_housed'] |= bool(red>=.12)
            top = rgb[y+3:y+20, x+4:x+31].astype(float)
            gold = np.mean((top[:,:,0]>100)&(top[:,:,1]>65)&(top[:,:,0]>1.4*top[:,:,2])&(top[:,:,1]>1.3*top[:,:,2]))
            # A research tile turns green as its progress bar fills (Age up at 70% ...), which
            # no stored template covers. Green progress is research in progress.
            green = np.mean((art[:,:,1]>70)&(art[:,:,1]>1.25*art[:,:,0])&(art[:,:,1]>1.25*art[:,:,2]))
            if gold > .85:
                result['waiting'] += 1            # queued behind another item: not activity
            elif green >= .22 and red < .12:
                result['hits'].append({'kind':'research','box':box,'score':float(green),'name':'research-progress'})
            else:
                result['unclassified'] += 1
        # Recount now that green research tiles were found among the unclassified boxes.
        result['research'] = sum(h['kind']=='research' for h in result['hits'])
        # A queue tile nothing recognises might be Town Centre production in a state with no
        # stored picture (age-up progress, a queued unit with a count badge, another skin).
        # Treat it as possible activity: wrongly staying quiet beats a false idle alarm.
        result['busy_upper_bound'] = result['busy'] + result['research'] + result['unclassified']
        result['queue_overflow'] = any(index>=int((queue[2]-queue[0])/p['queue_pitch'])-1 and hit['kind']!='non_tc' for index,hit in slots.items())
        # Unmatched terrain/units cannot veto the user's explicit TC allowlist.
        # Only recognized TC activity at the boundary indicates possible truncation.
        return result

