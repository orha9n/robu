"""Robu arayüz bileşenleri: sohbet balonları, komut/resim kartları, model seçici, CSS."""
import os
import re
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, GdkPixbuf, Gtk, Pango  # noqa: E402

from .cekirdek import kisa_ad  # noqa: E402

KLASOR = os.path.dirname(os.path.abspath(__file__))

SIMGE = os.path.join(KLASOR, "robu.svg")

# Küçük modeller bazen komutu çalıştırmak yerine metinle izin ister ("Onaylar mısın?").
# Böyle bir cevabın altına hızlı yanıt düğmeleri konur.
# Yalnızca bir işlem için izin isteyen sorular: "onaylıyor musun", "sileyim mi",
# "çalıştırmamı ister misin", "devam edeyim mi". "Tekrar denemek ister misin?" gibi teklifler
# ve seçenek listeleri bunlara girmez (evet/hayır düğmesi orada anlamsız).
ONAY_SORUSU = re.compile(
    r"onayl\w*\s+m[ıiuü]s[ıiuü]n|onay\w*\s+ver\w*\s+m[ıiuü]|izin\s+ver\w*\s+m[ıiuü]|"
    r"\w+(?:ay[ıi]m|ey[ie]m)\s+mi\b|\w+m[ae]m[ıi]\s+ist\w*\s+m[ıi]", re.I)


def onay_sorusu_mu(metin):
    son = metin.strip()[-300:]
    if not son.endswith("?"):
        return False  # soru cevabın sonunda değilse kullanıcıdan karar beklenmiyor
    if re.search(r"^\s*(?:\d+[.)]|[-*•])\s", son, re.M):
        return False  # seçenek listesi
    soru = re.split(r"(?<=[.!?])\s+", son)[-1]
    if re.search(r"\bya\s+da\b|\byoksa\b|\bveya\b", soru, re.I):
        return False  # "… mi? Ya da …?" gibi seçenekli soru
    return bool(ONAY_SORUSU.search(soru))

# Not: .balon-kullanici kuralı bilerek yalnızca doğrudan alt etikete (> label) uygulanır.
# Sağ tık menüsü etikete bağlı açılıp CSS'i miras aldığı için geniş bir kural
# menü yazısını da beyaz yapıyordu (beyaz üstüne beyaz).
CSS = b"""
.robu-pencere { background-color: @theme_bg_color; }
.sohbet { padding: 16px; }
.balon-kullanici {
    background-color: #3fb6b2;
    border-radius: 16px 16px 4px 16px; padding: 8px 12px;
}
.balon-kullanici > label { color: #ffffff; }
.balon-robu {
    background-color: @theme_base_color;
    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 4px 16px 16px 16px; padding: 8px 12px;
}
.komut-kart {
    background-color: alpha(@theme_fg_color, 0.05);
    border-left: 3px solid #3fb6b2; border-radius: 8px; padding: 8px 10px;
}
.komut-kart.tehlikeli { border-left-color: #e5533d; background-color: alpha(#e5533d, 0.07); }
.kod { font-family: monospace; }
.cikti {
    font-family: monospace; font-size: 90%;
    background-color: alpha(@theme_fg_color, 0.06); border-radius: 6px; padding: 6px;
}
.soluk { opacity: 0.6; font-size: 90%; }
.karsilama-baslik { font-size: 22px; font-weight: bold; }
.oneri { border-radius: 16px; padding: 4px 12px; }
.giris {
    background-color: @theme_base_color;
    border: 1px solid alpha(@theme_fg_color, 0.18); border-radius: 14px; padding: 6px 6px 6px 12px;
}
.giris textview, .giris textview text { background-color: transparent; }
.gonder { border-radius: 10px; min-width: 76px; }
.durum { padding: 4px 12px; border-top: 1px solid alpha(@theme_fg_color, 0.1); }
.indirme-gosterge {
    padding: 0 8px; min-height: 0; border-radius: 8px; font-size: 90%;
    background-color: alpha(#3fb6b2, 0.14); color: #2a7f86;
}
.indirme-gosterge:hover { background-color: alpha(#3fb6b2, 0.26); }
.indirme-gosterge.indirme-hata { background-color: alpha(#e0a526, 0.18); color: #9a6a00; }
.nokta-yesil { color: #2fa36b; }
.nokta-kirmizi { color: #e5533d; }
.nokta-sari { color: #e0a526; }
.uyum-rahat { color: #2fa36b; }
.uyum-agir { color: #c98a10; }
.uyum-sigmaz { color: #e5533d; }
.rozet {
    background-color: alpha(#3fb6b2, 0.18); color: #2a7f86;
    border-radius: 8px; padding: 1px 8px; font-size: 85%; font-weight: bold;
}
.rozet-iyi { background-color: alpha(#2fa36b, 0.16); color: #23855a; }
.rozet-uyari { background-color: alpha(#e0a526, 0.18); color: #9a6a00; }
.rozet-bilgi { background-color: alpha(@theme_fg_color, 0.08); color: @theme_fg_color; font-weight: normal; }
.gecmis-panel {
    background-color: alpha(@theme_fg_color, 0.03);
    border-left: 1px solid alpha(@theme_fg_color, 0.12);
}
.gecmis-panel list { background-color: transparent; }
.gecmis-panel row { border-radius: 8px; margin: 1px 6px; }
.gecmis-panel row.etkin { background-color: alpha(#3fb6b2, 0.18); }
.gecmis-baslik { font-weight: bold; }
.grup-baslik { font-size: 85%; font-weight: bold; opacity: 0.55; padding: 10px 14px 4px 14px; }
.bilgi-kart {
    background-color: @theme_base_color; border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 10px; padding: 12px;
}
"""


def md_pango(metin):
    """Küçük modellerin ürettiği basit Markdown'u Pango biçimine çevirir."""
    parcalar = metin.split("```")
    sonuc = []
    for i, p in enumerate(parcalar):
        if i % 2:  # kod bloğu
            if "\n" in p and re.match(r"^[\w+-]*\n", p):
                p = p.split("\n", 1)[1]
            sonuc.append("<tt>" + GLib.markup_escape_text(p.strip("\n")) + "</tt>")
            continue
        satirlar = []
        for satir in p.split("\n"):
            baslik = re.match(r"^\s*#{1,6}\s+(.*)$", satir)
            if baslik:
                satir = "**" + baslik.group(1) + "**"
            satir = re.sub(r"^(\s*)[*-]\s+", r"\1• ", satir)
            satirlar.append(_satir_ici("\n".join([satir])))
        sonuc.append("\n".join(satirlar))
    return "".join(sonuc)


def _satir_ici(satir):
    """`kod` ve **kalın** biçimlendirmesi; kalın metnin içinde kod da olabilir."""
    if satir.count("`") % 2:  # kapanmamış ` (akış sürerken)
        return GLib.markup_escape_text(satir)
    kodlar = []

    def yer_tut(m):
        kodlar.append("<tt>" + GLib.markup_escape_text(m.group(1)) + "</tt>")
        return f"\ue000{len(kodlar) - 1}\ue001"
    metin = GLib.markup_escape_text(re.sub(r"`([^`]*)`", yer_tut, satir))
    metin = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", metin)
    return re.sub("\ue000(\\d+)\ue001", lambda m: kodlar[int(m.group(1))], metin)


def simge(boyut):
    return GdkPixbuf.Pixbuf.new_from_file_at_size(SIMGE, boyut, boyut)


def etiket(metin="", siniflar=(), secilebilir=True, markup=False):
    e = Gtk.Label(xalign=0)
    e.set_line_wrap(True)
    e.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    e.set_max_width_chars(70)
    e.set_selectable(secilebilir)
    e.set_can_focus(False)
    if markup:
        e.set_markup(metin)
    else:
        e.set_text(metin)
    for s in siniflar:
        e.get_style_context().add_class(s)
    return e


class KomutKarti(Gtk.Box):
    def __init__(self, cmd, tehlikeli, otomatik=False, baslik=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.get_style_context().add_class("komut-kart")
        if tehlikeli:
            self.get_style_context().add_class("tehlikeli")
        baslik = baslik or ("⚠  Değişiklik yapan komut" if tehlikeli else "⚙  Komut")
        self.pack_start(etiket(baslik, ("soluk",), False), False, False, 0)
        self.pack_start(etiket(cmd, ("kod",)), False, False, 0)
        self.alt = Gtk.Box(spacing=6)
        self.pack_start(self.alt, False, False, 0)
        self._durum(otomatik if isinstance(otomatik, str) else
                    "Okuma komutu, sormadan çalıştırılıyor…" if otomatik else "Bekliyor…")

    def _temizle(self):
        for c in self.alt.get_children():
            self.alt.remove(c)

    def _durum(self, metin):
        self._temizle()
        self.alt.pack_start(etiket(metin, ("soluk",), False), False, False, 0)
        self.alt.show_all()

    def onay_iste(self, geri):
        self._temizle()
        evet = Gtk.Button(label="Çalıştır")
        evet.get_style_context().add_class("suggested-action")
        hayir = Gtk.Button(label="Reddet")

        def sec(_b, izin):
            self._durum("Çalışıyor…" if izin else "Reddedildi")
            geri(izin)

        evet.connect("clicked", sec, True)
        hayir.connect("clicked", sec, False)
        self.alt.pack_start(evet, False, False, 0)
        self.alt.pack_start(hayir, False, False, 0)
        self.alt.show_all()
        evet.grab_focus()

    def sonuc(self, cikti, reddedildi):
        if reddedildi:
            self._durum("Reddedildi")
            return
        satir = cikti.count("\n") + 1
        self._temizle()
        acilir = Gtk.Expander(label=f"Sayfa özeti ({satir} satır)" if cikti.startswith("Sayfa: ")
                              else f"Çıktı ({satir} satır)")
        if cikti.startswith("Sayfa: "):  # kısa başlık+adres kartın üstünde görünsün
            self.alt.set_orientation(Gtk.Orientation.VERTICAL)
            ilk = cikti.split("\n")[:2]
            self.alt.pack_start(etiket("\n".join(ilk), ("soluk",)), False, False, 0)
        acilir.set_expanded(satir <= 8)
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        kaydir.set_propagate_natural_height(True)
        kaydir.set_max_content_height(260)
        cikti_etiket = etiket(cikti, ("cikti",))
        cikti_etiket.set_line_wrap(False)  # tablolar bozulmasın; yatay kaydırılır
        cikti_etiket.set_max_width_chars(-1)
        kaydir.set_propagate_natural_width(False)
        kaydir.add(cikti_etiket)
        acilir.add(kaydir)
        self.alt.pack_start(acilir, True, True, 0)
        self.alt.show_all()


    def geri_al_ekle(self, geri, yapildi=None):
        """İşlem bitince "Geri al" düğmesi; `geri()` (başarılı mı, mesaj) döndürür.
        `yapildi`: daha önce geri alındıysa düğme yerine gösterilecek sonuç."""
        if yapildi:
            satir = Gtk.Box(halign=Gtk.Align.START)
            satir.pack_start(etiket("↶ " + yapildi, ("soluk",)), False, False, 0)
            self.pack_start(satir, False, False, 0)
            satir.show_all()
            return
        dugme = Gtk.Button(label="↶ Geri al")
        dugme.set_tooltip_text("Bu değişikliği geri alır (dosyanın eski hâli çöp kutusundan "
                               "geri getirilir).")
        satir = Gtk.Box(halign=Gtk.Align.START)  # çıktıyı daraltmasın diye ayrı satırda

        def tikla(_b):
            tamam, mesaj = geri()
            satir.remove(dugme)
            satir.pack_start(etiket(("↶ " if tamam else "⚠ ") + mesaj, ("soluk",)),
                             False, False, 0)
            satir.show_all()
        dugme.connect("clicked", tikla)
        satir.pack_start(dugme, False, False, 0)
        self.pack_start(satir, False, False, 0)
        satir.show_all()


class ResimKarti(Gtk.Box):
    """Modelin baktığı resimler: küçük önizlemeler ve durum."""

    def __init__(self, yollar, baslik=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.get_style_context().add_class("komut-kart")
        baslik = baslik or ("🖼  Resme bakılıyor" if len(yollar) == 1
                            else f"🖼  {len(yollar)} resme bakılıyor")
        self.pack_start(etiket(baslik, ("soluk",), False), False, False, 0)
        akis = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                           column_spacing=8, row_spacing=8, homogeneous=False)
        for yol in yollar:
            kutu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            try:
                kucuk = GdkPixbuf.Pixbuf.new_from_file_at_scale(yol, 150, 100, True)
                kucuk = kucuk.apply_embedded_orientation() or kucuk
                kutu.pack_start(Gtk.Image.new_from_pixbuf(kucuk), False, False, 0)
            except GLib.Error:
                pass
            ad = etiket(os.path.basename(yol), ("kod", "soluk"), False)
            ad.set_tooltip_text(yol)
            kutu.pack_start(ad, False, False, 0)
            akis.add(kutu)
        for cocuk in akis.get_children():
            cocuk.set_can_focus(False)
        self.pack_start(akis, False, False, 0)
        self.durum = etiket("Hazırlanıyor…", ("soluk",), False)
        self.pack_start(self.durum, False, False, 0)

    def sonuc(self, hata):
        self.durum.set_text("⚠ " + hata if hata else "Modele gösterildi")


class RobuBalonu(Gtk.Box):
    """Robu'nun bir cevabı: metin parçaları ve komut kartları sırayla eklenir."""

    def __init__(self, canli=True):
        super().__init__(spacing=8, halign=Gtk.Align.START)
        self.canli = canli  # False: geçmişten yeniden çiziliyor
        resim = Gtk.Image.new_from_pixbuf(simge(30))
        resim.set_valign(Gtk.Align.START)
        self.pack_start(resim, False, False, 0)
        self.govde = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.govde.get_style_context().add_class("balon-robu")
        self.pack_start(self.govde, False, False, 0)
        self.metin = None
        self.dusunce = None
        self.kartlar = {}
        self.son_kart = None
        self.baslangic = time.time()
        self.bekleme = Gtk.Box(spacing=8)
        self.bekleme.pack_start(Gtk.Spinner(active=True), False, False, 0)
        self.bekleme_etiket = etiket("Cevap bekleniyor…", ("soluk",), False)
        self.bekleme.pack_start(self.bekleme_etiket, False, False, 0)
        if canli:
            self.govde.pack_start(self.bekleme, False, False, 0)
            GLib.timeout_add(1000, self._sayac)
        self.istatistik = etiket("", ("soluk",), False)
        self.adimlar = []

    def _sayac(self):
        if not self.bekleme.get_parent():
            return False
        self.bekleme_etiket.set_text(f"Cevap bekleniyor… {time.time() - self.baslangic:.0f} sn")
        return True

    def _bekleme_kaldir(self):
        if self.bekleme.get_parent():
            self.govde.remove(self.bekleme)

    def _bekleme_ekle(self):
        if not self.bekleme.get_parent():
            self.govde.pack_start(self.bekleme, False, False, 0)
            self.bekleme.show_all()

    def dusunce_guncelle(self, metin):
        self._bekleme_kaldir()
        if self.dusunce is None:
            acilir = Gtk.Expander(label="Düşünce")
            self.dusunce = etiket("", ("soluk",))
            acilir.add(self.dusunce)
            self.govde.pack_start(acilir, False, False, 0)
            acilir.show_all()
            self._bekleme_ekle()
        self.dusunce.set_text(metin)

    def metin_guncelle(self, metin):
        self._bekleme_kaldir()
        if self.metin is None:
            self.metin = etiket("")
            self.govde.pack_start(self.metin, False, False, 0)
            self.metin.show()
        self.metin.set_markup(md_pango(metin.strip()))

    def komut_ekle(self, kimlik, cmd, tehlikeli, otomatik=False, baslik=None):
        self._bekleme_kaldir()
        kart = KomutKarti(cmd, tehlikeli, otomatik, baslik)
        self.kartlar[kimlik] = kart
        self.son_kart = kart
        self.govde.pack_start(kart, False, False, 0)
        kart.show_all()
        # sonraki adımın metni yeni bir paragraf olsun
        self.metin = None
        self.dusunce = None

    def resim_ekle(self, kimlik, yollar, baslik=None):
        self._bekleme_kaldir()
        kart = ResimKarti(yollar, baslik)
        self.kartlar[kimlik] = kart
        self.govde.pack_start(kart, False, False, 0)
        kart.show_all()
        self.metin = None
        self.dusunce = None

    def resim_sonuc(self, kimlik, hata):
        kart = self.kartlar.get(kimlik)
        if kart:
            kart.sonuc(hata)
        if self.canli:
            self.baslangic = time.time()
            self._bekleme_ekle()

    def cikti(self, kimlik, cikti, reddedildi):
        kart = self.kartlar.get(kimlik)
        if kart:
            kart.sonuc(cikti, reddedildi)
        if self.canli:
            self.baslangic = time.time()
            self._bekleme_ekle()

    def onay_dugmeleri(self, geri):
        """Metinle sorulan onay için 'Onaylıyorum / Onaylamıyorum' düğmeleri."""
        kutu = Gtk.Box(spacing=6)
        evet = Gtk.Button(label="Onaylıyorum")
        evet.get_style_context().add_class("suggested-action")
        hayir = Gtk.Button(label="Onaylamıyorum")
        evet.connect("clicked", lambda _b: geri(True))
        hayir.connect("clicked", lambda _b: geri(False))
        kutu.pack_start(evet, False, False, 0)
        kutu.pack_start(hayir, False, False, 0)
        self.govde.pack_start(kutu, False, False, 0)
        kutu.show_all()
        return kutu

    def adim(self, ist):
        self.adimlar.append(ist)

    def bitir(self, not_=None):
        self._bekleme_kaldir()
        if not_:
            self.govde.pack_start(etiket(not_, ("soluk",)), False, False, 0)
        if self.adimlar:
            sure = sum(a["sure"] for a in self.adimlar)
            hiz = self.adimlar[-1]["hiz"]
            n = len(self.adimlar)
            self.istatistik.set_text(
                f"{n} adım · {sure:.0f} sn · {hiz:.1f} token/sn" if n > 1
                else f"{sure:.0f} sn · {hiz:.1f} token/sn")
            self.govde.pack_start(self.istatistik, False, False, 0)
        self.govde.show_all()


def kullanici_balonu(metin):
    kutu = Gtk.Box(halign=Gtk.Align.END)
    ic = Gtk.Box()
    ic.get_style_context().add_class("balon-kullanici")
    ic.pack_start(etiket(metin), False, False, 0)
    kutu.pack_start(ic, False, False, 0)
    return kutu


class ModelSecici(Gtk.MenuButton):
    """Başlık çubuğundaki model seçici.

    GTK3 açılır listesi seçili öğeyi düğmenin üstüne hizalar; pencere ekranın
    kenarındayken sığmayıp tek satıra iner. Altına açılan panel bu sorunu yaşamaz.
    """

    def __init__(self, secildi, indir, yonet):
        super().__init__()
        self.secildi = secildi
        self.secili = None
        ic = Gtk.Box(spacing=4)
        self.etiket = Gtk.Label(label="Model yok")
        self.etiket.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.etiket.set_max_width_chars(24)
        ic.pack_start(self.etiket, False, False, 0)
        ic.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON),
                      False, False, 0)
        self.add(ic)

        self.pop = Gtk.Popover()
        kutu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        self.liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.liste.set_activate_on_single_click(True)
        self.liste.connect("row-activated", self._satir)
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        kaydir.set_propagate_natural_height(True)
        kaydir.set_max_content_height(380)
        kaydir.add(self.liste)
        kutu.pack_start(kaydir, True, True, 0)
        kutu.pack_start(Gtk.Separator(), False, False, 2)
        yeni = Gtk.Button(label="＋  Yeni model indir…")
        yeni.set_relief(Gtk.ReliefStyle.NONE)
        yeni.get_child().set_xalign(0)
        yeni.connect("clicked", lambda _b: (self.pop.popdown(), indir()))
        kutu.pack_start(yeni, False, False, 0)
        yon = Gtk.Button(label="⚙  Modelleri yönet…")
        yon.set_relief(Gtk.ReliefStyle.NONE)
        yon.get_child().set_xalign(0)
        yon.connect("clicked", lambda _b: (self.pop.popdown(), yonet()))
        kutu.pack_start(yon, False, False, 0)
        kutu.show_all()
        self.pop.add(kutu)
        self.set_popover(self.pop)

    def doldur(self, modeller, secili):
        for c in self.liste.get_children():
            self.liste.remove(c)
        for m in modeller:
            satir = Gtk.ListBoxRow()
            satir.ad = m["ad"]
            kutu = Gtk.Box(spacing=10, margin=6)
            isaret = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU) \
                if m["ad"] == secili else Gtk.Image()
            isaret.set_size_request(16, -1)
            kutu.pack_start(isaret, False, False, 0)
            dikey = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            ad = Gtk.Label(xalign=0)
            ad.set_markup(f"<b>{GLib.markup_escape_text(kisa_ad(m['ad']))}</b>")
            ad.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            ad.set_max_width_chars(44)
            ad.set_tooltip_text(m["ad"])
            dikey.pack_start(ad, False, False, 0)
            kaynak = ("Hugging Face · " + m["ad"].split("/")[1]) if m["ad"].startswith("hf.co/") \
                else "Ollama"
            yetenek = "⚙ komut çalıştırabilir" if m["araclar"] else "💬 sadece sohbet"
            gorsel = "🖼 görsel" if m.get("gorsel") else ""
            bilgi = [kaynak, f"{m['boyut_gb']:.1f} GB", m["parametre"], yetenek, gorsel]
            alt = Gtk.Label(label="  ·  ".join(x for x in bilgi if x), xalign=0)
            alt.get_style_context().add_class("soluk")
            dikey.pack_start(alt, False, False, 0)
            kutu.pack_start(dikey, True, True, 0)
            satir.add(kutu)
            self.liste.add(satir)
        self.liste.show_all()
        self.secili = secili
        self.etiket.set_text(kisa_ad(secili) if secili else "Model yok")
        self.set_tooltip_text(secili or "Model yok")

    def _satir(self, _liste, satir):
        self.pop.popdown()
        if satir.ad != self.secili:
            self.secildi(satir.ad)
