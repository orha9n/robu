# Robu

<p align="center"><img src="robu/robu.svg" width="128" alt="Robu simgesi"></p>

**Robu**, Linux masaüstünde çalışan, tamamen yerel (çevrimdışı) bir yapay zekâ asistanıdır.
[Ollama](https://ollama.com) üzerinde çalışan **küçük dil modelleriyle** günlük bilgisayar işlerini
yapar: dosya ve klasör işleri, sistem/terminal yardımı, PDF ve tablo okuma, resimlere bakma,
belgelerde arama ve Chrome'da internet işleri.

Hedef: ekran kartı olmayan sıradan bir dizüstü bilgisayarda bile **küçük modellerle kullanılabilir**
bir deneyim. Sohbetlerin, dosyaların ve resimlerin bilgisayardan çıkmaz.

- Arayüz: GTK 3 (Linux Mint, Ubuntu; XFCE / Cinnamon / GNOME)
- Dil: Python 3, **yalnızca standart kütüphane** + sistemde hazır gelen PyGObject (pip gerekmez)
- Lisans: [GPL-3.0](LICENSE)

---

## İçindekiler

1. [Kurulum](#kurulum)
2. [Kullanım](#kullanım)
3. [Robu neler yapabilir? (kapasite)](#robu-neler-yapabilir-kapasite)
4. [Modelin kullandığı araçlar](#modelin-kullandığı-araçlar)
5. [Güvenlik ve onay sistemi](#güvenlik-ve-onay-sistemi)
6. [Acil durdurma](#acil-durdurma)
7. [Arayüz](#arayüz)
8. [Model yönetimi ve Hugging Face](#model-yönetimi-ve-hugging-face)
9. [Ayarlar](#ayarlar)
10. [Dosya konumları](#dosya-konumları)
11. [Proje yapısı](#proje-yapısı)
12. [Bilinen sınırlar](#bilinen-sınırlar)
13. [Sorun giderme](#sorun-giderme)
14. [Lisans](#lisans)

---

## Kurulum

### Gereksinimler

| Bileşen | Not |
|---|---|
| Linux (Debian/Ubuntu tabanlı) | Linux Mint 22 (XFCE) üzerinde geliştirildi ve test edildi |
| Python 3.10+, GTK 3 (PyGObject) | Mint/Ubuntu'da hazır gelir |
| [Ollama](https://ollama.com) | Yerel model sunucusu; `kur.sh` kurabilir |
| Bellek | En az 8 GB RAM; 6 GB'lık önerilen model için 12 GB+ rahat çalışır |
| Disk | Model için ~7 GB, isteğe bağlı özellikler için +1 GB |
| İsteğe bağlı | `pdftotext`, `libreoffice`, Google Chrome / Chromium, ekran görüntüsü aracı |

### 1. Depoyu indir

```bash
git clone https://github.com/orha9n/robu.git
cd robu
```

### 2. Önce denetle (hiçbir şey kurmaz)

```bash
./kur.sh --kontrol
```

Eksik olan her şey listelenir ve nasıl kurulacağı yazılır.

### 3. Kur

```bash
./kur.sh
```

Betik her adımda sorar (`--evet` ile sormadan ilerler):

1. **Sistem paketleri**: eksik olanlar tek bir `sudo apt install` komutunda kurulur.
2. **Ollama**: kurulu değilse ollama.com'un resmî betiğiyle kurulur.
3. **Sohbet modeli**: hiç model yoksa `gemma4:e4b` (~6,6 GB, araç ve görsel destekli) indirilir.
4. **Belge araması** (isteğe bağlı): `embeddinggemma` (~620 MB).
5. **Sesli giriş** (isteğe bağlı): whisper.cpp kullanıcı klasörüne derlenir (3–5 dk) ve Türkçe
   için `small-q5_1` modeli (~190 MB) indirilir. `cmake` yoksa sudo gerektirmeden indirilir.
6. **Menü kısayolu**: *Uygulamalar → Geliştirme → Robu*.
7. **Birim testleri** çalıştırılır.

`sudo` yalnızca apt paketleri ve Ollama kurulumu için istenir; geri kalan her şey `~/.local`
altına kurulur.

Elle kurmak istersen:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 libglib2.0-bin curl poppler-utils
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e4b
ollama pull embeddinggemma        # isteğe bağlı: belge araması
```

Daha zayıf bir bilgisayarda daha küçük bir model seçebilirsin (ör. `gemma4:e2b`); modeli
uygulama içinden de değiştirebilir ya da Hugging Face'ten indirebilirsin.

### 4. Çalıştır

Menüden **Robu**'yu aç ya da:

```bash
python3 -m robu
```

### İsteğe bağlı: Türkçe sesli giriş için Vosk

whisper.cpp yeterlidir; Türkçede daha hızlı tanıma için Vosk da eklenebilir:

```bash
python3 -m venv ~/.local/share/robu/ses-venv
~/.local/share/robu/ses-venv/bin/pip install vosk
cd ~/.local/share/robu
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-tr-0.3.zip
unzip vosk-model-small-tr-0.3.zip && rm vosk-model-small-tr-0.3.zip
```

### İsteğe bağlı: Sesli yanıt (EMA Lightning)

Cevapları yerel yapay sesle okumak için (PyTorch dahil ~2 GB):

```bash
python3 -m venv ~/.local/share/robu/ema-venv
~/.local/share/robu/ema-venv/bin/pip install ema-lightning==1.0.1
# Modeli bir kez indir (sonra Robu çevrimdışı çalışır):
~/.local/share/robu/ema-venv/bin/python -c "from ema_lightning import EMA; EMA(device='cpu')"
```

Ardından ☰ → **Yanıtları seslendir** seçeneğini aç. Ses çalmak için `paplay` gerekir
(`pulseaudio-utils`).

### Güncelleme ve kaldırma

```bash
git pull                     # güncelle
./kur.sh --kontrol           # yeni bağımlılık var mı?
```

Kaldırmak için depo klasörünü ve şunları sil:
`~/.local/share/applications/robu.desktop`, `~/.config/robu`, `~/.local/share/robu`, `~/.cache/robu`.
Modeller Ollama'da kalır (`ollama rm <model>`).

---

## Kullanım

Robu tek örnek çalışır; ikinci kez açmak mevcut pencereyi öne getirir.

```bash
python3 -m robu            # pencereyi aç
python3 -m robu --durdur   # çalışan Robu'nun işini anında durdur (klavye kısayoluna bağlanabilir)
```

Örnek istekler: *"Masaüstümde ne var?"*, *"İndirilenler'deki PDF'leri bir klasöre topla"*,
*"Diskim neden doldu?"*, *"Ekranımda ne var?"*, *"Kiramı ayın kaçında ödüyorum?"* (belgelerde arama).

---

## Robu neler yapabilir? (kapasite)

### 💻 Bilgisayarda iş yapma
- Kabuk (bash) komutu çalıştırarak dosya/klasör listeleme, arama, taşıma, yeniden adlandırma,
  disk/RAM/işlemci durumu, süreç listesi vb.
- **Okuma komutları otomatik** çalışır (`ls`, `df`, `du`, `cat`, `grep`, `find`, `ps` …);
  değişiklik yapan her komut onaya düşer (ayrıntı: [Güvenlik](#güvenlik-ve-onay-sistemi)).
- Silme işlemleri için modele `gio trash` (çöp kutusu) kullanması söylenir; `sudo` kullanmaz.
- Türkçe klasör adlarını doğru yola çevirir (İndirilenler → `~/Downloads`, Masaüstü → `~/Desktop` …);
  eşleme sistemin `~/.config/user-dirs.dirs` dosyasından okunur.

### 📝 Dosya okuma ve yazma
- **`dosya_oku`**: metin dosyasını okur; uzun dosyalar sayfa sayfa (`satir=`) okunur. İkili dosyada
  PDF/Excel dönüştürmeyi önerir.
- **`dosya_yaz`**: dosya oluşturur, üstüne yazar ya da sonuna ekler (`ekle=true`).
- **`dosya_degistir`**: dosyadaki tek bir metin parçasını değiştirir. Küçük bir düzeltme için
  bütün dosyayı yeniden yazdırmaktan çok daha hızlıdır (CPU'da cevap üretimi ~6–11 token/sn).
  Metin bulunamazsa ya da birden çok yerde geçerse model uyarılır, dosyaya dokunulmaz.
- Onay kartında **fark** (`-eski +yeni`) ya da yeni dosyanın içeriği gösterilir.
- Üstüne yazmadan önce **eski dosya çöpe taşınır**; her değişiklik çöp kutusundan geri alınabilir.
- Küçük modeller bash ile dosya yazarken tırnak/kaçış hataları yaptığı için bu araçlar eklendi.

### ↶ Geri alma
Robu'nun yaptığı bazı değişikliklerin kartında, işlem bitince **↶ Geri al** düğmesi çıkar:
- `dosya_yaz` / `dosya_degistir`: dosya önceki hâline döner (eski hâli çöp kutusundan geri gelir;
  Robu'nun oluşturduğu yeni dosya çöpe taşınır). Yeni hâl de çöpe gider, yani geri alma da geri alınabilir.
- `gio trash …`: çöpe atılan dosyalar eski yerlerine döner.
- Basit `mv kaynak hedef`: dosya eski yerine taşınır.

Hedefte o arada başka bir dosya oluşmuşsa üstüne yazılmaz, geri alma yapılmaz. Joker (`*.txt`),
zincir (`a && b`) ya da seçenekli komutlar geri alınamaz. Geri alma, bir sonraki mesajda modele
bildirilir (dosyayı hâlâ yazılmış sanmasın). Çöp kutusu boşaltıldıysa geri alma yapılamaz.
Geri alma kayıtları sohbetle saklanır: sohbet yeniden açıldığında da düğme çıkar; geri alınmış
işlemde düğme yerine sonucu yazar. Bir işlem iki kez geri alınamaz (önce eski hâlin çöpte olduğu
denetlenir, dosyaya ancak sonra dokunulur).

### 🧾 Kişisel talimatlar
☰ menüsü → **Kişisel talimatları düzenle…** `~/.config/robu/talimatlar.md` dosyasını açar
(yoksa açıklamalı bir şablonla oluşturur). Yazdıkların her sohbette sistem istemine eklenir:
*"Cevapların çok kısa olsun"*, *"Projelerim ~/Kod'da"* gibi. `<!-- … -->` yorumları gönderilmez;
en fazla 1.500 karakter alınır (CPU'da her kelime istem süresini uzatır). Yeni sohbette geçerli olur.

### 📚 Belgelerde arama (yerel, anlamsal)
- ☰ menüsü → **Belgeler: Klasörler… / Belgeleri dizinle**. Varsayılan klasörler: Belgeler ve
  Masaüstü. `.txt .md .csv .pdf .docx .odt .rtf .html` dosyaları parçalara bölünür ve Ollama'daki
  çok dilli **`embeddinggemma`** modeliyle vektöre çevrilir (bir kez: `ollama pull embeddinggemma`).
- Dizin `~/.local/share/robu/dizin.json` dosyasındadır; bilgisayardan çıkmaz. Yeniden dizinleme
  artımlıdır: yalnızca değişen dosyalar işlenir, silinenler çıkarılır.
- Dizin bir kez oluşturulduysa Robu açılışta ve 30 dakikada bir (boştayken) değişen belgeleri
  kendiliğinden işler; değişiklik yoksa hiçbir şey yazmaz ve embedding modelini yüklemez
  (`belge_otomatik`, ayar dosyasından kapatılabilir).
- Dizin varken model **`belge_ara(sorgu)`** aracını alır: *"Kiramı ayın kaçında ödüyorum?"* →
  `kira.txt` bulunur, cevap: *ayın 5'inde, 12.500 TL* (test edildi). Kelime değil anlam eşleşir.
- Gizli dosyalar (`.env`, anahtarlar, tarayıcı profilleri…) ve gizli klasörler dizine alınmaz.
  Arama okuma sayılır; sonuçlar sızıntı denetiminde yerel veri kabul edilir.

### 🎤 Sesli giriş (çevrimdışı, deneysel)
Giriş kutusunun yanındaki mikrofon düğmesi (ya da **Ctrl+M**): bas ve konuş; konuşman bitince
(1,5 sn sessizlik) kayıt kendiliğinden durur. Ortam gürültüsü kaydın ilk yarım saniyesinden ölçülür.
Varsayılan ses kaynağı hoparlörün monitor kanalıysa gerçek mikrofon seçilir. Beş saniye
boyunca konuşma algılanmazsa kayıt durur. Düşük sesli kayıtlar yalnızca konuşma eşiğini
aşmadıkları için elenmez; sessiz sinyal, kısa kayıt ve aygıt hataları ayrı bildirilir.
Ses sistemi mikrofonun etkin girişini kullanılamıyor gösteriyorsa kayıt başlatılmaz;
mikrofon bağlantısı ve sistemin Ses → Giriş ayarı kontrol edilmelidir. Tamamen sessiz
WAV dosyaları yazıya çevirme modeline gönderilmez.
Ayarlardan: kendiliğinden durmayı kapatma (o zaman tekrar basılır) ve çevrilen metni hemen gönderme. Ses
`arecord` ile kaydedilir, **whisper.cpp** ile bilgisayarda yazıya çevrilip kutuya eklenir
(otomatik gönderilmez). Düğme yalnızca `~/.local/share/robu/whisper.cpp/build/bin/whisper-cli`
ve `~/.local/share/robu/whisper-modelleri/ggml-*.bin` varsa görünür (varsayılan model:
`small-q5_1`, ~5 sn'de 4 sn'lik konuşma). Ses dosyası çevrildikten sonra silinir.
Türkçe Vosk modeli (`vosk-model-small-tr-0.3`) ve `~/.local/share/robu/ses-venv`
ortamı kuruluysa Türkçe tanımada öncelikle Vosk kullanılır.

### 🔊 Sesli yanıt (EMA Lightning)
☰ → **Yanıtları seslendir (EMA Lightning)**: kesinleşmiş Türkçe cevabı yerel yapay sesle okur.
Yerel EMA ortamı `~/.local/share/robu/ema-venv/bin/python` üzerinden çalışır; ana GTK sürecine
PyTorch yüklenmez, çalışma sırasında model indirilmez veya metin/ses dışarı gönderilmez.
Yeni mesaj, mikrofon, yeni sohbet, **Esc** ve pencereyi kapatma sesi keser.
Araç çağrıları, onay bekleyen işlemler, düşünme alanı ve kod seslendirilmez.

Uyumlu akış, EMA `say()` ile aynı dört saniyelik pencere sınırlarını kullanır; kısa cevaplarda
cümle hazır olunca başlar. `ema_akis=false` tamponlu `say()` yoluna döner; `sesli_yanit=false`
sesi kapatır. Varsayılan olarak ses kapalıdır.

### 📄 Belgeler
- **PDF**: `pdftotext -layout dosya.pdf -` ile metnini okur, özetler, içinden bilgi çıkarır.
- **Excel / Word**: `libreoffice --headless --convert-to csv|pdf …` ile dönüştürüp okur.
- Uzun komut çıktıları modele en fazla 3.000 karakter olarak gider (ayarlanabilir).

### 🖼 Resimleri görme (görsel destekli modellerde)
- Model `vision` yeteneğine sahipse (ör. `gemma4:e4b`) **`resim_bak`** aracı açılır.
- Tek bir resme ya da **bir klasörün tamamına** (en fazla 6 resim, tek seferde) bakabilir:
  *"İndirilenler'deki resimlerden hangisinde kuş var?"* → `resim3.jpg`.
- Resimler gönderilmeden önce en uzun kenarı 1024 piksele küçültülür (EXIF yönü düzeltilir);
  resim bilgisayardan çıkmaz.
- **Ekran görüntüsü**: *"Ekranımda ne var?"*, *"Bu hata mesajı ne diyor?"* → model `resim_bak`
  aracına `yol="ekran"` verir; Robu tüm ekranın görüntüsünü alıp (`xfce4-screenshooter`, yoksa
  `gnome-screenshot`/`scrot`/`grim`…) modele gösterir. Yazılar okunabilsin diye 1280 piksele
  küçültülür. Görüntüler `~/.cache/robu/ekran/` altında saklanır (son 20). Okuma sayılır:
  varsayılan otomatik, internet içeriği okunduktan sonra onaya düşer. Robu penceresi de görüntüde
  yer alır.
- Sohbette küçük önizlemeleriyle bir kart gösterilir. Geçmiş dosyasına resim verisi yazılmaz,
  yalnızca dosya yolu saklanır.

### 🌐 Chrome'u kullanma (internet işleri)
- **Önce kendi bilgisi**: Genel bilgi sorularını (*"Fotosentez nedir?"*) model kendi bilgisiyle
  cevaplar; Chrome'u yalnızca güncel ya da emin olmadığı bilgi (haber, fiyat, son sürüm…)
  için açar. Böylece CPU'da 1–2 dakikalık gereksiz tarayıcı adımları olmaz.
- **Arama** (DuckDuckGo), **adres açma**, **sayfa okuma**, **tıklama**, **yazı kutusuna yazma / Enter**.
- **İnternet için izin**: Her arama ve adres açma öncesinde onay kartı gösterilir.
  İzin verilmeden Chrome başlatılmaz ve işlem yapılmaz; reddetmek görevi bitirir.
  Genel onaysız ayarları ve sohbet kestirmesi bu izni atlamaz.
- Her işlemden sonra model sayfanın kısa bir özetini görür: başlık, adres, ana metin ve
  **numaralı tıklanabilir öğeler** (`[4] bağlantı: Ankara, TR`). Küçük modeller sayfayı
  numaralarla yönetebilir.
- **Akıllı yazma**: Yazdıktan sonra arama kutusu öneri listesi açtıysa Enter'a basılmaz; model
  doğru öneriye tıklamaya yönlendirilir (otomatik tamamlamalı sitelerde başarıyı büyük ölçüde artırır).
- Sayfa özetlerinden menüler, seçim listeleri, alt bilgiler ve "İçeriğe geç" gibi atlama
  bağlantıları ayıklanır; aynı adrese giden bağlantılar bir kez listelenir.
- Robu'ya ait **ayrı bir Chrome profili** kullanılır: kişisel hesaplarına, şifrelerine, kayıtlı
  kartlarına ve geçmişine erişemez. Chrome penceresi görünür kalır; ne yaptığını izleyebilirsin.
- Örnek görevler (test edildi):
  - *"Linux Mint'in en son sürümü hangisi? İnternetten bak."* → arar, okur: **22.3**
  - *"meteomate.com'a gir, Ankara için anlık sıcaklığı söyle"* → siteyi açar, şehri yazar,
    öneriye tıklar: **14°C, az bulutlu**

### 💬 Sohbet
- **Yanıltıcı başarı uyarısı**: Turdaki son işlem hata verdiyse (çıkış kodu, "bulunamadı",
  "yapılamadı"…) ama model "taşındı / yapıldı" gibi başarı bildirirse cevabın altına
  *"⚠ Son işlem hata verdi; cevabı kontrol et."* uyarısı eklenir.
- **Öneri listesi yok**: Küçük modeller talimata rağmen cevabın sonuna "Başka bir şey ister misin?
  Öneriler: …" ekleyebiliyor; Robu bu teklif cümlelerini ve önündeki teklif cümlesiyle gelen seçenek
  listelerini cevap bitince siler (asıl cevaptaki listelere dokunmaz).
- Türkçe, kısa ve net cevaplar; basit Markdown (kalın, `kod`, kod blokları, listeler) düzgün gösterilir.
- **Sohbet geçmişi** kalıcıdır; sağ paneldeki listeden eski sohbetler açılıp kaldığı yerden sürdürülür.
- Model bir işlem için metinle izin isterse ("Sileyim mi?", "Onaylıyor musun?", "Devam edeyim
  mi?") cevabın altında **Onaylıyorum / Onaylamıyorum** düğmeleri çıkar. "Tekrar denemek ister
  misin? Ya da …" gibi teklifler ve seçenek listeleri düğme getirmez.
- **Reddetmek görevi bitirir.** Onay kartında *Reddet*, *Onaylamıyorum* düğmesi ya da yalnızca
  "hayır / istemiyorum / vazgeç / iptal" yazmak modeli hiç çağırmadan *"Tamam, işleme devam
  etmiyorum."* cevabını verir; alternatif önerilmez, ısrar edilmez.
- Araç desteği olmayan modellerle **sadece sohbet** modunda çalışır (komut yerine, kullanıcının
  çalıştırması için komut önerir).

---

## Modelin kullandığı araçlar

| Araç | Ne yapar | Ne zaman verilir | Onay |
|---|---|---|---|
| `komut(cmd)` | bash komutu çalıştırır, çıktısını döndürür | Model araç destekliyse | Okuma komutları otomatik; diğerleri onaylı |
| `dosya_oku(yol, satir)` | Metin dosyasını okur (sayfalı) | Model araç destekliyse | Okuma komutları gibi (varsayılan: otomatik) |
| `dosya_yaz(yol, metin, ekle)` | Dosya yazar/oluşturur/sonuna ekler | 〃 | Onaylı (fark gösterilir); eski hâli çöpe |
| `dosya_degistir(yol, eski, yeni)` | Tek bir metin parçasını değiştirir | 〃 | Onaylı (fark gösterilir); eski hâli çöpe |
| `belge_ara(sorgu)` | Belgelerde anlamsal arama | Belgeler dizinlendiyse | Okuma gibi (varsayılan: otomatik) |
| `resim_bak(yol)` | Resim(ler)i modele gösterir; yol bir klasör ya da `ekran` (ekran görüntüsü) olabilir | Model görsel destekliyse | Gerekmez (salt okunur) |
| `web_ara(sorgu)` | DuckDuckGo'da arar | Chrome ayarı açıksa | Her zaman izin ister |
| `sayfa_ac(adres)` | Bir web adresini açar | 〃 | Her zaman izin ister |
| `sayfa_oku(parca)` | Uzun sayfanın devamını okur (parça 2, 3…) | 〃 | Gerekmez |
| `tikla(no)` | Numaralı öğeye tıklar | 〃 | Varsayılan: gerekmez (ayarla açılabilir) |
| `yaz(no, metin, gonder)` | Kutuya yazar, istenirse Enter | 〃 | Varsayılan: gerekmez (ayarla açılabilir) |

Robu, modelin yeteneklerini Ollama'dan okur (`/api/show` → `tools`, `vision`) ve yalnızca
modelin destekleyebildiği araçları gönderir.

---

## Güvenlik ve onay sistemi

Robu, bilgisayarında komut çalıştırabildiği için katmanlı bir onay sistemi kullanır:

1. **Okuma komutları** (varsayılan: otomatik) — Komut, bash'e yakın biçimde sözcüklere ve
   işleçlere ayrılır (tırnaklar, kaçışlar, satır sonları bash gibi yorumlanır). Zincirdeki her komut
   bir izin listesinde olmalı (`ls`, `cat`, `df`, `du`, `grep`, `find`, `ps`, `free`,
   `pdftotext … -`, `gio list` vb.) ve aralarında yalnızca `|`, `||`, `&&`, `;` bulunmalı.
   Şunlardan biri varsa **onay istenir**: dosyaya yönlendirme (`>`; `2>/dev/null` ve `2>&1` hariç),
   alt komut (`$(…)`, ters tırnak), arka plan (`&`), alt kabuk, süslü parantez açılımı,
   `./ls` gibi sistem klasörü dışındaki programlar, yazan ya da program çalıştıran ekler
   (`find -delete/-exec/-fprint…`, `sort -o/--compress-program`, `rg --pre`, `exiftool -w` …;
   kısaltılmış `--out=` ve birleşik `-ro` biçimleri dahil), bitmeyen `tail -f` ya da listede
   olmayan herhangi bir komut. Şüphe durumunda her zaman onay istenir.
2. **Diğer komutlar** — Sohbette "⚙ Komut" kartı olarak gösterilir: **Çalıştır / Reddet**.
3. **Tehlikeli komutlar** — `rm`, `mv`, `sudo`, `dd`, `mkfs`, `shred`, `chmod -R`, `kill`,
   `find -delete`, `gio remove`, `git clean`, dosyanın üstüne yazan `>` ve `tee`, yorumlayıcılar
   (`sh`, `python3 -c` …) vb. Komut adına bakılır; `xargs rm`, `timeout 5 rm`, `$(rm …)`,
   `find -exec rm` ve `/bin/rm` gibi biçimler de yakalanır. **Kırmızı kenarlı** kartla gösterilir
   ve "Tüm komutları sormadan çalıştır" ayarı açık olsa bile **her zaman** onay ister.

Kurallar `tests/test_onay.py` ile sınanır: `python3 -m unittest discover tests`

Gerçek modelle davranış testi (Robu kapalıyken): `python3 tests/davranis.py [model]` (11 görev),
`--ret` (gereksiz ret oranı), `--tarayici` (Chrome görevleri; yerel deneme sitesi + internet).
4. **Chrome** — Arama ve adres açma her zaman izin ister. Ayrı profil sayesinde kişisel
   hesaplara erişim yoktur. Tıklama/yazma için onay
   isteğe bağlıdır (varsayılan kapalı).
5. **İnternetten gelen gizli talimatlara karşı (prompt injection)** — Bir web sayfası, modele
   "şu dosyayı oku, içeriğini şu adrese gönder" gibi gizli talimatlar yazabilir. Robu bunu üç
   katmanla engeller:
   - **İnternet içeriği okunduktan sonra hiçbir komut sormadan çalışmaz.** Sohbete bir sayfa
     özeti girdiği anda okuma komutları ve "tüm komutları sormadan çalıştır" ayarı o sohbet için
     devre dışı kalır (kart: *"internetten içerik okunduğu için onay gerekiyor"*). Sohbet
     kaydedilip yeniden açılsa da geçerlidir; yeni sohbette normale döner.
   - **Gizli bilgilere dokunan komutlar her zaman onay ister** (kırmızı kart): `~/.ssh`,
     `~/.gnupg`, anahtar halkası, tarayıcı profilleri ve çerezler, `.env`, `*.pem`/`*.key`,
     `~/.netrc`, `~/.aws`, kabuk geçmişi, `~/.ollama` anahtarı, `/etc/shadow` vb.
   - **Yerel bilgi internete giderken onay istenir.** `sayfa_ac` adresinde, `web_ara`
     sorgusunda ya da `yaz` metninde, komut çıktılarından alınmış ve kullanıcının yazmadığı/
     sayfalarda görülmemiş 16+ karakterlik bir parça varsa (adresler `%xx` çözülerek
     karşılaştırılır) işlem kırmızı kartla onaya düşer; reddedilirse modele bilgisayardaki
     bilgileri göndermemesi söylenir.
6. **Resimler** — Yalnızca yerel modele gider; bilgisayardan çıkmaz.

Reddedilen işlem görevi orada bitirir: model yeniden çağrılmaz, alternatif önermez.

### Kestirme: "bu sohbette onay isteme"

Sohbete **bu sohbette onay isteme** yazınca Robu **arama ve sayfa açma dışında onay istemez**:
değişiklik yapan ve tehlikeli komutlar, gizli dosyalar, internet içeriği okunduktan sonraki
komutlar ve Chrome'da tıklama/yazma dahil. İnternette arama ve sayfa açma için ayrıca izin
istenir. Durum çubuğunda **⚠ Komutlar onaysız · arama/sayfa açma izinli** rozeti görünür.

- Geri almak için: **bu sohbette onay iste**. Yeni sohbet her zaman onaylı başlar.
- Büyük/küçük harf ve ı/i farkı önemsizdir; "bu sohbette artık onay isteme", "… hiç onay sorma"
  da olur. Mesaj yalnızca kestirmeyse modele gitmez, anında uygulanır; başka bir istekle birlikte
  yazılırsa ("bu sohbette onay isteme, eski dosyaları sil") o istek de hemen onaysız yürür.
- Kayıtlı sohbet yeniden açıldığında durum korunur.
- Yalnızca **senin yazdığın** mesajlar sayılır: bir web sayfası ya da komut çıktısı bu cümleyi
  içerse bile onaysız moda geçilmez.
- ⚠ Bu modda internetten gelen gizli talimatlara karşı korumalar da devre dışıdır; internette
  gezinilen sohbetlerde dikkatli kullan.

---

## Acil durdurma

Robu istemediğin bir şey yapmaya başlarsa:

| Yol | Etki |
|---|---|
| **Durdur** düğmesi veya **Esc** | Çalışan komut ve tüm alt süreçleri **~1 sn** içinde sonlandırılır; model istemi işlerken bile Ollama bağlantısı **~2 sn** içinde kesilir ve Ollama üretimi bırakır; bekleyen onay reddedilir |
| Pencereyi kapatmak | Robu çalışıyorsa **"Durdur ve kapat / Vazgeç"** diye sorar; önce durdurur, kaydeder, sonra kapatır |
| `python3 -m robu --durdur` | Başka bir pencere (ör. Chrome) öndeyken de çalışır; istenirse bir klavye kısayoluna bağlanabilir |

Durdurma, o ana kadar yapılanları sohbet geçmişine kaydeder. **Tamamlanmış bir işlemi geri almaz**
(ör. çöpe taşınmış dosya çöpte kalır).

---

## Arayüz

- **Karşılama ekranı**: maskot ve tek tıkla denenebilecek örnek istekler.
- **Sohbet balonları**: kullanıcı (sağ), Robu (sol). Cevaplar kelime kelime akar.
- **"Cevap bekleniyor… N sn"** göstergesi: yavaş donanımda geçen süreyi canlı gösterir.
- **Kartlar**: ⚙ Komut / ⚠ Değişiklik yapan komut / 🖼 Resim / 🌐 Chrome — çıktılar açılır-kapanır
  bölümde, uzun çıktılar yatay kaydırılır.
- **Her cevabın altında** adım sayısı, süre ve hız (token/sn).
- **Model menüsü** (başlık çubuğu): kurulu modeller, boyut, parametre, `⚙ komut çalıştırabilir` /
  `💬 sadece sohbet` / `🖼 görsel` etiketleri; *Yeni model indir…* ve *Modelleri yönet…*.
- **Sağ panel — Sohbetler** (F9 ya da başlık çubuğundaki düğme ile gizle/göster):
  Bugün / Dün / Bu hafta / Daha eski gruplaması, her satırda başlık, saat, soru sayısı, model ve
  **sil** düğmesi (onaylı; sohbet çöp kutusuna taşınır, geri getirilebilir). Sohbet ilk mesaj
  gönderildiği anda listede görünür.
  Üstteki **arama kutusu** sohbet başlıklarında ve mesajlarında arar (büyük/küçük harf duyarsız).
  Her satırdaki **dışa aktar** düğmesi sohbeti Markdown dosyası (`.md`) olarak kaydeder
  (varsayılan: Belgeler klasörü).
- **Masaüstü bildirimi**: Robu penceresi öndeyken değilse, görev bitince, hata olunca ya da onay
  gerektiğinde bildirim gelir (görevler CPU'da dakikalar sürebilir).
- **Durum çubuğu**: Ollama bağlantısı (●), bellekteki model, CPU/GPU, Ollama sürümü, son hız.
- **Rozet**: "bu sohbette onay isteme" yazıldıysa durum çubuğunda ⚠ rozeti.
- **Kısayollar**: Enter gönder · Shift+Enter yeni satır · Ctrl+N yeni sohbet · F9 panel · Esc durdur.

---

## Model yönetimi ve Hugging Face

### İndirme (Hugging Face → Ollama)
*Model menüsü → Yeni model indir…*
- Hugging Face'te **GGUF** modelleri arar. Varsayılan: **Sohbet modelleri** (metin + görsel-metin),
  **Trend** sıralaması, **"Sadece bu bilgisayara sığanlar"** filtresi açık.
- Filtreler: Tür (Sohbet / Sadece metin / Görsel + metin), Sıralama (Trend / İndirme / Beğeni).
- Her depoda parametre sayısı ve yetenek rozetleri. Hugging Face'in parametre sayısı yardımcı
  dosyalar yüzünden yanlış olabildiği için depo adındaki boyutla (ör. `27B`) karşılaştırılır.
- Depo sayfasında **bilgi kartı**: komut çalıştırabilir mi (sohbet şablonundan okunur), görsel/ses,
  düşünme modu, kodlama, sansürsüz uyarısı, parametre, bağlam uzunluğu, lisans, temel model ve
  orijinal model kartından alınan **açıklama**.
- **Sürümler** (nicemleme: Q4_K_M, Q8_0 …) RAM'e göre işaretlenir: *belleğe sığar / zorlar / sığmaz*;
  en uygunu **önerilen** olarak en üstte. Sığmayanların İndir düğmesi kapalıdır.
- İlerleme çubuğu, iptal (sonra kaldığı yerden sürer), pencere kapalıyken arka planda devam.
- Arama kutusuna doğrudan `hf.co/kullanici/depo:Q4_K_M` ya da `gemma3:1b` yazılarak da indirilebilir.

### Yönetim
*Model menüsü → Modelleri yönet…*
- Tüm modeller: boyut, kaynak (Ollama / Hugging Face), parametre, yetenekler,
  **kullanımda** / **bellekte** rozetleri, toplam disk kullanımı.
- Onaylı **silme** (ne kadar yer açılacağı gösterilir). Robu bir modelle çalışırken o model silinemez.
- Model değiştirirken önceki model **bellekten boşaltılır** (küçük RAM'de iki modelin aynı anda
  yüklenip Ollama'nın çökmesini önler).

---

## Ayarlar

Başlık çubuğundaki ☰ menüsünden. Dosya: `~/.config/robu/ayarlar.json`

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| Okuma komutlarını sormadan çalıştır (`okuma_otomatik`) | açık | `ls`, `df`, `cat` gibi salt okunur komutlar onaysız |
| Tüm komutları sormadan çalıştır (`onaysiz`) | kapalı | Tehlikeli komutlar yine sorulur |
| Chrome'u kullanabilsin (`tarayici`) | açık | İnternet araçları |
| Chrome'da tıklama/yazma için onay iste (`tarayici_onay`) | kapalı | |
| Çalışırken bilgisayar uyumasın (`uyku_engeli`) | açık | Robu bir görev üzerinde çalışırken uyku ve ekran kilidi engellenir (`systemd-inhibit`); Robu çökse bile engel kalkar |
| Düşünme modu (`dusunme`) | kapalı | Daha isabetli, küçük modellerde çok daha yavaş |
| Çalışma klasörü (`klasor`) | `~` | Komutların çalıştığı klasör |
| Ollama adresi (`ollama`) | `http://localhost:11434` | `https://` ve alt yol (`https://sunucu/ollama`) da olur |
| Bağlam boyutu (`baglam`) | 8192 | Modelin bağlam penceresi (`num_ctx`, token); `0`: Ollama varsayılanı (Robu 4096 varsayar) |
| Komut zaman aşımı (`komut_suresi`) | 120 sn | Daha uzun süren komut sonlandırılır |
| `cikti_siniri` | 3000 | Modele giden komut çıktısı (karakter) — yalnızca dosyadan |
| `adim_siniri` | 10 | Tek görevde en fazla adım — yalnızca dosyadan |

Panelin açık/kapalı durumu ve seçili model de burada hatırlanır.

---

## Dosya konumları

| Yol | İçerik |
|---|---|
| `~/.config/robu/ayarlar.json` | Ayarlar |
| `~/.config/robu/talimatlar.md` | Kişisel talimatlar (isteğe bağlı) |
| `~/.local/share/robu/sohbetler/*.json` | Sohbet geçmişi (her sohbet bir dosya; resim verisi yok) |
| `~/.local/share/robu/dizin.json` | Belge arama dizini (metin parçaları + vektörler) |
| `~/.cache/robu/ekran/` | Ekran görüntüleri (son 20) |
| `~/.local/share/robu/chrome/` | Robu'ya ait ayrı Chrome profili |
| `~/.local/share/applications/robu.desktop` | Menü kısayolu (`kur.sh` oluşturur) |

---

## Proje yapısı

```
robu/
├── kur.sh             Kurulum: bağımlılık denetimi, eksikleri kurma, menü kısayolu
├── tests/             Birim testleri + ui_goruntu.py (arayüz ekran görüntüleri)
├── README.md
├── LICENSE          GPL-3.0
└── robu/
    ├── __main__.py    python3 -m robu
    ├── arayuz.py      GTK3 penceresi: düzen, çekirdek olayları, onay, durdurma, uygulama
    ├── bilesenler.py  Arayüz bileşenleri: balonlar, komut/resim kartları, model seçici, CSS
    ├── gecmis_paneli.py Sohbet geçmişi paneli (mixin): liste, arama, dışa aktarma, yeniden çizme
    ├── ayar_paneli.py Ayarlar menüsü (mixin): anahtarlar, bağlam, belgeler, talimatlar
    ├── cekirdek.py    Ajan döngüsü, Ollama istemcisi, araçlar, onay kuralları, acil durdurma
    ├── belgeler.py    Belge dizini: metin çıkarma (pdf/docx/odt), parçalama, embedding, arama
    ├── dosyalar.py    Dosya araçları: okuma (sayfalı), yazma/değiştirme (fark, çöpe yedek)
    ├── tarayici.py    Chrome kontrolü (CDP) + yalnızca standart kütüphaneyle WebSocket istemcisi
    ├── huggingface.py HF arama, GGUF sürümleri, RAM uyumu, model kartı/yetenek çıkarma
    ├── indirme.py     Model indirme penceresi
    ├── yonetim.py     Model yönetimi (listeleme, silme) penceresi
    ├── gecmis.py      Sohbet geçmişi kaydetme/yükleme/silme
    ├── geri_al.py     Geri alma: çöp kutusu kayıtları (freedesktop), dosya/çöp/taşıma geri alma
    ├── ses.py         Sesli giriş: kayıt (arecord), whisper.cpp / Vosk ile yazıya çevirme
    ├── ses_vosk.py    Ayrı ortamda çalışan Vosk işçisi
    ├── tts.py         Sesli yanıt (EMA Lightning) yönetimi
    ├── tts_ema_worker.py Ayrı ortamda çalışan EMA işçisi
    ├── robot.svg      Robot çizimi
    └── robu.svg       Uygulama simgesi (beyaz zemin üzerinde robot)
```

**Mimari kısaca**
- `cekirdek.Ajan` arayüzden bağımsızdır; olayları geri çağırma ile bildirir
  (`metin`, `komut`, `cikti`, `resim`, `tarayici`, `adim_bitti`, `bitti`, `durduruldu`, `hata`).
  Arayüz bu olayları GTK ana döngüsüne aktarır.
- Ajan ayrı bir iş parçacığında çalışır; onay gerektiğinde arayüzün kararını bekler.
- Ollama ile akışlı `/api/chat` kullanılır. Bağlantı elle açılır; böylece durdurma, model ilk
  kelimeyi üretmeden önce bile isteği kesebilir.
- Kabuk komutları kendi süreç grubunda çalışır; durdurma tüm grubu sonlandırır.
- Chrome, `--remote-debugging-port=9333` ve ayrı `--user-data-dir` ile başlatılır; Robu
  DevTools Protokolü üzerinden tek bir sekmeyi yönetir.

---

## Bilinen sınırlar

- **Küçük modeller her seferinde aynı davranmaz.** Aynı görev bir denemede başarılı, diğerinde
  başarısız olabilir. Robu en sık hataları telafi eder (boş cevapta hatırlatma, klasör eşlemesi,
  öneri algılama, "pes etme" talimatı), ama karmaşık çok adımlı görevlerde model şaşırabilir.
- **CPU'da yavaştır.** Her Chrome adımı 30–50 sn, her resim ~30 sn sürebilir.
- **Chrome profili boştur**: giriş gerektiren siteler (e-posta, sosyal medya) çalışmaz.
- **Google yerine DuckDuckGo** kullanılır; Google otomasyonu fark edince çerez onayı/CAPTCHA çıkarır.
- Tek bir Chrome işlemi (tıklama, sayfa yükleme; en fazla birkaç saniye) yarıda kesilmez;
  durdurmadan sonra yeni adım atılmaz.
- Ekran görüntüsü tüm ekranı kapsar (Robu penceresi dahil); tek bir pencere seçilemez.
- Çok uzun sohbetlerde en eski mesajlar modele gönderilmez (kayıtta durur); model onları
  "hatırlamaz". Yeni konu için yeni sohbet açmak hem daha hızlı hem daha isabetlidir.
- Geçmişteki sohbetler yeniden açıldığında daha önce bakılan resimler modele tekrar gönderilmez
  (yalnızca dosya adları kalır).
- `kill`, `pkill`, `killall` tehlikeli sayılır ve her zaman onay ister.
- Sızıntı denetimi bir sezgiseldir: model bilgiyi dönüştürerek (base64, harf harf, özetleyerek)
  ya da 16 karakterden kısa parçalar hâlinde gönderirse yakalanmaz. Asıl koruma, internet içeriği
  okunduktan sonra her komutun onaya düşmesidir; onay kartlarını okumadan onaylama.
- İndirilmiş dosyalardan okunan metin (ör. `cat ~/Downloads/…`) bilerek "internet içeriği"
  sayılmaz: İndirilenler'deki dosyaları kullanıcı kendisi indirir; her okumada onay sormak
  kullanımı zorlaştırırdı. Yalnızca Chrome araçlarının sonuçları sayılır.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Durum çubuğu: "Ollama'ya ulaşılamıyor" | `systemctl status ollama` · başlatmak için `sudo systemctl start ollama` |
| "Ollama çöktü; büyük olasılıkla bellek yetmedi" | Robu önce diğer modelleri boşaltıp bir kez kendiliğinden yeniden dener. Yine olmazsa: |
| "RemoteDisconnected" / Ollama aniden kapandı | Bellek yetmemiş olabilir (OOM). İki büyük model aynı anda yüklenmemeli; daha küçük bir model ya da sürüm (Q4) seç. Kontrol: `journalctl -u ollama \| grep -i oom` |
| Uzun sohbette cevaplar birden çok yavaşladı | Bağlam kırpıldıysa (durum çubuğu: "eski mesajlar kısaltıldı") istem bir kez baştan işlenir. Yeni sohbet aç ya da bağlam boyutunu küçült. |
| İlk cevap çok gecikiyor | Model diskten yükleniyordur (durum çubuğu sarı). Isınma bitince hızlanır. |
| Model "sadece sohbet" diyor | Modelin şablonu araç çağırmayı desteklemiyor; model menüsünde `⚙ komut çalıştırabilir` etiketli bir model seç. |
| "Ekran görüntüsü alınamadı" | `sudo apt install xfce4-screenshooter` (GNOME'da `gnome-screenshot`) |
| Model "resim göremem" diyor | Modelde `🖼 görsel` etiketi yok; görsel destekli bir model seç (ör. `gemma4:e4b`). |
| Chrome açılmıyor | `google-chrome --version` ile kurulu olduğunu kontrol et; 9333 portunu başka bir program kullanmıyor olmalı. |
| Değişiklikler görünmüyor | Robu'yu tamamen kapatıp yeniden aç (tek örnek çalışır). |

## Lisans

Robu, [GNU Genel Kamu Lisansı v3.0](LICENSE) (GPL-3.0-only) ile dağıtılır.
