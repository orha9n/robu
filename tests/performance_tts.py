"""Offline EMA say/stream kıyası; sentetik ses bellekte kalır, oynatılmaz/kaydedilmez.

~/.local/share/robu/ema-venv/bin/python tests/performance_tts.py
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import time

os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
                  OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repeats', type=int, default=5)
    ap.add_argument('--scenario', type=int, choices=range(4))
    ap.add_argument('--variants', default='say,stream_1s,stream')
    ap.add_argument('--output', default='docs/performance/results/ema-20261101')
    args = ap.parse_args()
    variants = args.variants.split(',')
    if args.repeats < 1 or 'say' not in variants or any(v not in ('say','stream_1s','stream') for v in variants):
        ap.error('Variants must include say reference and known EMA paths')
    import numpy as np
    import torch
    import ema_lightning
    from ema_lightning import EMA
    import ema_lightning.api as api
    from ema_lightning.engine import WINDOW
    native_first = api.FIRST_WINDOW
    torch.set_num_threads(2); torch.set_num_interop_threads(1)
    load_start = time.perf_counter_ns(); model = EMA(device='cpu')
    load = (time.perf_counter_ns() - load_start) / 1e9
    texts = [
        'Merhaba. Robu ses denemesi tamamlandı.',
        'Türkiye’nin başkenti Ankara’dır. Ankara, İç Anadolu Bölgesi’nde bulunur.',
        'Bugünkü sentetik notumuzda kitap okumak, parkta yürümek ve çay içmek var. '
        'Bu cümleler yalnızca yerel ses üretimini ölçmek için hazırlanmıştır.',
        'Bu denemede herhangi bir kişisel konuşma kullanılmıyor. Ses bilgisayarda üretiliyor '
        've dosyaya kaydedilmiyor. Cümlelerin doğal noktalama işaretleri korunuyor. '
        'Yeni bir istek geldiğinde eski sesin durması gerekiyor. Son cümleyle birlikte deneme sona eriyor.'
    ]
    # Warm both paths; startup stays separate from 20 requests per variant.
    model.say(texts[0], seed=0)
    list(model.stream(texts[0], seed=0))
    rows = []
    for repeat in range(args.repeats):
        for scenario, text in enumerate(texts):
            if args.scenario is not None and scenario != args.scenario:
                continue
            outputs = {}
            order = variants if repeat % 2 == 0 else list(reversed(variants))
            for mode in order:
                start = time.perf_counter_ns(); first = None; chunks = []
                if mode == 'say':
                    speech = model.say(text, seed=0)
                    chunks = [speech.audio]; first = time.perf_counter_ns()
                else:
                    api.FIRST_WINDOW = native_first if mode == 'stream_1s' else WINDOW
                    for chunk in model.stream(text, seed=0):
                        if first is None: first = time.perf_counter_ns()
                        chunks.append(chunk)
                end = time.perf_counter_ns()
                audio = np.concatenate(chunks)
                outputs[mode] = audio
                row = {'variant': mode, 'scenario': scenario, 'repeat': repeat,
                       'first_chunk_s': (first-start)/1e9, 'completed_s': (end-start)/1e9,
                       'audio_s': len(audio)/48000, 'chunks': len(chunks),
                       'finite': bool(np.isfinite(audio).all()), 'non_silent': bool(np.max(np.abs(audio)) > .01)}
                rows.append(row)
            for row in rows[-len(order):]:
                audio = outputs[row['variant']]; ref = outputs['say']
                equal_shape = audio.shape == ref.shape
                row['stream_matches_say'] = bool(equal_shape and np.allclose(ref, audio, atol=2e-5, rtol=1e-4))
                row['max_abs_difference'] = float(np.max(np.abs(ref-audio))) if equal_shape else None
                row['rmse'] = float(np.sqrt(np.mean((ref-audio)**2))) if equal_shape else None
            print(json.dumps({'scenario': scenario, 'repeat': repeat, 'match': [r['stream_matches_say'] for r in rows[-len(order):]]}), flush=True)
    summary = {}
    for mode in variants:
        selected = [r for r in rows if r['variant'] == mode]
        stats = {'n': len(selected), 'all_finite': all(r['finite'] for r in selected),
                 'all_non_silent': all(r['non_silent'] for r in selected),
                 'all_match': all(r['stream_matches_say'] for r in selected)}
        for name in ('first_chunk_s', 'completed_s'):
            values = sorted(r[name] for r in selected)
            stats[name] = {'p50': statistics.median(values), 'p95': values[max(0, math.ceil(len(values)*.95)-1)]}
        summary[mode] = stats
    data = {'torch': torch.__version__, 'ema': ema_lightning.__version__, 'threads': 2,
            'device': 'cpu', 'offline': True, 'native_first_frames':native_first, 'compatible_first_frames':WINDOW, 'load_s_excluding_imports': load,
            'scope': 'synthetic PCM generated, not audible playback; same seed per text',
            'rows': rows, 'summary': summary}
    import csv
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(data, indent=2))
    with output.with_suffix('.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__': main()
