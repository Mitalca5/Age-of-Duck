"""Compare the unchanged recognition results and median cost on public fixtures."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from tc_reminder.vision import Detector
from queue_reference import ReferenceDetector

def main():
    root=Path(__file__).resolve().parents[1]
    before=ReferenceDetector();after=Detector();results=[]
    for name in ('selected-three.png','foundation-five.png','independent-four.png'):
        with Image.open(root/'tc_reminder/samples'/name) as source:frame=source.convert('RGB')
        assert before.analyze_queue(frame)==after.analyze_queue(frame),name
        timings={}
        for label,detector in [('before',before),('after',after)]:
            measurements=[]
            for _ in range(5):
                start=time.perf_counter();detector.analyze_queue(frame)
                measurements.append((time.perf_counter()-start)*1000)
            timings[label]=round(statistics.median(measurements),3)
        results.append(dict(fixture=name,size=frame.size,median_ms=timings))
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
