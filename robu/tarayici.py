"""Robu'nun Chrome'u yönetmesi: Chrome DevTools Protokolü (CDP) üzerinden.

Robu'ya ait ayrı bir profil kullanılır (~/.local/share/robu/chrome); kullanıcının
hesaplarına, şifrelerine ve geçmişine erişilmez. Yalnızca standart kütüphane.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request

PORT = 9333
PROFIL = os.path.expanduser("~/.local/share/robu/chrome")
ARAMA = "https://html.duckduckgo.com/html/?q="  # hafif, çerez onayı / CAPTCHA çıkarmaz
METIN_PARCASI = 1800   # modele bir seferde gösterilen sayfa metni (karakter)
OGE_SINIRI = 40        # numaralanan en fazla tıklanabilir öğe


class TarayiciHatasi(Exception):
    pass


# ---------------------------------------------------------------- WebSocket (RFC 6455)

class WebSocket:
    """CDP için yeterli, en küçük WebSocket istemcisi (yalnızca ws://, metin çerçeveleri)."""

    def __init__(self, url, zaman_asimi=30):
        p = urllib.parse.urlparse(url)
        self.sok = socket.create_connection((p.hostname, p.port), timeout=zaman_asimi)
        anahtar = base64.b64encode(os.urandom(16)).decode()
        istek = (f"GET {p.path} HTTP/1.1\r\nHost: {p.hostname}:{p.port}\r\n"
                 "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Key: {anahtar}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sok.sendall(istek.encode())
        yanit = b""
        while b"\r\n\r\n" not in yanit:
            parca = self.sok.recv(4096)
            if not parca:
                raise TarayiciHatasi("Chrome bağlantıyı kapattı")
            yanit += parca
        if b" 101 " not in yanit.split(b"\r\n", 1)[0]:
            raise TarayiciHatasi("Chrome WebSocket bağlantısını reddetti")
        self.artik = yanit.split(b"\r\n\r\n", 1)[1]

    def _oku(self, n):
        while len(self.artik) < n:
            parca = self.sok.recv(max(65536, n - len(self.artik)))
            if not parca:
                raise TarayiciHatasi("Chrome bağlantısı koptu")
            self.artik += parca
        veri, self.artik = self.artik[:n], self.artik[n:]
        return veri

    def _cerceve_gonder(self, kod, veri):
        maske = os.urandom(4)
        n = len(veri)
        if n < 126:
            baslik = struct.pack("!BB", 0x80 | kod, 0x80 | n)
        elif n < 65536:
            baslik = struct.pack("!BBH", 0x80 | kod, 0x80 | 126, n)
        else:
            baslik = struct.pack("!BBQ", 0x80 | kod, 0x80 | 127, n)
        # XOR maskesini tek seferde uygula (bayt bayt döngüden çok daha hızlı)
        tekrar = (maske * (n // 4 + 1))[:n]
        maskeli = (int.from_bytes(veri, "big") ^ int.from_bytes(tekrar, "big")).to_bytes(n, "big")
        self.sok.sendall(baslik + maske + maskeli)

    def gonder(self, metin):
        self._cerceve_gonder(0x1, metin.encode())

    def al(self):
        parcalar = []
        while True:
            b1, b2 = self._oku(2)
            kod, son, n = b1 & 0x0F, b1 & 0x80, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._oku(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._oku(8))[0]
            veri = self._oku(n)
            if kod == 0x9:      # ping
                self._cerceve_gonder(0xA, veri)
                continue
            if kod == 0x8:      # kapat
                raise TarayiciHatasi("Chrome bağlantıyı kapattı")
            if kod in (0x0, 0x1, 0x2):
                parcalar.append(veri)
                if son:
                    return b"".join(parcalar).decode("utf-8", "replace")

    def kapat(self):
        try:
            self.sok.close()
        except OSError:
            pass


# ---------------------------------------------------------------- sayfadan özet çıkaran betik

OZET_JS = r"""
(() => {
  const gorunur = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  document.querySelectorAll('[data-robu]').forEach(e => e.removeAttribute('data-robu'));
  const secici = 'a[href], button, input:not([type=hidden]), textarea, select, ' +
    '[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], ' +
    '[contenteditable=true], summary';
  const ogeler = [], gorulen = new Set();
  let n = 0;
  for (const el of document.querySelectorAll(secici)) {
    if (!gorunur(el)) continue;
    if (el.tagName === 'A') {  // aynı adrese giden bağlantıları bir kez listele
      if (gorulen.has(el.href)) continue;
      gorulen.add(el.href);
      // "İçeriğe geç / Skip to content" gibi erişilebilirlik atlama bağlantıları
      if ((el.getAttribute('href') || '').startsWith('#') &&
          /içeriğe geç|ana içeri|skip|atla/.test((el.innerText || '').toLocaleLowerCase('tr')))
        continue;
    }
    const tag = el.tagName.toLowerCase();
    let ad = (el.innerText || el.value || el.getAttribute('aria-label') ||
              el.getAttribute('placeholder') || el.getAttribute('title') ||
              el.getAttribute('alt') || el.name || '').trim().replace(/\s+/g, ' ').slice(0, 70);
    let tur = 'düğme';
    if (tag === 'a') tur = 'bağlantı';
    else if (tag === 'textarea' || el.isContentEditable) tur = 'yazı kutusu';
    else if (tag === 'select') tur = 'seçim listesi';
    else if (tag === 'input') {
      tur = {checkbox: 'onay kutusu', radio: 'seçenek', submit: 'düğme', button: 'düğme',
             image: 'düğme', reset: 'düğme'}[el.type] || 'yazı kutusu';
    }
    if (!ad && tur === 'bağlantı') continue;
    n++;
    el.setAttribute('data-robu', n);
    ogeler.push('[' + n + '] ' + tur + ': ' + (ad || '(adsız)'));
    if (n >= %d) break;
  }
  // Ana içerik varsa onu oku; menü, seçim listesi ve alt bilgi satırlarını at
  let kok = document.querySelector('main, article, [role=main]');
  if (!kok || (kok.innerText || '').trim().length < 200) kok = document.body;
  const atla = new Set();
  document.querySelectorAll('option').forEach(o => atla.add(o.textContent.trim()));
  if (kok === document.body)
    document.querySelectorAll('nav, header, footer, aside, [role=navigation]').forEach(e =>
      (e.innerText || '').split('\n').forEach(l => { l = l.trim(); if (l) atla.add(l); }));
  const metin = (kok ? kok.innerText : '').split('\n')
    .map(l => l.replace(/[ \t]+/g, ' ').trim()).filter(l => l && !atla.has(l)).join('\n');
  return JSON.stringify({baslik: document.title, adres: location.href, metin: metin, ogeler: ogeler});
})()
""" % OGE_SINIRI


# ---------------------------------------------------------------- tarayıcı

class Tarayici:
    """Tek bir Chrome sekmesini yönetir. İlk kullanımda Chrome'u açar."""

    def __init__(self):
        self.ws = None
        self.sira = 0
        self.kilit = threading.Lock()
        self.son_metin = ""

    # ---------- bağlantı

    @staticmethod
    def _chrome_yolu():
        for ad in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            yol = shutil.which(ad)
            if yol:
                return yol
        raise TarayiciHatasi("Chrome bulunamadı. Kurulum: google-chrome-stable paketi")

    @staticmethod
    def _http(yol, yontem="GET"):
        istek = urllib.request.Request(f"http://127.0.0.1:{PORT}{yol}", method=yontem)
        with urllib.request.urlopen(istek, timeout=5) as r:
            return json.load(r)

    def _calisiyor_mu(self):
        try:
            self._http("/json/version")
            return True
        except OSError:
            return False

    def _baslat(self):
        os.makedirs(PROFIL, exist_ok=True)
        subprocess.Popen(
            [self._chrome_yolu(), f"--remote-debugging-port={PORT}",
             f"--user-data-dir={PROFIL}", "--no-first-run", "--no-default-browser-check",
             "--disable-features=Translate", "--lang=tr", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):
            if self._calisiyor_mu():
                return
            time.sleep(0.25)
        raise TarayiciHatasi("Chrome başlatılamadı")

    def _baglan(self):
        if self.ws is not None:
            return
        if not self._calisiyor_mu():
            self._baslat()
        sayfalar = [h for h in self._http("/json/list")
                    if h.get("type") == "page" and not h["url"].startswith("devtools://")]
        hedef = sayfalar[0] if sayfalar else self._http("/json/new?about:blank", "PUT")
        self.ws = WebSocket(hedef["webSocketDebuggerUrl"])
        self._cdp("Page.enable")
        self._cdp("Page.bringToFront")

    def _cdp(self, yontem, **parametre):
        self.sira += 1
        no = self.sira
        self.ws.gonder(json.dumps({"id": no, "method": yontem, "params": parametre}))
        while True:  # aradaki olay mesajlarını atla
            m = json.loads(self.ws.al())
            if m.get("id") == no:
                if "error" in m:
                    raise TarayiciHatasi(m["error"].get("message", str(m["error"])))
                return m.get("result", {})

    def _js(self, ifade):
        r = self._cdp("Runtime.evaluate", expression=ifade, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise TarayiciHatasi(r["exceptionDetails"].get("text", "JavaScript hatası"))
        return r.get("result", {}).get("value")

    def _yuklenmesini_bekle(self, en_fazla=8):
        time.sleep(0.8)
        bitis = time.time() + en_fazla
        while time.time() < bitis:
            try:
                if self._js("document.readyState") == "complete":
                    break
            except TarayiciHatasi:
                pass  # gezinme sırasında bağlam değişebilir
            time.sleep(0.4)
        time.sleep(0.5)  # betiklerin içeriği çizmesi için kısa pay

    def _guvenli(self, is_):
        """Chrome kapatıldıysa bir kez yeniden bağlanıp tekrar dener."""
        with self.kilit:
            for deneme in range(2):
                try:
                    self._baglan()
                    return is_()
                except (TarayiciHatasi, OSError) as e:
                    if self.ws:
                        self.ws.kapat()
                    self.ws = None
                    if deneme:
                        raise TarayiciHatasi(str(e)) from e

    # ---------- özet

    def _ozet(self, parca=1, not_=None):
        veri = json.loads(self._js(OZET_JS))
        self.son_ogeler = veri["ogeler"]
        self.son_metin = veri["metin"]
        bas = (parca - 1) * METIN_PARCASI
        metin = veri["metin"][bas:bas + METIN_PARCASI]
        satirlar = [f"Sayfa: {veri['baslik']}", f"Adres: {veri['adres']}"]
        if not_:
            satirlar.append(not_)
        satirlar += ["--- Metin ---", metin or "(metin yok)"]
        if len(veri["metin"]) > bas + METIN_PARCASI:
            satirlar.append(f"…(devamı var: sayfa_oku parca={parca + 1})")
        if parca == 1:
            satirlar.append("--- Tıklanabilir öğeler ---")
            satirlar.extend(veri["ogeler"] or ["(yok)"])
        return "\n".join(satirlar)

    # ---------- işlemler (araçlar)

    def ac(self, adres):
        adres = adres.strip()
        if "://" not in adres and not adres.startswith("about:"):
            adres = "https://" + adres

        def is_():
            self._cdp("Page.navigate", url=adres)
            self._yuklenmesini_bekle()
            return self._ozet()
        return self._guvenli(is_)

    def ara(self, sorgu):
        return self.ac(ARAMA + urllib.parse.quote(sorgu))

    def oku(self, parca=1):
        return self._guvenli(lambda: self._ozet(max(1, int(parca))))

    def tikla(self, no):
        def is_():
            sonuc = self._js(f"""(() => {{
                const el = document.querySelector('[data-robu="{int(no)}"]');
                if (!el) return 'yok';
                if (el.tagName === 'A') el.target = '_self';  // yeni sekme açılmasın
                el.scrollIntoView({{block: 'center'}});
                el.click();
                return 'tamam';
            }})()""")
            if sonuc == "yok":
                return f"[{no}] numaralı öğe yok. Güncel numaralar için sayfa_oku kullan."
            self._yuklenmesini_bekle()
            return self._ozet()
        return self._guvenli(is_)

    def yaz(self, no, metin, gonder=False):
        def is_():
            sonuc = self._js(f"""(() => {{
                const el = document.querySelector('[data-robu="{int(no)}"]');
                if (!el) return 'yok';
                el.scrollIntoView({{block: 'center'}});
                el.focus();
                if ('value' in el) {{ el.value = ''; el.dispatchEvent(new Event('input', {{bubbles: true}})); }}
                return 'tamam';
            }})()""")
            if sonuc == "yok":
                return f"[{no}] numaralı öğe yok. Güncel numaralar için sayfa_oku kullan."
            self._cdp("Input.insertText", text=metin)
            # Arama kutularının çoğu yazarken öneri listesi açar; doğru sonuç çoğu zaman
            # Enter'la değil öneriye tıklayarak gelir. Öneri çıktıysa Enter'a basma.
            time.sleep(1.2)
            aranan = metin.strip().lower()
            oneriler = [o for o in json.loads(self._js(OZET_JS))["ogeler"]
                        if aranan and aranan in o.lower() and "yazı kutusu" not in o]
            if oneriler:
                not_ = ("NOT: Yazınca öneriler çıktı" + (", Enter'a basılmadı" if gonder else "")
                        + ". Doğru öneriye tikla ile tıkla: " + "; ".join(oneriler[:5]))
                return self._ozet(not_=not_)
            if gonder:
                for tur in ("keyDown", "keyUp"):
                    self._cdp("Input.dispatchKeyEvent", type=tur, key="Enter", code="Enter",
                              windowsVirtualKeyCode=13, nativeVirtualKeyCode=13,
                              **({"text": "\r"} if tur == "keyDown" else {}))
                self._yuklenmesini_bekle()
            return self._ozet()
        return self._guvenli(is_)


_tarayici = None


def tarayici():
    """Uygulama genelinde tek Chrome bağlantısı."""
    global _tarayici
    if _tarayici is None:
        _tarayici = Tarayici()
    return _tarayici
