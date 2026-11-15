"""Üretim EMA worker + gerçek paplay yolu; testte yalnızca bu oynatıcı sessizdir.

python3 tests/check_tts_runtime.py
Varsayılan sink/sistem sesi değiştirilmez, ses dosyası kaydedilmez.
"""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robu import tts


def wait_idle(voice, timeout=45):
    deadline = time.perf_counter()+timeout
    while voice._active and time.perf_counter() < deadline:
        time.sleep(.01)
    if voice._active: raise RuntimeError('TTS deadline exceeded')


def main():
    rows, errors, players = [], [], []
    original = tts.subprocess.Popen
    def launch(command, *args, **kwargs):
        if command[0] == 'paplay':
            p = original(command+['--volume=0'], *args, **kwargs)
            players.append(p); return p
        return original(command, *args, **kwargs)
    voice = tts.SesliYanit({'sesli_yanit': True}, hata=errors.append)
    def speak(text, name, buffered=False):
        epoch = voice.yeni_istek(); points = {}; start = time.perf_counter_ns()
        voice.olcum = lambda name: points.setdefault(name, (time.perf_counter_ns()-start)/1e9)
        voice.ayar['ema_akis'] = not buffered
        voice.soyle(text, epoch); wait_idle(voice)
        rows.append({'scenario': name, 'points': points, 'total_s': (time.perf_counter_ns()-start)/1e9})
        if errors or 'audio_chunk_submitted' not in points: raise RuntimeError('Local playback path failed')
    try:
        with patch.object(tts.subprocess, 'Popen', side_effect=launch):
            speak('Robu ses denemesi tamamlandı.', 'cold_stream')
            speak('Robu ses denemesi tamamlandı.', 'warm_stream')
            speak('Robu ses denemesi tamamlandı.', 'warm_buffered', buffered=True)
            voice.ayar['ema_akis'] = True
            epoch = voice.yeni_istek(); points = {}; start = time.perf_counter_ns()
            voice.olcum = lambda name: points.setdefault(name, (time.perf_counter_ns()-start)/1e9)
            voice.soyle('Bu uzun sentetik konuşma yarıda kesilecek. Yeni istek geldiğinde eski üretim '
                        've oynatma hemen durmalı. Bu metin hiçbir dosyaya kaydedilmiyor. '*5, epoch)
            deadline = time.perf_counter()+30
            while 'first_tts_chunk_generated' not in points and time.perf_counter() < deadline:
                time.sleep(.01)
            if 'first_tts_chunk_generated' not in points: raise RuntimeError('Cancel setup failed')
            worker = voice._worker; started = time.perf_counter_ns(); voice.yeni_istek()
            cancel_call = (time.perf_counter_ns()-started)/1e9
            worker.wait(timeout=3)
            rows.append({'scenario':'cancel', 'cancel_call_s':cancel_call, 'worker_exited':worker.poll() is not None})
            speak('Yeni sentetik yanıt.', 'new_generation_after_cancel')
    finally:
        worker = voice._worker; voice.kapat()
        if worker is not None: worker.wait(timeout=3)
    data = {'scope':'real worker + real paplay, volume=0 for these test processes only; no physical audible-time claim',
            'rows':rows, 'errors':len(errors), 'player_exit_codes':[p.wait(timeout=3) for p in players]}
    target = Path(__file__).resolve().parents[1] / 'docs/performance/results/tts-runtime-20261101.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2)); print(json.dumps(data, indent=2))

if __name__ == '__main__': main()
