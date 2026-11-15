"""Hugging Face'ten (veya Ollama kütüphanesinden) model indirme penceresi."""
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import cekirdek, huggingface as hf  # noqa: E402

UYUM_METNI = {
    "rahat": ("✓ belleğe sığar", "uyum-rahat"),
    "agir": ("⚠ belleği zorlar", "uyum-agir"),
    "sigmaz": ("✗ belleğe sığmaz", "uyum-sigmaz"),
}


def _sayi(n):
    if n >= 1e6:
        return f"{n / 1e6:.1f} mn".replace(".", ",")
    if n >= 1e3:
        return f"{n / 1e3:.1f} bin".replace(".", ",")
    return str(n)


def _arka_plan(is_, sonra):
    def calis():
        try:
            sonuc = is_()
        except Exception as e:
            sonuc = e
        GLib.idle_add(sonra, sonuc)
    threading.Thread(target=calis, daemon=True).start()


def _rozet(metin, tur="bilgi"):
    e = Gtk.Label(label=metin, valign=Gtk.Align.CENTER)
    e.get_style_context().add_class("rozet")
    e.get_style_context().add_class("rozet-" + tur)
    return e


def _rozetler(liste):
    kutu = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8,
                       column_spacing=6, row_spacing=6, homogeneous=False)
    for metin, tur in liste:
        kutu.add(_rozet(metin, tur))
    for cocuk in kutu.get_children():  # rozetler odak almasın (vurgulanmasın)
        cocuk.set_can_focus(False)
    return kutu


def _soluk(metin, markup=False):
    e = Gtk.Label(xalign=0)
    e.set_markup(metin) if markup else e.set_text(metin)
    e.get_style_context().add_class("soluk")
    return e


class IndirmePenceresi(Gtk.Window):
    def __init__(self, ana, indirildi):
        super().__init__(title="Model indir", transient_for=ana)
        self.set_default_size(680, 720)
        self.set_icon(ana.get_icon())
        self.ana = ana
        self.indirildi = indirildi  # indirme bitince ana pencereye haber verir
        self.dur = None
        self.inen = None
        self.connect("delete-event", lambda *_: self.hide() or True)

        hb = Gtk.HeaderBar(show_close_button=True, title="Model indir",
                           subtitle="Hugging Face · GGUF")
        self.geri = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        self.geri.connect("clicked", lambda _b: self._sayfa("depolar"))
        hb.pack_start(self.geri)
        self.set_titlebar(hb)
        hb.show_all()  # başlık çubuğu içerikten ayrı gösterilmeli

        kok = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        self.add(kok)

        self.arama = Gtk.SearchEntry(
            placeholder_text="Ara: gemma, qwen, llama…  ya da hf.co/… / gemma3:1b yapıştır")
        self.arama.connect("activate", self._ara)
        kok.pack_start(self.arama, False, False, 0)

        # arama seçenekleri: tür, sıralama, boyut
        secenek = Gtk.Box(spacing=8)
        self.tur = Gtk.ComboBoxText()
        for kimlik, metin in (("hepsi", "Sohbet modelleri"), ("metin", "Sadece metin"),
                              ("gorsel", "Görsel + metin")):
            self.tur.append(kimlik, metin)
        self.tur.set_active_id("hepsi")
        self.sira = Gtk.ComboBoxText()
        for kimlik, metin in (("trend", "Trend"), ("indirme", "En çok indirilen"),
                              ("begeni", "En çok beğenilen")):
            self.sira.append(kimlik, metin)
        self.sira.set_active_id("trend")
        self.sigan = Gtk.CheckButton(label="Sadece bu bilgisayara sığanlar", active=True)
        self.sigan.set_tooltip_text("Q4 sürümü belleğe rahat sığmayan büyük modelleri gizler.")
        for w in (self.tur, self.sira):
            w.connect("changed", self._ara)
            secenek.pack_start(w, False, False, 0)
        self.sigan.connect("toggled", self._ara)
        secenek.pack_start(self.sigan, False, False, 4)
        kok.pack_start(secenek, False, False, 0)

        ram = hf.toplam_ram() / 2**30
        not_ = _soluk(
            f"Bu bilgisayar: {ram:.0f} GB RAM. Dosya ne kadar büyükse cevap o kadar yavaş gelir; "
            "ekran kartı yoksa 1–4B parametreli modeller ve Q4_K_M en iyi dengedir.")
        not_.set_line_wrap(True)
        kok.pack_start(not_, False, False, 0)

        self.yigin = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.depolar, depo_cerceve = self._liste()
        self.dosyalar, dosya_cerceve = self._liste()
        self.yigin.add_named(depo_cerceve, "depolar")
        sayfa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ust = Gtk.Box(spacing=8)
        donus = Gtk.Button(label="← Sonuçlar")
        donus.set_relief(Gtk.ReliefStyle.NONE)
        donus.connect("clicked", lambda _b: self._sayfa("depolar"))
        ust.pack_start(donus, False, False, 0)
        self.depo_baslik = Gtk.Label(xalign=0)
        self.depo_baslik.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        ust.pack_start(self.depo_baslik, True, True, 0)
        self.hf_bag = Gtk.LinkButton(label="Hugging Face'te aç")
        ust.pack_end(self.hf_bag, False, False, 0)
        sayfa.pack_start(ust, False, False, 0)

        # model bilgi kartı: yetenekler, özellikler, açıklama
        self.kart = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.kart.get_style_context().add_class("bilgi-kart")
        sayfa.pack_start(self.kart, False, False, 0)

        surum = Gtk.Label(xalign=0)
        surum.set_markup("<b>Sürümler</b>")
        sayfa.pack_start(surum, False, False, 2)
        sayfa.pack_start(dosya_cerceve, True, True, 0)
        self.yigin.add_named(sayfa, "dosyalar")
        kok.pack_start(self.yigin, True, True, 0)

        self.bilgi = _soluk("")
        self.bilgi.set_line_wrap(True)
        kok.pack_start(self.bilgi, False, False, 0)

        # indirme ilerlemesi
        self.ilerleme_kutu = Gtk.Box(spacing=10)
        dikey = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.ilerleme_etiket = Gtk.Label(xalign=0)
        self.ilerleme_etiket.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.ilerleme = Gtk.ProgressBar(show_text=True)
        dikey.pack_start(self.ilerleme_etiket, False, False, 0)
        dikey.pack_start(self.ilerleme, False, False, 0)
        self.ilerleme_kutu.pack_start(dikey, True, True, 0)
        iptal = Gtk.Button(label="İptal", valign=Gtk.Align.END)
        iptal.connect("clicked", lambda _b: self.dur and self.dur.set())
        self.ilerleme_kutu.pack_start(iptal, False, False, 0)
        kok.pack_start(self.ilerleme_kutu, False, False, 0)

        kok.show_all()
        self.ilerleme_kutu.hide()
        self._sayfa("depolar")
        self._ara(None)  # açılışta popüler GGUF depoları

    # ---------- yardımcılar

    def _liste(self):
        liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        liste.get_style_context().add_class("indirme-liste")
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        kaydir.add(liste)
        cerceve = Gtk.Frame()
        cerceve.add(kaydir)
        return liste, cerceve

    def _temizle(self, liste):
        for c in liste.get_children():
            liste.remove(c)

    def _sayfa(self, ad):
        self.yigin.set_visible_child_name(ad)
        self.geri.set_visible(ad == "dosyalar")

    def _bekliyor(self, liste, metin):
        self._temizle(liste)
        satir = Gtk.Box(spacing=8, margin=12)
        satir.pack_start(Gtk.Spinner(active=True), False, False, 0)
        satir.pack_start(_soluk(metin), False, False, 0)
        liste.add(satir)
        liste.show_all()

    # ---------- arama

    def _ara(self, _w):
        sorgu = self.arama.get_text().strip()
        # doğrudan model adı: hf.co/..., huggingface.co/... ya da ollama adı (gemma3:1b)
        dogrudan = sorgu.replace("https://", "").replace("huggingface.co/", "hf.co/")
        if dogrudan.startswith("hf.co/") or (":" in dogrudan and " " not in dogrudan):
            self.indir(dogrudan)
            return
        if sorgu.count("/") == 1 and " " not in sorgu:  # kullanici/depo
            self._depo_ac(sorgu)
            return
        self._sayfa("depolar")
        self._bekliyor(self.depolar, "Hugging Face'te aranıyor…")
        self._arama_no = getattr(self, "_arama_no", 0) + 1
        no, tur, sira, sigan = (self._arama_no, self.tur.get_active_id(),
                                self.sira.get_active_id(), self.sigan.get_active())
        _arka_plan(lambda: (no, hf.ara(sorgu, tur, sira, sigan)), self._sonuclar)

    def _sonuclar(self, sonuc):
        if not isinstance(sonuc, Exception):
            no, sonuc = sonuc
            if no != self._arama_no:  # daha yeni bir arama başladı; eskisini gösterme
                return False
        self._temizle(self.depolar)
        if isinstance(sonuc, Exception):
            self.depolar.add(_soluk(f"  Hugging Face'e ulaşılamadı: {sonuc}"))
        elif not sonuc:
            self.depolar.add(_soluk("  Sonuç yok. Başka bir kelime dene."))
        for m in sonuc if isinstance(sonuc, list) else []:
            satir = Gtk.Box(spacing=10, margin=8)
            dikey = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            ad = Gtk.Label(xalign=0)
            boyut = f"  <span alpha='60%'>{m['parametre']}</span>" if m["parametre"] else ""
            ad.set_markup(f"<b>{GLib.markup_escape_text(m['depo'])}</b>{boyut}")
            ad.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            dikey.pack_start(ad, False, False, 0)
            alt = Gtk.Box(spacing=8)
            alt.pack_start(_soluk(f"↓ {_sayi(m['indirme'])} indirme  ·  ♥ {_sayi(m['begeni'])}"),
                           False, False, 0)
            for metin, tur in m["yetenekler"]:
                if metin != "Sohbet":
                    alt.pack_start(_rozet(metin, tur), False, False, 0)
            dikey.pack_start(alt, False, False, 0)
            satir.pack_start(dikey, True, True, 0)
            sec = Gtk.Button(label="Sürümler")
            sec.connect("clicked", lambda _b, d=m["depo"]: self._depo_ac(d))
            satir.pack_start(sec, False, False, 0)
            self.depolar.add(satir)
        self.depolar.show_all()
        return False

    # ---------- depo içeriği

    def _depo_ac(self, depo):
        self.depo = depo
        self.depo_baslik.set_markup(f"<b>{GLib.markup_escape_text(depo)}</b>")
        self.hf_bag.set_uri(f"https://huggingface.co/{depo}")
        self._sayfa("dosyalar")
        self._kart_temizle()
        bekle = Gtk.Box(spacing=8)
        bekle.pack_start(Gtk.Spinner(active=True), False, False, 0)
        bekle.pack_start(_soluk("Model bilgisi okunuyor…"), False, False, 0)
        self.kart.pack_start(bekle, False, False, 0)
        self.kart.show_all()
        self._bekliyor(self.dosyalar, "Dosyalar okunuyor…")
        _arka_plan(lambda: hf.dosyalar(depo), self._dosyalar_geldi)
        _arka_plan(lambda: (depo, hf.bilgi(depo)), self._bilgi_geldi)

    def _kart_temizle(self):
        for c in self.kart.get_children():
            self.kart.remove(c)

    def _bilgi_geldi(self, sonuc):
        if isinstance(sonuc, Exception):
            self._kart_temizle()
            self.kart.pack_start(_soluk(f"Model bilgisi alınamadı: {sonuc}"), False, False, 0)
            self.kart.show_all()
            return False
        depo, b = sonuc
        if depo != self.depo:  # kullanıcı bu arada başka depoya geçti
            return False
        self._kart_temizle()
        rozet = list(b["yetenekler"])
        if b["kilitli"]:
            rozet.append(("🔒 Giriş gerekir", "uyari"))
        self.kart.pack_start(_rozetler(rozet), False, False, 0)
        ozellik = [x for x in (
            b["parametre"] and f"{b['parametre']} parametre",
            b["baglam"] and f"{b['baglam']} bağlam",
            b["mimari"],
            b["lisans"] and f"lisans: {b['lisans']}",
            b["guncelleme"] and f"güncelleme: {b['guncelleme']}",
        ) if x]
        if ozellik:
            self.kart.pack_start(_soluk("  ·  ".join(ozellik)), False, False, 0)
        if b["temel"]:
            self.kart.pack_start(_soluk(f"Temel model: {b['temel']}"), False, False, 0)
        if b["aciklama"]:
            acik = Gtk.Label(label=b["aciklama"], xalign=0)
            acik.set_line_wrap(True)
            acik.set_lines(6)
            acik.set_ellipsize(Pango.EllipsizeMode.END)
            acik.set_tooltip_text(b["aciklama"])
            self.kart.pack_start(acik, False, False, 0)
        else:
            self.kart.pack_start(_soluk("Model kartında açıklama bulunamadı."), False, False, 0)
        self.kart.show_all()
        return False

    def _dosyalar_geldi(self, sonuc):
        self._temizle(self.dosyalar)
        if isinstance(sonuc, Exception):
            self.dosyalar.add(_soluk(f"  Okunamadı: {sonuc}"))
            self.dosyalar.show_all()
            return False
        if not sonuc:
            self.dosyalar.add(_soluk("  Bu depoda Ollama'nın indirebileceği GGUF dosyası yok."))
        onerilen = hf.oneri(sonuc)
        # önerilen sürüm en üstte görünsün
        sonuc = sorted(sonuc, key=lambda d: d["etiket"] != onerilen)
        for d in sonuc:
            uyum = hf.uyum(d["boyut"])
            satir = Gtk.Box(spacing=10, margin=8)
            ad = Gtk.Label(xalign=0, width_chars=14)
            ad.set_markup(f"<b>{d['etiket']}</b>")
            satir.pack_start(ad, False, False, 0)
            satir.pack_start(Gtk.Label(label=f"{d['boyut'] / 2**30:.1f} GB", width_chars=8,
                                       xalign=1), False, False, 0)
            metin, sinif = UYUM_METNI[uyum]
            u = Gtk.Label(label=metin, xalign=0)
            u.get_style_context().add_class(sinif)
            satir.pack_start(u, True, True, 0)
            if d["etiket"] == onerilen:
                o = Gtk.Label(label="önerilen", valign=Gtk.Align.CENTER)
                o.get_style_context().add_class("rozet")
                satir.pack_start(o, False, False, 0)
            dugme = Gtk.Button(label="İndir")
            if d["etiket"] == onerilen:
                dugme.get_style_context().add_class("suggested-action")
            dugme.set_sensitive(uyum != "sigmaz")
            dugme.connect("clicked", lambda _b, e=d["etiket"]: self.indir(
                hf.ollama_adi(self.depo, e)))
            satir.pack_end(dugme, False, False, 0)
            self.dosyalar.add(satir)
        self.dosyalar.show_all()
        return False

    # ---------- indirme

    def indir(self, ad):
        if self.dur is not None:
            self.bilgi.set_text("Zaten bir indirme sürüyor; bitmesini bekle ya da iptal et.")
            return
        self.inen = ad
        self.dur = threading.Event()
        self.ilerleme_etiket.set_text(f"İndiriliyor: {ad}")
        self.ilerleme.set_fraction(0)
        self.ilerleme.set_text("başlıyor…")
        self.ilerleme_kutu.show()
        self.bilgi.set_text("Pencereyi kapatabilirsin; indirme arka planda sürer.")
        ollama = cekirdek.Ollama(self.ana.ayar["ollama"])
        dur = self.dur

        def calis():
            try:
                for v in ollama.cek(ad, dur):
                    GLib.idle_add(self._ilerle, v)
                if dur.is_set():
                    GLib.idle_add(self._bitti, None, "İptal edildi. Tekrar başlatırsan "
                                                     "kaldığı yerden sürer.")
                else:
                    GLib.idle_add(self._bitti, ollama.yetenekler(ad), None)
            except Exception as e:
                metin = str(e)
                # HF olmayan/gizli depoda 401 döner, Ollama bunu "realm host" hatasına çevirir
                if "realm host" in metin or "file does not exist" in metin or "401" in metin:
                    metin = ("Model bulunamadı: depo adı ya da sürüm etiketi yanlış, "
                             "veya depo Hugging Face girişi gerektiriyor.")
                GLib.idle_add(self._bitti, None, f"Hata: {metin}")
        threading.Thread(target=calis, daemon=True).start()

    def _ilerle(self, v):
        durum = v.get("status", "")
        toplam, inen = v.get("total"), v.get("completed")
        if toplam and inen is not None:
            self.ilerleme.set_fraction(inen / toplam)
            self.ilerleme.set_text(f"{inen / 1e9:.2f} / {toplam / 1e9:.2f} GB")
            self.ana.indirme_durumu(f"İndiriliyor %{inen * 100 // toplam}: {self.inen}")
        else:
            ceviri = {"pulling manifest": "bilgiler alınıyor…",
                      "verifying sha256 digest": "doğrulanıyor…",
                      "writing manifest": "kaydediliyor…", "success": "tamam"}
            self.ilerleme.set_text(ceviri.get(durum, durum))
        return False

    def _bitti(self, yetenek, hata):
        ad, self.inen, self.dur = self.inen, None, None
        self.ilerleme_kutu.hide()
        if hata:
            self.bilgi.set_text(hata)
            self.ana.indirme_durumu(None)
            return False
        if "tools" in yetenek:
            self.bilgi.set_text(f"✓ {ad} indirildi. Model seçiciden seçebilirsin.")
        else:
            self.bilgi.set_text(f"✓ {ad} indirildi. Bu model komut çalıştırmayı desteklemiyor; "
                                "Robu onunla yalnızca sohbet edebilir.")
        self.indirildi(ad)
        return False
