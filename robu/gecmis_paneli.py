"""Sağdaki sohbet geçmişi paneli: liste, arama, dışa aktarma, kaydetme ve yeniden çizme."""
import datetime
import os
import re
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import cekirdek, dosyalar, gecmis  # noqa: E402
from .cekirdek import kisa_ad  # noqa: E402
from .bilesenler import KomutKarti, RobuBalonu, etiket, kullanici_balonu  # noqa: E402


class GecmisPaneli:
    """RobuPenceresi\'ne karıştırılan (mixin) yöntemler."""

    def _gecmis_paneli(self):
        kutu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        kutu.get_style_context().add_class("gecmis-panel")
        kutu.set_size_request(280, -1)
        ust = Gtk.Box(spacing=6, margin=10, margin_bottom=4)
        b = Gtk.Label(label="Sohbetler", xalign=0)
        b.get_style_context().add_class("gecmis-baslik")
        ust.pack_start(b, True, True, 0)
        yeni = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        yeni.set_relief(Gtk.ReliefStyle.NONE)
        yeni.set_tooltip_text("Yeni sohbet (Ctrl+N)")
        yeni.connect("clicked", lambda _b: self.yeni_sohbet())
        ust.pack_end(yeni, False, False, 0)
        kutu.pack_start(ust, False, False, 0)

        self.arama = Gtk.SearchEntry(placeholder_text="Sohbetlerde ara…",
                                     margin_start=10, margin_end=10, margin_bottom=6)
        self.arama.connect("search-changed", self._arama_degisti)
        kutu.pack_start(self.arama, False, False, 0)
        self.arama_sonucu = None  # None: filtre yok; küme: eşleşen sohbet kimlikleri

        self.gecmis_liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.gecmis_liste.set_filter_func(
            lambda satir: self.arama_sonucu is None or satir.kimlik in self.arama_sonucu)
        self.gecmis_liste.set_activate_on_single_click(True)
        self.gecmis_liste.connect("row-activated", lambda _l, s: self.sohbet_ac(s.kimlik))
        self.gecmis_liste.set_header_func(self._grup_basligi)
        bos = Gtk.Label(label="Henüz kayıtlı sohbet yok.\nİlk sorundan sonra burada görünür.",
                        justify=Gtk.Justification.CENTER, margin=20)
        bos.get_style_context().add_class("soluk")
        bos.show()
        self.gecmis_liste.set_placeholder(bos)
        kaydir = Gtk.ScrolledWindow()
        kaydir.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        kaydir.add(self.gecmis_liste)
        kutu.pack_start(kaydir, True, True, 0)
        return kutu

    def _arama_degisti(self, giris):
        self.arama_sonucu = gecmis.ara(giris.get_text())
        self.gecmis_liste.invalidate_filter()
        self.gecmis_liste.invalidate_headers()

    def _disa_aktar(self, s):
        try:
            kayit = gecmis.yukle(s["id"])
        except (OSError, ValueError) as e:
            self._durum("kirmizi", f"Sohbet okunamadı: {e}")
            return
        pencere = Gtk.FileChooserDialog(title="Sohbeti dışa aktar", transient_for=self,
                                        action=Gtk.FileChooserAction.SAVE)
        pencere.add_buttons("İptal", Gtk.ResponseType.CANCEL, "Kaydet", Gtk.ResponseType.ACCEPT)
        pencere.set_do_overwrite_confirmation(True)
        belge_klasoru = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        pencere.set_current_folder(belge_klasoru or os.path.expanduser("~"))
        ad = re.sub(r'[\\/:*?"<>|]', "", kayit.get("baslik") or "sohbet").strip()[:60] or "sohbet"
        pencere.set_current_name(ad + ".md")
        if pencere.run() == Gtk.ResponseType.ACCEPT:
            yol = pencere.get_filename()
            try:
                with open(yol, "w") as f:
                    f.write(gecmis.markdown(kayit))
                self._durum("yesil", f"Dışa aktarıldı: {yol}")
            except OSError as e:
                self._durum("kirmizi", f"Kaydedilemedi: {e}")
        pencere.destroy()

    @staticmethod
    def _grup(zaman):
        gun = (datetime.date.today() - datetime.date.fromtimestamp(zaman)).days
        if gun <= 0:
            return "Bugün"
        if gun == 1:
            return "Dün"
        if gun < 7:
            return "Bu hafta"
        return "Daha eski"

    def _grup_basligi(self, satir, onceki):
        grup = self._grup(satir.zaman)
        if onceki is not None and self._grup(onceki.zaman) == grup:
            satir.set_header(None)
            return
        e = Gtk.Label(label=grup.upper(), xalign=0)
        e.get_style_context().add_class("grup-baslik")
        satir.set_header(e)

    def _gecmisi_yenile(self):
        for c in self.gecmis_liste.get_children():
            self.gecmis_liste.remove(c)
        for s in gecmis.listele():
            self.gecmis_liste.add(self._gecmis_satiri(s))
        self.gecmis_liste.show_all()
        self._etkin_isaretle()

    def _gecmis_satiri(self, s):
        satir = Gtk.ListBoxRow()
        satir.kimlik, satir.zaman = s["id"], s["guncelleme"]
        kutu = Gtk.Box(spacing=4, margin_start=8, margin_top=6, margin_bottom=6)
        dikey = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        baslik = Gtk.Label(label=s["baslik"], xalign=0)
        baslik.set_ellipsize(Pango.EllipsizeMode.END)
        baslik.set_tooltip_text(s["baslik"])
        dikey.pack_start(baslik, False, False, 0)
        saat = datetime.datetime.fromtimestamp(s["guncelleme"]).strftime("%d.%m %H:%M")
        alt = Gtk.Label(label=f"{saat}  ·  {s['soru']} soru  ·  {kisa_ad(s['model'])}", xalign=0)
        alt.set_ellipsize(Pango.EllipsizeMode.END)
        alt.get_style_context().add_class("soluk")
        dikey.pack_start(alt, False, False, 0)
        kutu.pack_start(dikey, True, True, 0)
        sil = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.MENU)
        sil.set_relief(Gtk.ReliefStyle.NONE)
        sil.set_valign(Gtk.Align.CENTER)
        sil.set_tooltip_text("Bu sohbeti sil")
        sil.connect("clicked", lambda _b: self._sohbet_sil_sor(s))
        kutu.pack_end(sil, False, False, 0)
        aktar = Gtk.Button.new_from_icon_name("document-save-as-symbolic", Gtk.IconSize.MENU)
        aktar.set_relief(Gtk.ReliefStyle.NONE)
        aktar.set_valign(Gtk.Align.CENTER)
        aktar.set_tooltip_text("Markdown dosyası olarak dışa aktar")
        aktar.connect("clicked", lambda _b: self._disa_aktar(s))
        kutu.pack_end(aktar, False, False, 0)
        satir.add(kutu)
        return satir

    def _etkin_isaretle(self):
        etkin = self.sohbet_kayit["id"] if self.sohbet_kayit else None
        for satir in self.gecmis_liste.get_children():
            stil = satir.get_style_context()
            (stil.add_class if satir.kimlik == etkin else stil.remove_class)("etkin")

    def _panel_degisti(self, dugme):
        self.panel.set_reveal_child(dugme.get_active())
        self._ayar_degis("panel", dugme.get_active())

    def _kaydet(self, ek=()):
        mesajlar = self.ajan.gecmis() + list(ek)
        if not any(m.get("role") == "user" for m in mesajlar):
            return
        if self.sohbet_kayit is None:
            ilk = next(m["content"] for m in mesajlar if m.get("role") == "user")
            self.sohbet_kayit = {"id": gecmis.yeni_kimlik(), "baslik": gecmis.baslik_uret(ilk),
                                 "olusturma": time.time()}
        self.sohbet_kayit["model"] = self.ayar.get("model", "")
        self.sohbet_kayit["mesajlar"] = mesajlar
        try:
            gecmis.kaydet(self.sohbet_kayit)
        except OSError as e:
            self._durum("kirmizi", f"Sohbet kaydedilemedi: {e}")
            return
        self._gecmisi_yenile()

    def sohbet_ac(self, kimlik):
        if self.mesgul:
            self._durum("sari", "Robu çalışırken başka sohbete geçilemez; önce durdur.")
            return
        if self.sohbet_kayit and self.sohbet_kayit["id"] == kimlik:
            return
        try:
            kayit = gecmis.yukle(kimlik)
        except (OSError, ValueError) as e:
            self._durum("kirmizi", f"Sohbet açılamadı: {e}")
            return
        self.yeni_sohbet()
        self.sohbet_kayit = kayit
        self.ajan.gecmisi_yukle(kayit.get("mesajlar", []))
        self._gecmisi_ciz(kayit.get("mesajlar", []))
        self._etkin_isaretle()
        self._onay_rozetini_guncelle()

    def _gecmisi_ciz(self, mesajlar):
        """Kayıtlı mesajlardan balonları, komut kartlarını ve çıktıları yeniden kurar."""
        balon, kartlar = None, {}
        for sira, m in enumerate(mesajlar):
            rol = m.get("role")
            if rol == "user" and (m.get("robu_resim") or m.get("robu_hatirlatma")):
                continue  # resim kartta gösterilir; hatırlatma iç mesajdır
            if rol == "user":
                if balon:
                    balon.bitir()
                balon = None
                self.sohbet.pack_start(kullanici_balonu(m["content"]), False, False, 0)
                continue
            if balon is None:
                balon = RobuBalonu(canli=False)
                self.sohbet.pack_start(balon, False, False, 0)
            if rol == "assistant":
                if m.get("content", "").strip():
                    balon.metin_guncelle(m["content"])
                if m.get("robu_uyari"):
                    balon.govde.pack_start(etiket(m["robu_uyari"], ("soluk",)), False, False, 0)
                for c in m.get("tool_calls") or []:
                    fn = c.get("function", {})
                    arg = fn.get("arguments") or {}
                    kimlik = len(kartlar)
                    kartlar[kimlik] = balon
                    if fn.get("name") == "resim_bak":
                        yol = arg.get("yol", "") if isinstance(arg, dict) else str(arg)
                        if yol.strip(" '\"").lower() in cekirdek.EKRAN_ADLARI:
                            # alınan görüntünün yolu ardından gelen resim mesajında
                            sonraki = next((n.get("robu_resim") for n in mesajlar[sira + 1:]
                                            if n.get("robu_resim")), None) or []
                            balon.resim_ekle(kimlik, sonraki, "🖥  Ekran görüntüsü")
                            balon.son_resim = kimlik
                            continue
                        tam = os.path.join(self.ayar["klasor"], os.path.expanduser(yol))
                        balon.resim_ekle(kimlik, cekirdek.resim_yollari(tam)[0] or [tam])
                        balon.son_resim = kimlik
                        continue
                    if fn.get("name") in cekirdek.TARAYICI_ADLARI:
                        aciklama = cekirdek.tarayici_aciklamasi(
                            fn["name"], arg if isinstance(arg, dict) else {})
                        balon.komut_ekle(kimlik, aciklama, False, " ", "🌐  Chrome")
                        balon.son_kimlik = kimlik
                        continue
                    if fn.get("name") == "belge_ara":
                        sorgu = arg.get("sorgu", "") if isinstance(arg, dict) else ""
                        balon.komut_ekle(kimlik, f"Ara: {sorgu}", False, " ", "📚  Belge arama")
                        balon.son_kimlik = kimlik
                        continue
                    if fn.get("name") in dosyalar.ADLAR:
                        baslik = {"dosya_oku": "📄  Dosya okuma", "dosya_yaz": "✎  Dosya yazma",
                                  "dosya_degistir": "✎  Dosya değiştirme"}[fn["name"]]
                        balon.komut_ekle(kimlik, dosyalar.aciklama(
                            fn["name"], arg if isinstance(arg, dict) else {}), False, " ", baslik)
                        balon.son_kimlik = kimlik
                        continue
                    cmd = arg.get("cmd", "") if isinstance(arg, dict) else str(arg)
                    hassas = cekirdek.hassas_mi(cmd)
                    balon.komut_ekle(kimlik, cmd, hassas or cekirdek.tehlikeli_mi(cmd), False,
                                     "⚠  Gizli bilgilere dokunan komut" if hassas else None)
                    balon.son_kimlik = kimlik
            elif rol == "tool" and m.get("tool_name") == "resim_bak":
                kimlik = getattr(balon, "son_resim", None)
                if kimlik is not None:
                    icerik = m.get("content", "")
                    balon.resim_sonuc(kimlik, None if "açıldı;" in icerik else icerik)
                    balon.son_resim = None
            elif rol == "tool":
                kimlik = getattr(balon, "son_kimlik", None)
                if kimlik is None:
                    continue
                icerik = m.get("content", "")
                red = icerik.startswith(("Kullanıcı reddetti", "Kullanıcı bu komutu reddetti",
                                         "Kullanıcı bu işlemi reddetti",
                                         "Kullanıcı görevi durdurdu"))
                balon.cikti(kimlik, icerik, red)
                kayit = m.get("robu_geri_al")
                kart = balon.kartlar.get(kimlik)
                if kayit and isinstance(kart, KomutKarti):
                    kart.geri_al_ekle(lambda k=kayit: self._geri_al(self.ajan, k),
                                      kayit.get("geri_alindi"))
                balon.son_kimlik = None
        if balon:
            balon.bitir()
        if mesajlar:
            self.yigin.set_visible_child_name("sohbet")
        self.sohbet.show_all()

    def _sohbet_sil_sor(self, s):
        etkin = self.sohbet_kayit and self.sohbet_kayit["id"] == s["id"]
        if etkin and self.mesgul:
            self._durum("sari", "Robu bu sohbette çalışırken silinemez; önce durdur.")
            return
        soru = Gtk.MessageDialog(transient_for=self, modal=True,
                                 message_type=Gtk.MessageType.QUESTION,
                                 buttons=Gtk.ButtonsType.NONE, text="Bu sohbet silinsin mi?")
        soru.format_secondary_text(f"“{s['baslik']}” çöp kutusuna taşınır; gerekirse "
                                   "oradan geri getirilebilir.")
        soru.add_button("İptal", Gtk.ResponseType.CANCEL)
        sil = soru.add_button("Sil", Gtk.ResponseType.ACCEPT)
        sil.get_style_context().add_class("destructive-action")
        soru.set_default_response(Gtk.ResponseType.CANCEL)
        cevap = soru.run()
        soru.destroy()
        if cevap != Gtk.ResponseType.ACCEPT:
            return
        try:
            gecmis.sil(s["id"])
        except OSError as e:
            self._durum("kirmizi", f"Sohbet silinemedi: {e}")
            return
        if etkin:
            self.yeni_sohbet()
        self._gecmisi_yenile()
