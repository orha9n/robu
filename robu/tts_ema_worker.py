"""İzole EMA CPU çalışanı: stdin JSON metin, stdout uzunluk+PCM; dosya/ağ yok."""
import json
import os
import struct
import sys

# Modelin config kontrolü dahil tüm Hugging Face erişimleri yalnızca yerel cache.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['MKL_NUM_THREADS'] = '2'


def ses_parcalari(tts, req):
    if req.get('stream', True):
        yield from tts.stream(req['text'], seed=0, sample_rate=48000)
    else:
        # Karşılaştırma/rollback: tüm ses hazır olmadan ilk PCM gönderilmez.
        audio = tts.say(req['text'], seed=0, sample_rate=48000).audio
        for start in range(0, len(audio), 48000 * 4):
            yield audio[start:start + 48000 * 4]


def main():
    import torch
    from ema_lightning import EMA
    import ema_lightning.api as api
    from ema_lightning.engine import WINDOW
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    # Yerel EMA 1.0.1'de 1 saniyelik ilk pencere say() ile örnek eşliği
    # vermedi. Aynı 4 saniyelik pencere sınırları çıktıyı koruyarak akışı açar.
    api.FIRST_WINDOW = WINDOW
    tts = EMA(device='cpu')  # .lightning()/CUDA kullanılmaz
    out = sys.stdout.buffer
    out.write(b'ROBU_EMA_1\n'); out.flush()
    for line in sys.stdin.buffer:
        req = json.loads(line)
        stream = ses_parcalari(tts, req)
        try:
            for chunk in stream:
                pcm = (chunk.clip(-1, 1) * 32767).astype('<i2').tobytes()
                out.write(struct.pack('<I', len(pcm))); out.write(pcm); out.flush()
            out.write(struct.pack('<I', 0)); out.flush()
        finally:
            stream.close()


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    except Exception:
        # Hata metni kullanıcı metnini içerebilir: yalnızca sabit hata kodu.
        sys.stderr.write('EMA_LOCAL_RUNTIME_ERROR\n')
        sys.exit(1)
