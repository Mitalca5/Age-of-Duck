"""Approval is tied to reviewed screenshot calibration, not a user checkbox."""
import hashlib
import json
from itertools import product
from .paths import ROOT

ALGORITHM_VERSION = '2026-09-30-tc-allowlist-overlay-v4'

def fingerprint():
    h=hashlib.sha256(ALGORITHM_VERSION.encode())
    for name in ('calibration.json','clock-calibration.json','population-glyphs.json'):
        h.update((ROOT/name).read_bytes())
    p=json.loads((ROOT/'calibration.json').read_text())
    for template in p['templates']:
        h.update((ROOT/template['file']).read_bytes())
    return h.hexdigest()

def compatible_fingerprints():
    """Accept legacy approvals across Git LF/CRLF conversions only.

    JSON content and binary templates must remain byte-identical otherwise.
    Older approvals were produced with different Windows checkout settings.
    """
    names=('calibration.json','clock-calibration.json','population-glyphs.json')
    variants=[]
    for name in names:
        lf=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
        variants.append(tuple(dict.fromkeys((lf,lf.replace(b'\n',b'\r\n')))))
    profile=json.loads((ROOT/'calibration.json').read_text())
    templates=[(ROOT/t['file']).read_bytes() for t in profile['templates']]
    for files in product(*variants):
        h=hashlib.sha256(ALGORITHM_VERSION.encode())
        for data in files:h.update(data)
        for data in templates:h.update(data)
        yield h.hexdigest()

def approved():
    try:
        a=json.loads((ROOT/'validation-approval.json').read_text())
        return a.get('approved') is True and a.get('fingerprint') in compatible_fingerprints()
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return False
