"""Sesli giriş: gerçek mikrofondan kayıt ve çevrimdışı Türkçe Vosk tanıma.

Vosk kuruluysa Türkçe modeli kullanılır; yoksa whisper-cli ve model aranır.
Ses dosyası bilgisayardan çıkmaz ve yazıya çevrildikten sonra silinir.
"""
import array
import glob
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave

KOK = os.path.expanduser("~/.local/share/robu")
CLI_ADAYLARI = [os.path.join(KOK, "whisper.cpp/build/bin/whisper-cli")]
MODEL_KLASORU = os.path.join(KOK, "whisper-modelleri")
# Türkçe için isabet/hız dengesine göre tercih sırası
# whisper'a bağlam: Robu'da sık geçen sözcüklerin doğru yazımı (RAM→REM, masa üstü… hatalarını azaltır)
IPUCU = ("Robu, bilgisayar komutları: Masaüstü, İndirilenler, Belgeler, RAM, PDF, CPU, disk, "
         "klasör, dosya, çöp kutusu, internet.")
MODEL_SIRASI = ("small-q5_1", "small", "base-q5_1", "base", "medium-q5_0", "tiny")


def cli_yolu():
    for yol in CLI_ADAYLARI:
        if os.access(yol, os.X_OK):
            return yol
    return shutil.which("whisper-cli")


def model_yolu():
    modeller = glob.glob(os.path.join(MODEL_KLASORU, "ggml-*.bin"))
    for tercih in MODEL_SIRASI:
        for m in modeller:
            if os.path.basename(m) == f"ggml-{tercih}.bin":
                return m
    return modeller[0] if modeller else None


def hazir_mi():
    return bool((vosk_hazir_mi() or (cli_yolu() and model_yolu()))
                and (shutil.which("arecord") or shutil.which("parec")))


ORAN = 16000                # whisper'ın beklediği örnekleme hızı (Hz)
PARCA_BAYT = ORAN * 2 // 20  # 50 ms'lik 16 bit mono parça
EN_UZUN_KAYIT = 60          # saniye; unutulan kayıt sonsuza dek sürmesin
KONUSMA_BEKLEME = 5         # konuşma gelmezse yanlış kayıt üretmeden dur
VOSK_MODEL = os.path.join(KOK, "vosk-model-small-tr-0.3")
VOSK_PYTHON = os.path.join(KOK, "ses-venv/bin/python")


def vosk_hazir_mi():
    # Eski Türkçe paketinde final.mdl kökte; yeni Vosk paketlerinde am/ altında.
    return any(os.path.isfile(os.path.join(VOSK_MODEL, p)) for p in ("am/final.mdl", "final.mdl")) \
        and os.access(VOSK_PYTHON, os.X_OK)


def mikrofon_kaynagi():
    """Varsayılan kaynak monitor ise gerçek mikrofonu seç; sistem ayarını değiştirme."""
    if not shutil.which("pactl") or not shutil.which("parec"):
        return None
    try:
        sources = json.loads(subprocess.check_output(["pactl", "-f", "json", "list", "sources"],
                                                     text=True, stderr=subprocess.DEVNULL, timeout=3))
        default = subprocess.check_output(["pactl", "get-default-source"], text=True, timeout=3).strip()
        mic = [s["name"] for s in sources if not s["name"].endswith(".monitor")
               and s.get("properties", {}).get("device.class") != "monitor"]
        if not mic:
            raise RuntimeError("Gerçek mikrofon bulunamadı; ses giriş aygıtını kontrol edin.")
        uygun = []
        for s in sources:
            if s["name"] not in mic:
                continue
            active = s.get("active_port")
            port = next((p for p in s.get("ports", []) if p.get("name") == active), {})
            if port.get("availability") != "not available":
                uygun.append(s["name"])
        if not uygun:
            raise RuntimeError("Ses sistemi mikrofon girişini kullanılamıyor gösteriyor. "
                               "Mikrofon bağlantısını ve sistemin Ses → Giriş ayarını kontrol edin.")
        return default if default in uygun else uygun[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class SessizlikDedektoru:
    """Konuşma başlayıp ardından `sessizlik` saniye sessizlik olunca True döner.

    Ortam gürültüsü ilk 0,5 saniyeden ölçülür; eşik onun 3 katı (en az 100). Böylece sessiz
    odada da gürültülü odada da çalışır. İlk anda konuşulduysa sonraki düşük enerjiyle
    kalibrasyonu düzeltir; başlangıç konuşması ortam gürültüsü sayılmaz."""

    def __init__(self, sessizlik=1.5):
        self.sessizlik_parca = int(sessizlik * 20)
        self.olcum, self.esik = [], None
        self.konusma, self.sessiz = False, 0
        self.konusma_parca = 0

    @staticmethod
    def _guc(parca):
        ornek = array.array("h", parca[:len(parca) // 2 * 2])
        return math.sqrt(sum(x * x for x in ornek) / len(ornek)) if ornek else 0.0

    def besle(self, parca):
        guc = self._guc(parca)
        if self.esik is None:
            self.olcum.append(guc)
            if len(self.olcum) >= 10:  # 0,5 sn
                self.esik = max(100.0, 3 * sorted(self.olcum)[len(self.olcum) // 2])
            return False
        # İlk 0,5 sn tamamen konuşmaysa eşik konuşmanın üstüne çıkmış olabilir.
        if not self.konusma and min(self.olcum) > 100 and guc < min(self.olcum) / 3:
            self.esik = max(100.0, guc * 3)
            self.konusma = True
            self.konusma_parca = len(self.olcum)
        if guc > self.esik:
            self.konusma, self.sessiz = True, 0
            self.konusma_parca += 1
        elif self.konusma:
            self.sessiz += 1
        return self.konusma and self.sessiz >= self.sessizlik_parca


class Kayit:
    """Mikrofondan 16 kHz mono kayıt (whisper'ın beklediği biçim). arecord ham sesi bir iş
    parçacığına akıtır; `sessizlikte` verilirse konuşma bitince (sessizlik) bu geri çağırma
    bir kez çağrılır (kullanıcı ikinci kez basmak zorunda kalmasın)."""

    def __init__(self, sessizlikte=None, aygit=None):
        self.dosya = None
        self._surec = None
        self._ses = bytearray()
        self._sessizlikte = sessizlikte
        self._aygit = aygit
        self._is = None
        self._dedektor = SessizlikDedektoru()
        self.kaynak = None
        self.hata = None
        self._hata_akis = None

    def baslat(self):
        komut = ["arecord", "-q", "-f", "S16_LE", "-r", str(ORAN), "-c", "1", "-t", "raw"]
        if self._aygit:
            komut += ["-D", self._aygit]
        else:
            self.kaynak = mikrofon_kaynagi()
            if self.kaynak:
                komut = ["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1",
                         "--device=" + self.kaynak, "--client-name=Robu", "--latency-msec=50"]
        self._hata_akis = tempfile.TemporaryFile()
        try:
            self._surec = subprocess.Popen(komut, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=self._hata_akis)
        except OSError:
            self._hata_akis.close()
            self._hata_akis = None
            raise
        self._is = threading.Thread(target=self._oku, args=(self._surec,), daemon=True)
        self._is.start()

    def _oku(self, surec):
        dedektor = self._dedektor
        cagrildi = False
        akis = surec.stdout
        while True:
            parca = akis.read(PARCA_BAYT)
            if not parca:  # arecord bitti (durduruldu ya da açılamadı): arayüz beklemede kalmasın
                if not cagrildi and self._sessizlikte:
                    self._sessizlikte()
                return
            self._ses += parca
            sessizlik = dedektor.besle(parca)
            konusma_yok = not dedektor.konusma and len(self._ses) >= KONUSMA_BEKLEME * ORAN * 2
            if len(self._ses) > EN_UZUN_KAYIT * ORAN * 2:
                parca = b""  # sınır: durdurmayı iste
            if not cagrildi and self._sessizlikte and (not parca or sessizlik or konusma_yok):
                cagrildi = True
                self._sessizlikte()
                return

    def bitir(self):
        """Kaydı durdurur; WAV dosyasının yolunu döndürür (kayıt çok kısaysa None)."""
        p, self._surec = self._surec, None
        if p is None:
            return None
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        if self._is is not None:
            self._is.join(timeout=3)
        if p.stdout:
            p.stdout.close()
        if self._hata_akis:
            self._hata_akis.seek(0)
            hata = self._hata_akis.read(2000).decode("utf-8", errors="replace").strip()
            self._hata_akis.close()
            self._hata_akis = None
        else:
            hata = ""
        if len(self._ses) < ORAN * 2 // 5:
            self.hata = ("Mikrofon kaydı alınamadı: " + hata[:300]) if hata else \
                "Kayıt 0,2 saniyeden kısa; mikrofonu başlatıp biraz daha uzun konuşun."
            return None
        # Konuşma dedektörü otomatik durdurma içindir; düşük sesli/erken başlayan
        # gerçek kaydı veto etmez. Yalnızca gerçekten sessiz sinyali eleriz.
        if SessizlikDedektoru._guc(self._ses) < 5:
            self.hata = "Mikrofondan ses gelmedi; mikrofon girişini ve ses düzeyini kontrol edin."
            return None
        fd, self.dosya = tempfile.mkstemp(prefix="robu-ses-", suffix=".wav")
        with os.fdopen(fd, "wb") as f, wave.open(f, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(ORAN)
            w.writeframes(bytes(self._ses))
        return self.dosya

    def iptal(self):
        self.bitir()
        self.temizle()

    def temizle(self):
        if self.dosya:
            try:
                os.remove(self.dosya)
            except OSError:
                pass
            self.dosya = None


def yaziya_cevir(wav, dil="tr", is_parcacigi=None):
    """WAV dosyasını yerel Vosk/Whisper ile yazıya çevirir; hata olursa RuntimeError."""
    # Kayit dışındaki çağrılarda da sessizlikte Whisper'ın sözcük uydurmasını önle.
    with wave.open(wav, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != ORAN:
            raise RuntimeError("16 kHz, 16 bit, mono WAV gerekli.")
        while True:
            parca = w.readframes(ORAN // 20)
            if not parca:
                return ""
            if SessizlikDedektoru._guc(parca) >= 5:
                break
    if vosk_hazir_mi() and dil == "tr":
        worker = os.path.join(os.path.dirname(__file__), "ses_vosk.py")
        p = subprocess.run([VOSK_PYTHON, worker, VOSK_MODEL, wav], capture_output=True,
                           text=True, timeout=60)
        if p.returncode:
            raise RuntimeError("Türkçe ses tanıma çalışmadı: " + p.stderr.strip()[-300:])
        return duzelt(p.stdout.strip())
    cli, model = cli_yolu(), model_yolu()
    if not cli or not model:
        raise RuntimeError("whisper.cpp ya da modeli bulunamadı.")
    is_parcacigi = is_parcacigi or max(1, min(6, (os.cpu_count() or 2) - 1))
    p = subprocess.run([cli, "-m", model, "-f", wav, "-l", dil, "-nt", "-np",
                        "-t", str(is_parcacigi), "--prompt", IPUCU],
                       capture_output=True, text=True, timeout=300)
    if p.returncode:
        raise RuntimeError((p.stderr or "whisper-cli başarısız").strip()[-300:])
    metin = " ".join(p.stdout.split())
    # whisper sessizlikte etiket üretir: [BLANK_AUDIO], (Müzik), [alkış]…
    return duzelt(re.sub(r"\[[^\]]*\]|\([^)]*\)", "", metin).strip())


# whisper'ın Türkçede sık böldüğü bileşik sözcükler
_BIRLESIK = re.compile(r"\b([Mm])asa üstü", re.U)


def duzelt(metin):
    return _BIRLESIK.sub(lambda m: m[1] + "asaüstü", metin)
