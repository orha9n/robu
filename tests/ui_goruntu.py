"""Arayüzün ekran görüntülerini alır (görsel kontrol için geliştirici aracı).

    python3 tests/ui_goruntu.py [çıktı_klasörü]

Robu'yu ayrı bir uygulama kimliğiyle açar (çalışan Robu'ya dokunmaz), modeli belleğe yüklemez,
sohbet geçmişine yazmaz. Çekirdek olaylarını taklit ederek örnek kartlar çizer ve şu görüntüleri
kaydeder: 1_kartlar.png, 2_arama.png, 3_ayarlar.png. X11 ve xfce4-screenshooter gerekir.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf  # noqa: E402

from robu import arayuz  # noqa: E402

CIKTI = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="robu-ui-")
os.makedirs(CIKTI, exist_ok=True)
arayuz.RobuPenceresi._isit = lambda self, bosalt=None: None   # modeli yükleme
arayuz.RobuPenceresi._kaydet = lambda self, ek=(): None        # gerçek geçmişe yazma


class Deneme(arayuz.RobuUygulamasi):
    def __init__(self):
        arayuz.Gtk.Application.__init__(self, application_id="io.robu.RobuGoruntu",
                                        flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)


def cek(p, ad):
    """Tüm ekranı çekip pencerenin alanını kırpar (odak başka pencerede olabilir)."""
    p.get_window().raise_()
    tam_yol = os.path.join(CIKTI, "tam.png")
    subprocess.run(["xfce4-screenshooter", "-f", "-s", tam_yol], check=True)
    k = p.get_window().get_frame_extents()
    tam = GdkPixbuf.Pixbuf.new_from_file(tam_yol)
    x, y = max(0, k.x), max(0, k.y)
    w, h = min(k.width, tam.get_width() - x), min(k.height, tam.get_height() - y)
    tam.new_subpixbuf(x, y, w, h).savev(os.path.join(CIKTI, ad + ".png"), "png", [], [])
    os.remove(tam_yol)


def soru(p, metin):
    p.yigin.set_visible_child_name("sohbet")
    p.sohbet.pack_start(arayuz.kullanici_balonu(metin), False, False, 0)
    p.balon = arayuz.RobuBalonu()
    p.sohbet.pack_start(p.balon, False, False, 0)
    p.sohbet.show_all()


IST = {"sure": 12, "istem": 1200, "uretilen": 20, "hiz": 7.1, "baglam": 1400,
       "baglam_siniri": 8192, "kirpildi": False}
SAHTE_KAYIT = {"tur": "dosya", "yol": "/olmayan/yol", "cop": None, "aciklama": "örnek"}


def _cagri(ad, arg):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": ad, "arguments": arg}}]}


# Yeniden açılan bir sohbet: biri geri alınabilir, biri daha önce geri alınmış iki işlem
GECMIS = [
    {"role": "user", "content": "eski.txt'yi çöpe at, notlar.txt'ye tarih ekle"},
    _cagri("komut", {"cmd": "gio trash eski.txt"}),
    {"role": "tool", "tool_name": "komut", "content": "(çıktı yok)",
     "robu_geri_al": {"tur": "cop", "ogeler": [["eski.txt", "/olmayan/eski.txt"]],
                      "aciklama": "çöpe atıldı: eski.txt"}},
    _cagri("dosya_yaz", {"yol": "notlar.txt", "metin": "4 Ekim", "ekle": True}),
    {"role": "tool", "tool_name": "dosya_yaz", "content": "Yazıldı: notlar.txt (3 satır).",
     "robu_geri_al": {"tur": "dosya", "yol": "/olmayan/notlar.txt", "cop": None,
                      "aciklama": "x", "geri_alindi": "notlar.txt önceki hâline döndü."}},
    {"role": "assistant", "content": "İkisini de yaptım."},
]


def ayar_menusu(p):
    for w in p.get_titlebar().get_children():
        if isinstance(w, arayuz.Gtk.MenuButton) and not isinstance(w, arayuz.ModelSecici):
            w.set_active(not w.get_active())


def adimlar(app):
    p = app.props.active_window
    p.resize(900, 820)
    p.set_keep_above(True)
    p.present()
    sira = iter([
        lambda: soru(p, "notlar.txt dosyasındaki tarihi 2026 yap"),
        lambda: [p._olay("komut", 1, "Değiştir: notlar.txt\n@@ -1 +1 @@\n-Tarih: 2025\n"
                         "+Tarih: 2026", False, "Sormadan yazılıyor…", "✎  Dosya değiştirme"),
                 p._olay("cikti", 1, "Yazıldı: ~/notlar.txt (1 satır); eski hâli "
                         "çöp kutusunda.", False),
                 p._olay("geri_alinabilir", 1, SAHTE_KAYIT),
                 p._olay("metin", "Tarihi 2026 olarak değiştirdim."),
                 p._olay("adim_bitti", IST), p._olay("bitti")],
        lambda: soru(p, "eski klasörünü sil"),
        lambda: [p._olay("komut", 2, "rm -rf ~/eski", True, False, None),
                 p._olay("cikti", 2, "", True),
                 p._olay("metin", "Tamam, işleme devam etmiyorum."), p._olay("bitti")],
        lambda: cek(p, "1_kartlar"),
        lambda: p.arama.set_text("hava"),
        lambda: cek(p, "2_arama"),
        lambda: (p.arama.set_text(""), ayar_menusu(p)),
        lambda: cek(p, "3_ayarlar"),
        lambda: (ayar_menusu(p), p.yeni_sohbet(), p.yigin.set_visible_child_name("sohbet"),
                 p._gecmisi_ciz(GECMIS)),
        lambda: cek(p, "4_gecmis"),
        lambda: app.quit(),
    ])

    def sonraki():
        try:
            next(sira)()
            return True
        except StopIteration:
            return False
    GLib.timeout_add(1200, sonraki)
    return False


if __name__ == "__main__":
    app = Deneme()
    app.connect("activate", lambda a: GLib.timeout_add(2000, adimlar, a))
    app.run([])
    print(CIKTI)
