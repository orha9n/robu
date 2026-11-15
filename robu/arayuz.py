"""Robu GTK3 arayüzü."""
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import cekirdek, geri_al, ses, tts  # noqa: E402
from .ayar_paneli import AyarPaneli  # noqa: E402
from .bilesenler import (CSS, SIMGE, KomutKarti, ModelSecici, RobuBalonu,  # noqa: E402
                         kullanici_balonu, onay_sorusu_mu, simge)  # noqa: F401
from .gecmis_paneli import GecmisPaneli  # noqa: E402
from .indirme import IndirmePenceresi  # noqa: E402
from .yonetim import ModelYonetimi  # noqa: E402

ONERILER = [
    "İndirilenler klasöründe ne var?",
    "Diskte ne kadar boş yer var?",
    "Masaüstündeki PDF dosyalarını listele",
    "En çok RAM kullanan 5 programı göster",
]



class RobuPenceresi(GecmisPaneli, AyarPaneli, Gtk.ApplicationWindow):
    def __init__(self, uygulama):
        super().__init__(application=uygulama, title="Robu")
        self.set_default_size(1060, 700)
        self.set_icon_from_file(SIMGE)
        self.get_style_context().add_class("robu-pencere")

        self.ayar = cekirdek.ayarlari_yukle()
        self.sesli_yanit = tts.SesliYanit(
            self.ayar, hata=lambda mesaj: GLib.idle_add(self._durum, "sari", mesaj))
        self._tts_epoch = 0
        self.connect("destroy", lambda _w: self.sesli_yanit.kapat())
        self.ajan = None
        self.uyku_engeli = cekirdek.UykuEngeli()
        self.balon = None
        self.mesgul = False
        self.onay_bekleyen = None
        self.modeller = []
        self.indirme = None
        self.indirme_metni = None
        self.indirme_bitti = False
        self.indirme_zamanlayici = None
        self.yonetim = None
        self.sohbet_kayit = None  # açık sohbetin kaydı (ilk cevaptan sonra oluşur)
        self.onay_kutusu = None   # cevap bekleyen Onaylıyorum/Onaylamıyorum düğmeleri

        self._baslik_cubugu()
        ana = Gtk.Box()
        self.add(ana)
        kok = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ana.pack_start(kok, True, True, 0)
        self.panel = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.panel.add(self._gecmis_paneli())
        self.panel.set_reveal_child(bool(self.ayar.get("panel", True)))
        ana.pack_start(self.panel, False, False, 0)

        self.yigin = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.yigin.add_named(self._karsilama(), "karsilama")
        self.kaydirma = Gtk.ScrolledWindow()
        self.kaydirma.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sohbet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.sohbet.get_style_context().add_class("sohbet")
        self.kaydirma.add(self.sohbet)
        self.kaydirma.get_vadjustment().connect("changed", self._en_alta)
        self.yigin.add_named(self.kaydirma, "sohbet")
        kok.pack_start(self.yigin, True, True, 0)

        kok.pack_start(self._giris_alani(), False, False, 0)
        kok.pack_start(self._durum_cubugu(), False, False, 0)

        self.connect("key-press-event", self._kisayol)
        self.connect("delete-event", self._kapatiliyor)
        self.yeni_sohbet()
        self._gecmisi_yenile()
        self._modelleri_yenile()
        GLib.timeout_add_seconds(5, self._durum_yokla)

    # ---------- düzen

    def _baslik_cubugu(self):
        hb = Gtk.HeaderBar(show_close_button=True)
        hb.set_title("Robu")
        hb.set_subtitle("çevrimdışı küçük asistan")
        self.set_titlebar(hb)

        yeni = Gtk.Button.new_from_icon_name("document-new-symbolic", Gtk.IconSize.BUTTON)
        yeni.set_tooltip_text("Yeni sohbet (Ctrl+N)")
        yeni.connect("clicked", lambda _b: self.yeni_sohbet())
        self.yeni_dugme = yeni
        hb.pack_start(yeni)

        self.panel_dugme = Gtk.ToggleButton(active=bool(self.ayar.get("panel", True)))
        self.panel_dugme.set_image(Gtk.Image.new_from_icon_name(
            "sidebar-show-right-symbolic", Gtk.IconSize.BUTTON))
        self.panel_dugme.set_tooltip_text("Sohbet geçmişi (F9)")
        self.panel_dugme.connect("toggled", self._panel_degisti)
        hb.pack_end(self.panel_dugme)

        ayar = Gtk.MenuButton()
        ayar.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        ayar.set_tooltip_text("Ayarlar")
        ayar.set_popover(self._ayar_paneli(ayar))
        hb.pack_end(ayar)

        indir = Gtk.Button.new_from_icon_name("folder-download-symbolic", Gtk.IconSize.BUTTON)
        indir.set_tooltip_text("Hugging Face'ten model indir")
        indir.connect("clicked", lambda _b: self.indirme_ac())
        hb.pack_end(indir)

        self.model_secici = ModelSecici(self._model_sec, self.indirme_ac, self.yonetim_ac)
        hb.pack_end(self.model_secici)

    def _karsilama(self):
        kutu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        kutu.pack_start(Gtk.Image.new_from_pixbuf(simge(112)), False, False, 0)
        b = Gtk.Label(label="Merhaba, ben Robu!")
        b.get_style_context().add_class("karsilama-baslik")
        kutu.pack_start(b, False, False, 0)
        a = Gtk.Label(label="Bilgisayarındaki küçük işleri senin için yaparım — tamamen çevrimdışı.")
        a.get_style_context().add_class("soluk")
        kutu.pack_start(a, False, False, 6)
        akis = Gtk.FlowBox(max_children_per_line=2, selection_mode=Gtk.SelectionMode.NONE,
                           column_spacing=8, row_spacing=8, homogeneous=True)
        for o in ONERILER:
            d = Gtk.Button(label=o)
            d.get_style_context().add_class("oneri")
            d.connect("clicked", lambda w: self.gonder(w.get_label()))
            akis.add(d)
        kutu.pack_start(akis, False, False, 8)
        return kutu

    def _giris_alani(self):
        dis = Gtk.Box(margin=12, margin_top=6, margin_bottom=8)
        kutu = Gtk.Box(spacing=8)
        kutu.get_style_context().add_class("giris")
        self.giris = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.giris.set_top_margin(6)
        self.giris.set_bottom_margin(6)
        self.giris.connect("key-press-event", self._giris_tus)
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        kaydir.set_propagate_natural_height(True)
        kaydir.set_max_content_height(140)
        kaydir.add(self.giris)
        kutu.pack_start(kaydir, True, True, 0)
        self.kayit = None
        if ses.hazir_mi():  # whisper.cpp + model kuruluysa
            self.mikrofon = Gtk.Button.new_from_icon_name("audio-input-microphone-symbolic",
                                                          Gtk.IconSize.BUTTON)
            self.mikrofon.set_valign(Gtk.Align.END)
            self.mikrofon.set_tooltip_text("Sesle yaz (Ctrl+M): bas, konuş, bitince tekrar bas. "
                                           "Ses çevrimdışı yazıya çevrilir.")
            self.mikrofon.connect("clicked", lambda _b: self._ses_kaydi())
            kutu.pack_start(self.mikrofon, False, False, 0)
        self.gonder_dugme = Gtk.Button(label="Gönder", valign=Gtk.Align.END)
        self.gonder_dugme.get_style_context().add_class("gonder")
        self.gonder_dugme.get_style_context().add_class("suggested-action")
        self.gonder_dugme.connect("clicked", self._gonder_tik)
        kutu.pack_start(self.gonder_dugme, False, False, 0)
        dis.pack_start(kutu, True, True, 0)
        return dis

    def _ses_kaydi(self):
        """Mikrofon düğmesi: kaydı başlatır; ikinci basışta durdurup yazıya çevirir."""
        if self.ajan.olcum:
            self.ajan.olcum("audio_input_accepted")
        self._tts_epoch = self.sesli_yanit.yeni_istek()
        if not hasattr(self, "mikrofon"):
            return
        stil = self.mikrofon.get_style_context()
        if self.kayit is None:
            otomatik = self.ayar.get("ses_sessizlikte_dur", True)
            kayit = ses.Kayit(sessizlikte=(lambda: GLib.idle_add(self._ses_sessizlik, kayit))
                              if otomatik else None)
            self.kayit = kayit
            try:
                self.kayit.baslat()
            except (OSError, RuntimeError) as e:
                self.kayit = None
                self._durum("kirmizi", f"Mikrofon açılamadı: {e}")
                return
            stil.add_class("destructive-action")
            self._durum("kirmizi", "● Dinliyorum… konuşman bitince kendiliğinden durur."
                        if otomatik else "● Kaydediliyor… bitirmek için mikrofon düğmesine bas.")
            return
        kayit, self.kayit = self.kayit, None
        stil.remove_class("destructive-action")
        wav = kayit.bitir()
        if not wav:
            self._durum("sari", kayit.hata or "Ses kaydedilemedi.")
            return
        self.mikrofon.set_sensitive(False)
        self._durum("sari", "Ses yazıya çevriliyor…")

        def is_():
            try:
                return ses.yaziya_cevir(wav)
            finally:
                kayit.temizle()
        self._arka_plan(is_, self._ses_cevrildi)

    def _ses_sessizlik(self, kayit):
        """Kayıt iş parçacığı konuşmanın bittiğini bildirdi: ikinci basış gibi durdur."""
        if self.kayit is kayit:
            self._ses_kaydi()
        return False

    def _ses_cevrildi(self, sonuc):
        self.mikrofon.set_sensitive(True)
        if isinstance(sonuc, Exception):
            self._durum("kirmizi", f"Yazıya çevrilemedi: {sonuc}")
        elif not sonuc:
            self._durum("sari", "Konuşma anlaşılamadı.")
        else:
            if self.ajan.olcum:
                self.ajan.olcum("stt_finalized")
            tampon = self.giris.get_buffer()
            mevcut = tampon.get_text(tampon.get_start_iter(), tampon.get_end_iter(), False)
            tampon.set_text((mevcut.rstrip() + " " if mevcut.strip() else "") + sonuc)
            self.giris.grab_focus()
            self._durum_yokla()
            if self.ayar.get("ses_otomatik_gonder") and not self.mesgul:
                self._gonder_tik(None)
        return False

    def _durum_cubugu(self):
        kutu = Gtk.Box(spacing=8)
        kutu.get_style_context().add_class("durum")
        self.nokta = Gtk.Label(label="●")
        self.durum_etiket = Gtk.Label(label="Ollama'ya bağlanıyor…", xalign=0)
        self.durum_etiket.set_ellipsize(Pango.EllipsizeMode.END)
        self.isinma = Gtk.Spinner()
        self.hiz_etiket = Gtk.Label(xalign=1)
        for e in (self.durum_etiket, self.hiz_etiket):
            e.get_style_context().add_class("soluk")
        kutu.pack_start(self.nokta, False, False, 0)
        kutu.pack_start(self.durum_etiket, True, True, 0)
        kutu.pack_start(self.isinma, False, False, 0)
        kutu.pack_end(self.hiz_etiket, False, False, 0)
        # Arka plandaki model indirmesi: bağlam/hız yazısından ayrı, tıklayınca pencereyi açar.
        self.indirme_dugme = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self.indirme_dugme.get_style_context().add_class("indirme-gosterge")
        self.indirme_etiket = Gtk.Label()
        self.indirme_etiket.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.indirme_etiket.set_max_width_chars(40)
        self.indirme_dugme.add(self.indirme_etiket)
        self.indirme_dugme.set_tooltip_text("İndirme penceresini aç")
        self.indirme_dugme.connect("clicked", lambda _b: self.indirme_ac())
        self.indirme_dugme.set_no_show_all(True)
        self.indirme_etiket.show()
        kutu.pack_end(self.indirme_dugme, False, False, 0)
        self.onay_rozeti = Gtk.Label(label="⚠ Komutlar onaysız · arama/sayfa açma izinli")
        self.onay_rozeti.get_style_context().add_class("rozet")
        self.onay_rozeti.get_style_context().add_class("rozet-uyari")
        self.onay_rozeti.set_tooltip_text("Robu bu sohbette her komutu ve Chrome işlemini "
                                          "sormadan yapar. Geri almak için yaz: "
                                          "“bu sohbette onay iste”")
        self.onay_rozeti.set_no_show_all(True)
        kutu.pack_end(self.onay_rozeti, False, False, 0)
        return kutu

    def _onay_rozetini_guncelle(self):
        self.onay_rozeti.set_visible(self.ajan.onaysiz_sohbet())

    # ---------- olaylar

    def _kisayol(self, _w, olay):
        ctrl = olay.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and olay.keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self.yeni_sohbet()
            return True
        if ctrl and olay.keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self._ses_kaydi()
            return True
        if olay.keyval == Gdk.KEY_F9:
            self.panel_dugme.set_active(not self.panel_dugme.get_active())
            return True
        if olay.keyval == Gdk.KEY_Escape:
            self.durdur()
            return True
        return False

    def _kapatiliyor(self, _w, _olay):
        """Robu çalışırken pencere kapatılırsa önce sor, sonra durdurup kaydet."""
        if not self.mesgul:
            return False
        soru = Gtk.MessageDialog(transient_for=self, modal=True,
                                 message_type=Gtk.MessageType.QUESTION,
                                 buttons=Gtk.ButtonsType.NONE, text="Robu şu an çalışıyor")
        soru.format_secondary_text("Durdurup kapatılsın mı? Çalışan komut sonlandırılır, "
                                   "o ana kadar yapılanlar sohbet geçmişine kaydedilir.")
        soru.add_button("Vazgeç", Gtk.ResponseType.CANCEL)
        kapat = soru.add_button("Durdur ve kapat", Gtk.ResponseType.ACCEPT)
        kapat.get_style_context().add_class("destructive-action")
        cevap = soru.run()
        soru.destroy()
        if cevap != Gtk.ResponseType.ACCEPT:
            return True
        self.durdur()
        bitis = time.time() + 5

        def bekle():  # "durduruldu" olayı işlenip geçmiş kaydedilince kapat
            if self.mesgul and time.time() < bitis:
                return True
            self.destroy()
            return False
        GLib.timeout_add(100, bekle)
        return True

    def _giris_tus(self, _w, olay):
        if olay.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and \
                not olay.state & Gdk.ModifierType.SHIFT_MASK:
            self._gonder_tik(None)
            return True
        return False

    def _gonder_tik(self, _b):
        if self.mesgul:
            self.durdur()
            return
        tampon = self.giris.get_buffer()
        metin = tampon.get_text(tampon.get_start_iter(), tampon.get_end_iter(), False).strip()
        if metin:
            tampon.set_text("")
            self.gonder(metin)

    def _en_alta(self, adj):
        adj.set_value(adj.get_upper() - adj.get_page_size())

    # ---------- sohbet

    def yeni_sohbet(self):
        if self.mesgul:
            return
        self._tts_epoch = self.sesli_yanit.yeni_istek()
        for c in self.sohbet.get_children():
            self.sohbet.remove(c)
        self.ajan = cekirdek.Ajan(self.ayar, self._olay_kopru, self._onay_iste)
        self.ajan.arac_destegi(self._arac_var(), self._gorsel_var())
        self.sohbet_kayit = None
        self._etkin_isaretle()
        self._onay_rozetini_guncelle()
        self.yigin.set_visible_child_name("karsilama")
        self.giris.grab_focus()

    def gonder(self, metin):
        if self.mesgul:
            return
        self._paint_trace_started = False
        self.sesli_yanit.olcum = self.ajan.olcum
        if self.ajan.olcum:
            self.ajan.olcum("ui_input_accepted")
        self._tts_epoch = self.sesli_yanit.yeni_istek()
        if cekirdek.onay_kestirmesi(metin) is not None and cekirdek.yalniz_kestirme_mi(metin):
            self._yerel(metin, self.ajan.kestirme)
            return
        if cekirdek.ret_mi(metin):  # "hayır", "vazgeç"… model çağrılmaz
            self._yerel(metin, self.ajan.ret)
            return
        if not self.ayar.get("model"):
            self._durum("kirmizi", "Model yok. Terminalde: ollama pull gemma3:1b")
            return
        self._onay_kutusunu_kaldir()  # yazarak cevap verildiyse düğmeler kalkar
        self.yigin.set_visible_child_name("sohbet")
        self.sohbet.pack_start(kullanici_balonu(metin), False, False, 0)
        self.balon = RobuBalonu()
        self.sohbet.pack_start(self.balon, False, False, 0)
        self.sohbet.show_all()
        self._mesgul(True)
        # sohbet cevap bitmeden de geçmiş panelinde görünsün
        self._kaydet(ek=[{"role": "user", "content": metin}])
        threading.Thread(target=self.ajan.calistir, args=(metin,), daemon=True).start()

    def _yerel(self, metin, cevapla):
        """Kestirme ve ret mesajları modeli beklemeden anında cevaplanır."""
        self._onay_kutusunu_kaldir()
        self.yigin.set_visible_child_name("sohbet")
        self.sohbet.pack_start(kullanici_balonu(metin), False, False, 0)
        balon = RobuBalonu(canli=False)
        cevap = cevapla(metin)
        balon.metin_guncelle(cevap)
        self.sesli_yanit.soyle(cevap, self._tts_epoch)
        balon.bitir()
        self.sohbet.pack_start(balon, False, False, 0)
        self.sohbet.show_all()
        self._kaydet()
        self._onay_rozetini_guncelle()

    def _hizli_onay(self, izin):
        self.gonder("Onaylıyorum, devam et." if izin else "Onaylamıyorum.")

    def _onay_kutusunu_kaldir(self):
        if self.onay_kutusu and self.onay_kutusu.get_parent():
            self.onay_kutusu.get_parent().remove(self.onay_kutusu)
        self.onay_kutusu = None

    def durdur(self):
        """Acil durdurma: komutu öldürür, modeli keser, bekleyen onayı reddeder."""
        self._tts_epoch = self.sesli_yanit.yeni_istek()
        if not self.ajan or not self.mesgul:
            return
        self.gonder_dugme.set_label("Durduruluyor…")
        self.gonder_dugme.set_sensitive(False)
        self.ajan.durdur()
        if self.onay_bekleyen:
            olay, kutu = self.onay_bekleyen
            kutu["izin"] = False
            olay.set()

    def _mesgul(self, deger):
        self.mesgul = deger
        if deger and self.ayar.get("uyku_engeli", True):
            self.uyku_engeli.baslat()
        else:
            self.uyku_engeli.bitir()
        stil = self.gonder_dugme.get_style_context()
        self.gonder_dugme.set_sensitive(True)
        if deger:
            self.gonder_dugme.set_label("Durdur")
            stil.remove_class("suggested-action")
            stil.add_class("destructive-action")
        else:
            self.gonder_dugme.set_label("Gönder")
            stil.remove_class("destructive-action")
            stil.add_class("suggested-action")
        self.yeni_dugme.set_sensitive(not deger)
        self.model_secici.set_sensitive(not deger)

    # Çekirdek başka iş parçacığında çalışır; arayüz değişiklikleri ana döngüye aktarılır.
    def _olay_kopru(self, tur, *veri):
        GLib.idle_add(self._olay, tur, *veri)

    def _olay(self, tur, *veri):
        b = self.balon
        if tur == "basladi":  # mesaj kestirme içeriyorsa ("…, bu sohbette onay isteme")
            self._onay_rozetini_guncelle()
        elif tur == "dusunce":
            b.dusunce_guncelle(veri[0])
        elif tur == "metin":
            b.metin_guncelle(veri[0])
            olcum = self.ajan.olcum
            if olcum and veri[0].strip():
                olcum("text_applied")
                if not getattr(self, "_paint_trace_started", False):
                    self._paint_trace_started = True
                    epoch, handler = self._tts_epoch, []

                    def painted(widget, _cr):
                        widget.disconnect(handler[0])
                        if epoch == self._tts_epoch:
                            olcum("first_text_painted")
                        return False

                    handler.append(b.metin.connect_after("draw", painted))
        elif tur == "komut":
            b.komut_ekle(*veri)  # kimlik, cmd, tehlikeli, otomatik, baslik
        elif tur == "cikti":
            b.cikti(*veri)
        elif tur == "geri_alinabilir":
            kimlik, kayit = veri
            kart = b.kartlar.get(kimlik)
            if isinstance(kart, KomutKarti):
                ajan = self.ajan  # düğmeye sonra basılsa da not bu sohbete gitsin
                kart.geri_al_ekle(lambda: self._geri_al(ajan, kayit))
        elif tur == "tarayici":
            kimlik, aciklama, uyari = veri
            if uyari:  # yerel bilgi internete gidebilir; onay istenecek
                b.komut_ekle(kimlik, aciklama, True, "Bekliyor…", "⚠  " + uyari)
            else:
                bekliyor = aciklama.startswith(("Ara:", "Aç:"))
                b.komut_ekle(kimlik, aciklama, False,
                             "İnternet için izin bekliyor…" if bekliyor else "Chrome'da yapılıyor…",
                             "🌐  Chrome")
        elif tur == "resim":
            b.resim_ekle(*veri)
        elif tur == "resim_sonuc":
            b.resim_sonuc(*veri)
        elif tur == "adim_bitti":
            b.adim(veri[0])
            ist = veri[0]
            doluluk = 100 * ist["baglam"] / ist["baglam_siniri"]
            self.hiz_etiket.set_text(
                f"bağlam %{doluluk:.0f} · {ist['hiz']:.1f} token/sn"
                + (" · eski mesajlar kısaltıldı" if ist["kirpildi"] else ""))
            self.hiz_etiket.set_tooltip_text(
                f"Modele giden istem ≈{ist['baglam']} / {ist['baglam_siniri']} token. %85'i "
                "aşınca eski araç çıktıları kısaltılır, gerekirse en eski mesajlar modele "
                "gönderilmez (sohbet kaydında tam kalır).")
        elif tur == "uyari":
            self._durum("sari", veri[0])
        elif tur == "bitti":
            son = self.ajan.mesajlar[-1].get("content", "")
            # Yalnızca izin/tool adımları ve cevap temizliği tamamlanınca konuş.
            self.sesli_yanit.soyle(son, self._tts_epoch)
            self._bildir("Robu işi bitirdi", son[:120] or "Görev tamamlandı.")
            b.bitir(self.ajan.mesajlar[-1].get("robu_uyari"))
            self._mesgul(False)
            self._kaydet()
            son = self.ajan.mesajlar[-1]
            if son.get("role") == "assistant" and onay_sorusu_mu(son.get("content", "")):
                self.onay_kutusu = b.onay_dugmeleri(self._hizli_onay)
        elif tur == "durduruldu":
            b.bitir("Durduruldu.")
            self._mesgul(False)
            self._kaydet()
        elif tur == "hata":
            self._bildir("Robu: hata", veri[0][:120])
            b.bitir("⚠ " + veri[0])
            self._mesgul(False)
            self._kaydet()
        return False

    def _geri_al(self, ajan, kayit):
        try:
            mesaj = geri_al.geri_al(kayit)
        except (geri_al.GeriAlinamaz, OSError) as e:
            return False, str(e)
        ajan.not_ekle(f"Kullanıcı şu işlemi geri aldı: {kayit['aciklama']}. Sonuç: {mesaj}")
        kayit["geri_alindi"] = mesaj  # sohbet yeniden açılınca düğme yerine bu yazar
        if ajan is self.ajan and not self.mesgul:
            self._kaydet()
        return True, mesaj

    def _bildir(self, baslik, govde):
        """Pencere öndeyken değilse masaüstü bildirimi (görevler CPU'da dakikalar sürebilir)."""
        if self.is_active():
            return
        bildirim = Gio.Notification.new(baslik)
        bildirim.set_body(govde)
        bildirim.set_priority(Gio.NotificationPriority.NORMAL)
        self.get_application().send_notification("robu", bildirim)

    def _onay_iste(self, cmd):
        olay, kutu = threading.Event(), {"izin": False}
        self.onay_bekleyen = (olay, kutu)

        def goster():
            self._bildir("Robu onay bekliyor", cmd.split("\n")[0][:120])
            kart = self.balon.son_kart if self.balon else None
            if kart is None:
                olay.set()
                return False

            def karar(izin):
                kutu["izin"] = izin
                olay.set()
            kart.onay_iste(karar)
            return False

        GLib.idle_add(goster)
        olay.wait()
        self.onay_bekleyen = None
        return kutu["izin"]

    # ---------- Ollama durumu ve modeller

    def _arka_plan(self, is_, sonra):
        def calis():
            try:
                sonuc = is_()
            except Exception as e:
                sonuc = e
            GLib.idle_add(sonra, sonuc)
        threading.Thread(target=calis, daemon=True).start()

    def _durum(self, renk, metin):
        stil = self.nokta.get_style_context()
        for r in ("yesil", "kirmizi", "sari"):
            stil.remove_class("nokta-" + r)
        stil.add_class("nokta-" + renk)
        self.durum_etiket.set_text(metin)

    def _modelleri_yenile(self):
        ollama = cekirdek.Ollama(self.ayar["ollama"])
        self._arka_plan(ollama.modeller, self._modeller_geldi)

    def _modeller_geldi(self, sonuc):
        if isinstance(sonuc, Exception):
            self._durum("kirmizi", "Ollama çalışmıyor. Terminalde: systemctl start ollama")
            return False
        self.modeller = sonuc
        if not sonuc:
            self.model_secici.doldur([], None)
            self._durum("kirmizi", "Hiç model yok. Yukarıdaki menüden bir model indir.")
            return False
        adlar = [m["ad"] for m in sonuc]
        secili = self.ayar.get("model") if self.ayar.get("model") in adlar else adlar[0]
        ilk = self.model_secici.secili is None
        self.model_secici.doldur(sonuc, secili)
        if ilk or secili != self.ayar.get("model"):
            self._model_sec(secili)  # liste yenilenince boşuna yeniden ısıtma
        return False

    def _model_sec(self, ad):
        onceki = self.ayar.get("model")
        if ad != onceki:
            self._ayar_degis("model", ad)
        self.model_secici.doldur(self.modeller, ad)
        self.ajan.arac_destegi(self._arac_var(), self._gorsel_var())
        self._isit(bosalt=onceki if onceki and onceki != ad else None)

    def _gorsel_var(self):
        return any(m["ad"] == self.ayar.get("model") and m.get("gorsel") for m in self.modeller)

    def _arac_var(self):
        for m in self.modeller:
            if m["ad"] == self.ayar.get("model"):
                return m["araclar"]
        return True

    # ---------- model yönetimi

    def yonetim_ac(self):
        if self.yonetim is None:
            self.yonetim = ModelYonetimi(self, self._modelleri_yenile)
        else:
            self.yonetim.yenile()
        self.yonetim.present()

    # ---------- model indirme

    def indirme_ac(self):
        if self.indirme is None:
            self.indirme = IndirmePenceresi(self, self._indirildi)
        if self.indirme_bitti:  # sonuç görüldü; sürmeyen indirmenin göstergesi kalkar
            self.indirme_durumu(None)
        self.indirme.present()

    def _indirildi(self, ad):
        self.indirme_durumu(f"✓ {cekirdek.kisa_ad(ad)} indirildi", bitti=True)
        self._modelleri_yenile()

    def indirme_durumu(self, metin, bitti=False):
        """İndirme penceresi kapalıyken de ilerleme durum çubuğunda görünsün.
        bitti: indirme sona erdi (başarı/hata); başarı birkaç saniye sonra kendiliğinden kalkar,
        hata tıklanıp görülene kadar kalır."""
        self.indirme_metni, self.indirme_bitti = metin, bitti
        if self.indirme_zamanlayici:
            GLib.source_remove(self.indirme_zamanlayici)
            self.indirme_zamanlayici = None
        self.indirme_etiket.set_text(metin or "")
        stil = self.indirme_dugme.get_style_context()
        (stil.add_class if metin and metin.startswith("⚠") else stil.remove_class)("indirme-hata")
        self.indirme_dugme.set_visible(bool(metin))
        if metin and bitti and metin.startswith("✓"):
            def kaldir():
                self.indirme_zamanlayici = None
                self.indirme_durumu(None)
                return False
            self.indirme_zamanlayici = GLib.timeout_add_seconds(8, kaldir)

    def _isit(self, bosalt=None):
        """Seçili modeli belleğe yükler. Küçük RAM'de iki model birden sığmayıp
        Ollama'yı çökertebileceği için önce eski model boşaltılır."""
        self._durum("sari", f"{self.ayar['model']} belleğe yükleniyor…")
        self.isinma.start()
        ollama = cekirdek.Ollama(self.ayar["ollama"])
        ajan = self.ajan

        def is_():
            if bosalt:
                try:
                    ollama.bosalt(bosalt)
                except Exception:
                    pass
            ajan.isit()
        self._arka_plan(is_, self._isindi)

    def _isindi(self, sonuc):
        self.isinma.stop()
        if isinstance(sonuc, Exception):
            self._durum("kirmizi", f"Model yüklenemedi: {sonuc}")
        else:
            self._durum_yokla()
            if not getattr(self, "_dizin_zamanlayici", None):  # yalnızca ilk ısınmada kur
                GLib.timeout_add_seconds(15, lambda: self._otomatik_dizin() and False)
                self._dizin_zamanlayici = GLib.timeout_add_seconds(1800, self._otomatik_dizin)
        return False

    def _durum_yokla(self):
        if self.isinma.get_property("active"):
            return True
        ollama = cekirdek.Ollama(self.ayar["ollama"])
        self._arka_plan(lambda: (ollama.surum(), ollama.yuklu()), self._durum_geldi)
        return True

    def _durum_geldi(self, sonuc):
        if isinstance(sonuc, Exception):
            self._durum("kirmizi", "Ollama'ya ulaşılamıyor")
            return False
        surum, yuklu = sonuc
        if not self._arac_var():
            surum += " · sadece sohbet (model komut desteklemiyor)"
        m = yuklu.get(self.ayar.get("model"))
        if m:
            yer = "GPU" if m["gpu"] else "CPU"
            self._durum("yesil", f"Hazır · {self.ayar['model']} bellekte "
                                 f"({m['ram_gb']:.1f} GB, {yer}) · Ollama {surum}")
        else:
            self._durum("sari", f"{self.ayar.get('model')} uykuda; ilk soruda yüklenecek · "
                                f"Ollama {surum}")
        return False


class RobuUygulamasi(Gtk.Application):
    """Tek örnek çalışır. `robu --durdur` çalışan Robu'ya acil durdurma gönderir;
    böylece Chrome gibi başka bir pencere öndeyken de klavye kısayoluyla durdurulabilir."""

    def __init__(self):
        super().__init__(application_id="io.robu.Robu",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_command_line(self, komut_satiri):
        if "--durdur" in komut_satiri.get_arguments()[1:]:
            pencere = self.props.active_window
            if pencere is not None:
                pencere.durdur()
            return 0
        self.activate()
        return 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        saglayici = Gtk.CssProvider()
        saglayici.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), saglayici, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        pencere = self.props.active_window or RobuPenceresi(self)
        pencere.show_all()
        pencere.present()


def main():
    GLib.set_prgname("robu")
    GLib.set_application_name("Robu")
    return RobuUygulamasi().run(sys.argv)
