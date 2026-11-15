"""Ayarlar menüsü (☰): anahtarlar, klasörler, bağlam, belgeler, kişisel talimatlar."""
import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gio, Gtk, Pango  # noqa: E402

from . import belgeler, cekirdek, ses  # noqa: E402


class AyarPaneli:
    """RobuPenceresi\'ne karıştırılan (mixin) yöntemler."""

    def _ayar_paneli(self, ana):
        pop = Gtk.Popover(relative_to=ana)
        izgara = Gtk.Grid(row_spacing=10, column_spacing=16, margin=14)

        def anahtar(satir, metin, ipucu, alan):
            e = Gtk.Label(label=metin, xalign=0)
            e.set_tooltip_text(ipucu)
            s = Gtk.Switch(active=bool(self.ayar.get(alan, cekirdek.VARSAYILAN_AYARLAR.get(alan))),
                           halign=Gtk.Align.END)
            s.set_tooltip_text(ipucu)
            s.connect("notify::active", lambda w, _p: self._ayar_degis(alan, w.get_active()))
            izgara.attach(e, 0, satir, 1, 1)
            izgara.attach(s, 1, satir, 1, 1)

        anahtar(0, "Okuma komutlarını sormadan çalıştır",
                "ls, df, cat, grep gibi hiçbir şeyi değiştirmeyen komutlar onaysız çalışır. "
                "Dosyaya yazan ya da değiştiren her komut yine sorulur.",
                "okuma_otomatik")
        anahtar(1, "Tüm komutları sormadan çalıştır",
                "Silme/taşıma gibi tehlikeli komutlar dışında her şey onaysız çalışır.",
                "onaysiz")
        anahtar(2, "Chrome'u kullanabilsin",
                "Robu internette arama yapar, sayfa açar, tıklar ve yazar. Robu'ya ait ayrı bir "
                "Chrome profili kullanılır; senin hesaplarına ve şifrelerine erişemez. "
                "Her arama ve sayfa açma öncesinde izin istenir.",
                "tarayici")
        anahtar(3, "Chrome'da tıklama/yazma için onay iste",
                "Açık olursa Robu her tıklama ve yazmadan önce sorar.", "tarayici_onay")
        anahtar(5, "Çalışırken bilgisayar uyumasın",
                "Robu bir görev üzerinde çalışırken (CPU'da dakikalar sürebilir) bilgisayarın "
                "uykuya girmesini ve ekranın kilitlenmesini engeller.", "uyku_engeli")
        anahtar(4, "Düşünme modu",
                "Model cevaptan önce düşünür. Daha isabetli ama küçük modellerde çok daha yavaş.",
                "dusunme")

        izgara.attach(Gtk.Label(label="Çalışma klasörü", xalign=0), 0, 6, 1, 1)
        klasor = Gtk.FileChooserButton(action=Gtk.FileChooserAction.SELECT_FOLDER)
        klasor.set_filename(self.ayar["klasor"])
        klasor.connect("file-set", lambda w: self._ayar_degis("klasor", w.get_filename()))
        izgara.attach(klasor, 1, 6, 1, 1)

        izgara.attach(Gtk.Label(label="Ollama adresi", xalign=0), 0, 7, 1, 1)
        adres = Gtk.Entry(text=self.ayar["ollama"])
        adres.connect("activate", lambda w: (self._ayar_degis("ollama", w.get_text()),
                                             self._modelleri_yenile()))
        izgara.attach(adres, 1, 7, 1, 1)

        e = Gtk.Label(label="Bağlam boyutu", xalign=0)
        e.set_tooltip_text("Modelin aynı anda aklında tutabileceği metin (token). Büyük değer "
                           "uzun sohbetleri ve sayfaları kapsar ama daha çok RAM kullanır; CPU'da "
                           "dolu bir bağlamın baştan işlenmesi dakikalar sürer.")
        izgara.attach(e, 0, 8, 1, 1)
        baglam = Gtk.ComboBoxText(halign=Gtk.Align.END)
        secenekler = [("4096", "4.096"), ("8192", "8.192 (önerilen)"), ("16384", "16.384"),
                      ("32768", "32.768"), ("0", "Ollama varsayılanı")]
        for kimlik, ad in secenekler:
            baglam.append(kimlik, ad)
        baglam.set_active_id(str(self.ayar.get("baglam", 8192)))
        baglam.connect("changed", lambda w: self._baglam_degis(int(w.get_active_id())))
        izgara.attach(baglam, 1, 8, 1, 1)

        e = Gtk.Label(label="Komut zaman aşımı (sn)", xalign=0)
        e.set_tooltip_text("Bir komut bu süreden uzun sürerse sonlandırılır.")
        izgara.attach(e, 0, 9, 1, 1)
        sure = Gtk.SpinButton.new_with_range(10, 3600, 10)
        sure.set_halign(Gtk.Align.END)
        sure.set_value(int(self.ayar.get("komut_suresi", 120)))
        sure.connect("value-changed", lambda w: self._ayar_degis("komut_suresi",
                                                                 w.get_value_as_int()))
        izgara.attach(sure, 1, 9, 1, 1)

        talimat = Gtk.Button(label="Kişisel talimatları düzenle…")
        talimat.set_tooltip_text("Robu'nun her sohbette bilmesini istediğin şeyler (ör. "
                                 "\"cevapların kısa olsun\", \"projelerim ~/Kod'da\"). "
                                 "Yeni sohbette geçerli olur.")
        talimat.connect("clicked", lambda _b: (pop.popdown(), self._talimatlari_ac()))
        izgara.attach(talimat, 0, 10, 2, 1)

        belge = Gtk.Box(spacing=6)
        e = Gtk.Label(label="Belgeler", xalign=0)
        e.set_tooltip_text("Robu belgelerinde (PDF, Word, metin) anlamca arayabilsin diye "
                           "klasörler dizinlenir. Dizin bilgisayarda kalır.")
        belge.pack_start(e, False, False, 0)
        self.belge_durum = Gtk.Label(label=belgeler.aciklama(), xalign=0)
        self.belge_durum.get_style_context().add_class("soluk")
        self.belge_durum.set_ellipsize(Pango.EllipsizeMode.END)
        belge.pack_start(self.belge_durum, True, True, 0)
        klasorler = Gtk.Button(label="Klasörler…")
        klasorler.connect("clicked", lambda _b: (pop.popdown(), self._belge_klasorleri_sec()))
        belge.pack_start(klasorler, False, False, 0)
        self.dizinle_dugme = Gtk.Button(label="Belgeleri dizinle")
        self.dizinle_dugme.connect("clicked", lambda _b: self._dizinle())
        belge.pack_start(self.dizinle_dugme, False, False, 0)
        izgara.attach(belge, 0, 11, 2, 1)

        if ses.hazir_mi():
            anahtar(12, "Konuşma bitince kaydı kendiliğinden durdur",
                    "Mikrofona bir kez bas, konuş; 1,5 saniye sessizlikten sonra kayıt durur ve "
                    "yazıya çevrilir. Kapalıysa bitirmek için tekrar basılır.",
                    "ses_sessizlikte_dur")
            anahtar(13, "Yazıya çevrilen konuşmayı hemen gönder",
                    "Açıksa metin gözden geçirilmeden Robu'ya gönderilir. Kapalıysa giriş "
                    "kutusuna yazılır, sen gönderirsin.", "ses_otomatik_gonder")

        bilgi = Gtk.Label(xalign=0)
        bilgi.set_markup("<small>Model indirme ve silme: model menüsünden.\n"
                         "Klasör ve Chrome değişiklikleri yeni sohbette geçerli olur.</small>")
        bilgi.get_style_context().add_class("soluk")
        izgara.attach(bilgi, 0, 14, 2, 1)
        anahtar(15, "Yanıtları seslendir (EMA Lightning)",
                "Kesinleşmiş Türkçe yanıtı yerel yapay sesle okur. Yeni mesaj, mikrofon "
                "ve Esc sesi keser. Yerel EMA ortamı gereklidir; otomatik indirme yapılmaz.",
                "sesli_yanit")
        izgara.show_all()
        pop.add(izgara)
        return pop

    def _ayar_degis(self, alan, deger):
        self.ayar[alan] = deger
        if alan == "sesli_yanit" and not deger:
            self.sesli_yanit.kapat()
        cekirdek.ayarlari_kaydet(self.ayar)

    def _talimatlari_ac(self):
        try:
            yol = cekirdek.talimat_dosyasini_hazirla()
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(yol).get_uri(), None)
        except (OSError, GLib.Error) as e:
            self._durum("kirmizi", f"Talimat dosyası açılamadı: {e}")
            return
        self._durum("yesil", "Talimatları kaydedince yeni sohbette (Ctrl+N) geçerli olur.")

    def _belge_klasorleri(self):
        return self.ayar.get("belge_klasorleri") or belgeler.varsayilan_klasorler()

    def _belge_klasorleri_sec(self):
        pencere = Gtk.FileChooserDialog(title="Dizinlenecek belge klasörleri", transient_for=self,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        pencere.add_buttons("İptal", Gtk.ResponseType.CANCEL, "Seç", Gtk.ResponseType.ACCEPT)
        pencere.set_select_multiple(True)
        for k in self._belge_klasorleri():
            pencere.select_filename(k)
        if pencere.run() == Gtk.ResponseType.ACCEPT and pencere.get_filenames():
            self._ayar_degis("belge_klasorleri", pencere.get_filenames())
            self._durum("yesil", "Belge klasörleri: " + ", ".join(
                os.path.basename(k) for k in pencere.get_filenames())
                + ". Uygulamak için 'Belgeleri dizinle'ye bas.")
        pencere.destroy()

    def _dizinle(self, sessiz=False):
        """Belgeleri arka planda dizinler; ilerleme durum çubuğunda görünür. `sessiz`
        (otomatik güncelleme): değişiklik yoksa hiçbir şey yazmaz."""
        if getattr(self, "_dizinleniyor", False):
            return
        self._dizinleniyor = True
        self.dizinle_dugme.set_sensitive(False)
        ollama = cekirdek.Ollama(self.ayar["ollama"])
        model = self.ayar.get("belge_modeli") or "embeddinggemma"
        klasorler = self._belge_klasorleri()

        def ilerleme(yapilan, toplam, yol):
            GLib.idle_add(self._durum, "sari",
                          f"Dizinleniyor {yapilan + 1}/{toplam}: {os.path.basename(yol)}")
        self._arka_plan(lambda: belgeler.dizinle(ollama, model, klasorler, ilerleme),
                        lambda sonuc: self._dizinlendi(sonuc, sessiz))

    def _otomatik_dizin(self):
        """Dizin bir kez oluşturulduysa değişen belgeleri kendiliğinden işler (zamanlayıcı)."""
        if self.ayar.get("belge_otomatik", True) and belgeler.dizin_var() and not self.mesgul:
            self._dizinle(sessiz=True)
        return True  # GLib zamanlayıcısı sürsün

    def _dizinlendi(self, sonuc, sessiz=False):
        self._dizinleniyor = False
        self.dizinle_dugme.set_sensitive(True)
        self.belge_durum.set_text(belgeler.aciklama())
        if sessiz and not isinstance(sonuc, Exception) and not (sonuc["islenen"]
                                                                 or sonuc["silinen"]):
            return False  # değişiklik yok: sessiz kal
        if sessiz and not isinstance(sonuc, Exception):
            self._durum("yesil", f"Belgeler güncellendi: {sonuc['islenen']} değişen, "
                                 f"{sonuc['silinen']} silinen dosya.")
            return False
        if isinstance(sonuc, Exception):
            ipucu = f" (model yoksa terminalde: ollama pull {self.ayar.get('belge_modeli')})" \
                if "not found" in str(sonuc) or "404" in str(sonuc) else ""
            self._durum("kirmizi", f"Dizinlenemedi: {sonuc}{ipucu}")
        else:
            self._durum("yesil", f"Dizinlendi: {sonuc['dosya']} dosya, {sonuc['parca']} parça "
                                 f"({sonuc['islenen']} dosya yeniden işlendi). Artık "
                                 "belgelerde arama yapılabilir.")
        return False

    def _baglam_degis(self, deger):
        """Bağlam boyutu değişince Ollama modeli yeniden yükler; bunu şimdi yapalım ki
        ilk soru beklemesin."""
        self._ayar_degis("baglam", deger)
        if not self.mesgul and self.ayar.get("model"):
            self._isit()
