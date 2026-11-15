"""Kurulu modelleri listeleyip silme penceresi."""
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import cekirdek  # noqa: E402


def _arka_plan(is_, sonra):
    def calis():
        try:
            sonuc = is_()
        except Exception as e:
            sonuc = e
        GLib.idle_add(sonra, sonuc)
    threading.Thread(target=calis, daemon=True).start()


def _soluk(metin):
    e = Gtk.Label(label=metin, xalign=0)
    e.get_style_context().add_class("soluk")
    return e


class ModelYonetimi(Gtk.Window):
    def __init__(self, ana, degisti):
        super().__init__(title="Modelleri yönet", transient_for=ana)
        self.set_default_size(600, 480)
        self.set_icon(ana.get_icon())
        self.ana = ana
        self.degisti = degisti  # model silinince ana pencere listeyi yeniler
        self.connect("delete-event", lambda *_: self.hide() or True)

        self.hb = Gtk.HeaderBar(show_close_button=True, title="Modelleri yönet")
        yenile = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        yenile.set_tooltip_text("Yenile")
        yenile.connect("clicked", lambda _b: self.yenile())
        self.hb.pack_start(yenile)
        self.set_titlebar(self.hb)
        self.hb.show_all()

        kok = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        self.add(kok)
        self.liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        kaydir.add(self.liste)
        cerceve = Gtk.Frame()
        cerceve.add(kaydir)
        kok.pack_start(cerceve, True, True, 0)

        alt = Gtk.Box(spacing=8)
        self.bilgi = _soluk("")
        self.bilgi.set_line_wrap(True)
        alt.pack_start(self.bilgi, True, True, 0)
        indir = Gtk.Button(label="＋ Yeni model indir…")
        indir.connect("clicked", lambda _b: self.ana.indirme_ac())
        alt.pack_end(indir, False, False, 0)
        kok.pack_start(alt, False, False, 0)
        kok.show_all()
        self.yenile()

    def yenile(self):
        for c in self.liste.get_children():
            self.liste.remove(c)
        satir = Gtk.Box(spacing=8, margin=12)
        satir.pack_start(Gtk.Spinner(active=True), False, False, 0)
        satir.pack_start(_soluk("Modeller okunuyor…"), False, False, 0)
        self.liste.add(satir)
        self.liste.show_all()
        ollama = cekirdek.Ollama(self.ana.ayar["ollama"])
        _arka_plan(lambda: (ollama.modeller(), ollama.yuklu()), self._geldi)

    def _geldi(self, sonuc):
        for c in self.liste.get_children():
            self.liste.remove(c)
        if isinstance(sonuc, Exception):
            self.liste.add(_soluk(f"  Ollama'ya ulaşılamadı: {sonuc}"))
            self.liste.show_all()
            return False
        modeller, yuklu = sonuc
        toplam = sum(m["boyut_gb"] for m in modeller)
        self.hb.set_subtitle(f"{len(modeller)} model · diskte {toplam:.1f} GB")
        if not modeller:
            self.liste.add(_soluk("  Kurulu model yok."))
        secili = self.ana.ayar.get("model")
        for m in modeller:
            self.liste.add(self._satir(m, m["ad"] == secili, m["ad"] in yuklu))
        self.liste.show_all()
        return False

    def _satir(self, m, kullanimda, bellekte):
        kutu = Gtk.Box(spacing=10, margin=10)
        dikey = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        ust = Gtk.Box(spacing=8)
        ad = Gtk.Label(xalign=0)
        ad.set_markup(f"<b>{GLib.markup_escape_text(cekirdek.kisa_ad(m['ad']))}</b>")
        ad.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        ad.set_tooltip_text(m["ad"])
        ust.pack_start(ad, False, False, 0)
        for var, metin in ((kullanimda, "kullanımda"), (bellekte, "bellekte")):
            if var:
                r = Gtk.Label(label=metin, valign=Gtk.Align.CENTER)
                r.get_style_context().add_class("rozet")
                ust.pack_start(r, False, False, 0)
        dikey.pack_start(ust, False, False, 0)
        kaynak = ("Hugging Face · " + m["ad"].split("/")[1]) if m["ad"].startswith("hf.co/") \
            else "Ollama"
        yetenek = "⚙ komut çalıştırabilir" if m["araclar"] else "💬 sadece sohbet"
        gorsel = "🖼 görsel" if m.get("gorsel") else ""
        dikey.pack_start(_soluk("  ·  ".join(x for x in (
            kaynak, f"{m['boyut_gb']:.1f} GB", m["parametre"], yetenek, gorsel) if x)),
            False, False, 0)
        kutu.pack_start(dikey, True, True, 0)

        sil = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        sil.set_relief(Gtk.ReliefStyle.NONE)
        sil.set_valign(Gtk.Align.CENTER)
        sil.set_tooltip_text("Modeli sil")
        if kullanimda and self.ana.mesgul:
            sil.set_sensitive(False)
            sil.set_tooltip_text("Robu bu modelle çalışırken silinemez")
        sil.connect("clicked", lambda _b: self._sil_sor(m))
        kutu.pack_end(sil, False, False, 0)
        return kutu

    def _sil_sor(self, m):
        soru = Gtk.MessageDialog(transient_for=self, modal=True,
                                 message_type=Gtk.MessageType.QUESTION,
                                 buttons=Gtk.ButtonsType.NONE,
                                 text=f"{cekirdek.kisa_ad(m['ad'])} silinsin mi?")
        soru.format_secondary_text(
            f"Diskte {m['boyut_gb']:.1f} GB yer açılır. Gerekirse yeniden indirebilirsin.")
        soru.add_button("İptal", Gtk.ResponseType.CANCEL)
        sil = soru.add_button("Sil", Gtk.ResponseType.ACCEPT)
        sil.get_style_context().add_class("destructive-action")
        soru.set_default_response(Gtk.ResponseType.CANCEL)
        cevap = soru.run()
        soru.destroy()
        if cevap != Gtk.ResponseType.ACCEPT:
            return
        self.bilgi.set_text(f"{cekirdek.kisa_ad(m['ad'])} siliniyor…")
        ollama = cekirdek.Ollama(self.ana.ayar["ollama"])
        _arka_plan(lambda: ollama.sil(m["ad"]), lambda s: self._silindi(m, s))

    def _silindi(self, m, sonuc):
        if isinstance(sonuc, Exception):
            self.bilgi.set_text(f"Silinemedi: {sonuc}")
        else:
            self.bilgi.set_text(f"✓ {cekirdek.kisa_ad(m['ad'])} silindi "
                                f"({m['boyut_gb']:.1f} GB yer açıldı).")
            self.degisti()
        self.yenile()
        return False
