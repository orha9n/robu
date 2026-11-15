"""EMA Lightning ses çıkışı. Ana GTK sürecinde ağır bağımlılık yüklemez."""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading

EMA_PYTHON = os.path.expanduser('~/.local/share/robu/ema-venv/bin/python')


def okunacak_metin(text):
    """Kod, URL ve araç JSON'u seslendirilmez; yalnızca kesinleşmiş cevap verilir."""
    if text.lstrip().startswith(('{', '<|tool')) or (text.lstrip().startswith('[') and not re.match(r'\s*\[[^\]]+\]\([^)]*\)', text)):
        return ''
    text = re.sub(r'```[\s\S]*?(?:```|$)', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?m)^\s*[#>*-]+\s*', '', text)
    return text.strip()


def hazir_mi(python=None):
    return os.path.isfile(python or EMA_PYTHON) and bool(shutil.which('paplay'))


def _tam_oku(pipe, n):
    data = bytearray()
    while len(data) < n:
        part = pipe.read(n - len(data))
        if not part:
            raise RuntimeError('EMA akışı tamamlanmadan kapandı')
        data.extend(part)
    return bytes(data)


class SesliYanit:
    """Bir sıcak EMA çalışanı, tek ses sırası, iptal için generation epoch.

    Çalışan pencere ile yaşar; daemon/servis değildir. Konuşma ve ses diske yazılmaz.
    Yeni giriş hem oynatmayı hem süren sentezi sonlandırır; eski thread yeni sesi
    kapatamaz. Tamamlanmış, boşta çalışan EMA sonraki cevapta yeniden kullanılır.
    """
    def __init__(self, ayar, hata=None, olcum=None):
        self.ayar, self.hata, self.olcum = ayar, hata, olcum
        self._lock = threading.Lock()
        self._epoch = 0
        self._worker = None
        self._player = None
        self._active = False

    @staticmethod
    def _kes(p):
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except ProcessLookupError:
                return
            # GTK ana döngüsü wait() ile bloke edilmez; çocuk mutlaka reap edilir.
            def reap():
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
            threading.Thread(target=reap, daemon=True).start()

    def yeni_istek(self):
        with self._lock:
            self._epoch += 1
            self._kes(self._player); self._player = None
            if self._active:
                self._kes(self._worker); self._worker = None
            self._active = False
            return self._epoch

    def kapat(self):
        self.yeni_istek()
        with self._lock:
            self._kes(self._worker); self._worker = None

    def soyle(self, text, epoch):
        text = okunacak_metin(text)
        if not text or not self.ayar.get('sesli_yanit', False):
            return
        with self._lock:
            if epoch != self._epoch or self._active:
                return
            self._active = True
        threading.Thread(target=self._konus, args=(text, epoch), daemon=True).start()

    def _konus(self, text, epoch):
        player, worker = None, None
        olcum = self.olcum
        try:
            with self._lock:
                if epoch != self._epoch:
                    return
                python = self.ayar.get('ema_python') or EMA_PYTHON
                if not hazir_mi(python):
                    raise RuntimeError('EMA yerel Python ortamı ya da paplay bulunamadı')
                worker = self._worker
                fresh = worker is None or worker.poll() is not None
                if fresh:
                    env = dict(os.environ, HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
                    worker = subprocess.Popen([python, str(Path(__file__).with_name('tts_ema_worker.py'))],
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, env=env)
                    self._worker = worker
            if fresh and worker.stdout.readline() != b'ROBU_EMA_1\n':
                raise RuntimeError('EMA yerel CPU ortamı başlatılamadı')
            worker.stdin.write(json.dumps({'text': text, 'stream': bool(self.ayar.get('ema_akis', True))},
                                          ensure_ascii=False).encode() + b'\n')
            worker.stdin.flush()
            first = True
            while True:
                n = struct.unpack('<I', _tam_oku(worker.stdout, 4))[0]
                if n == 0:
                    break
                if n > 48000 * 2 * 10 or n % 2:
                    raise RuntimeError('EMA geçersiz ses parçası')
                pcm = _tam_oku(worker.stdout, n)
                with self._lock:
                    if epoch != self._epoch:
                        return
                    if first:
                        if olcum:
                            olcum('first_tts_chunk_generated')
                        # Kendi adıyla: ses karıştırıcısında "Robu" görünür ve PipeWire'ın başka
                        # paplay kullanımları için hatırladığı ses düzeyi (ör. %0) buna uygulanmaz.
                        player = subprocess.Popen(['paplay', '--raw', '--rate=48000', '--channels=1',
                                                   '--format=s16le', '--latency-msec=80',
                                                   '--client-name=Robu',
                                                   '--stream-name=Robu sesli yanıt',
                                                   '--property=application.name=Robu',
                                                   '--property=media.name=Robu sesli yanıt',
                                                   '--property=application.icon_name=robu',
                                                   '--property=media.role=accessibility'],
                                                  stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                        self._player = player
                        if olcum:
                            olcum('audio_player_started')
                        first = False
                player.stdin.write(pcm); player.stdin.flush()
                if olcum:
                    olcum('audio_chunk_submitted')  # fiziksel duyulma zamanı değildir
            if player is not None:
                player.stdin.close(); player.wait()
                if player.returncode:
                    raise RuntimeError('Ses çıkışı çalışmadı')
                if olcum:
                    olcum('audio_playback_completed')
        except (OSError, RuntimeError, ValueError):
            with self._lock:
                current = epoch == self._epoch
                if self._worker is worker:
                    self._kes(worker); self._worker = None
            if current and self.hata:
                self.hata('EMA ses çıkışı kullanılamıyor; yerel ortamı ve ses aygıtını kontrol et.')
        finally:
            self._kes(player)
            with self._lock:
                if epoch == self._epoch:
                    self._active = False
                    self._player = None
