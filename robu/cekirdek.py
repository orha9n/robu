"""Robu çekirdeği: Ollama istemcisi ve ajan döngüsü.

Arayüzden bağımsızdır; olaylar geri çağırma (callback) ile bildirilir.
Yalnızca Python standart kütüphanesi kullanılır.
"""
import ast
import base64
import http.client
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import belgeler, dosyalar, geri_al

AYAR_DOSYASI = os.path.expanduser("~/.config/robu/ayarlar.json")
TALIMAT_DOSYASI = os.path.expanduser("~/.config/robu/talimatlar.md")
TALIMAT_SINIRI = 1500  # karakter; CPU'da her istem tokenı zaman demek
TALIMAT_SABLONU = """<!--
Robu'ya kalıcı talimatlar. Bu yorum bloğu modele gönderilmez; altına yazdıkların her
sohbette sistem istemine eklenir. Kısa tut (en fazla 1500 karakter): CPU'da her kelime
cevap süresini uzatır. Değişiklikler yeni sohbette geçerli olur.

Örnekler:
- Cevapların çok kısa olsun, gereksiz açıklama yapma.
- Projelerim ~/Kod klasöründe.
- Telefon fotoğraflarım ~/Resimler/Telefon içinde.
-->
"""

VARSAYILAN_AYARLAR = {
    "ollama": "http://localhost:11434",
    "model": "",
    "onaysiz": False,      # komutları sormadan çalıştır
    "okuma_otomatik": True,  # salt okunur komutları (ls, df, cat…) sormadan çalıştır
    "tarayici": True,        # Chrome araçları (Robu'ya ait ayrı profil)
    "tarayici_onay": False,  # tıklama/yazma öncesi onay iste
    "dusunme": False,      # modelin "think" modu (küçük modellerde yavaşlatır)
    "klasor": os.path.expanduser("~"),
    "cikti_siniri": 3000,  # komut çıktısı modele en fazla bu kadar karakter gider
    "adim_siniri": 10,
    "baglam": 8192,        # modelin bağlam penceresi (num_ctx, token); 0: Ollama varsayılanı
    "komut_suresi": 120,   # bir komut en fazla bu kadar saniye çalışır
    "uyku_engeli": True,   # Robu çalışırken bilgisayar uykuya girmesin
    "belge_klasorleri": [],  # belge araması için dizinlenecek klasörler; boş: Belgeler+Masaüstü
    "belge_modeli": "embeddinggemma",  # çok dilli embedding modeli (Ollama)
    "ses_sessizlikte_dur": True,   # konuşma bitince (1,5 sn sessizlik) kayıt kendiliğinden durur
    "ses_otomatik_gonder": False,  # yazıya çevrilen metin gözden geçirilmeden gönderilsin
    "belge_otomatik": True,  # dizin varsa açılışta ve 30 dk'da bir değişen belgeleri işle
    "model_thread": None,  # None: motor varsayılanı; ölçümle seçilen pozitif thread sayısı
    "model_keep_alive": None,  # None: motor varsayılanı; ör. "5m" (kalıcı servis ayarı değil)
    "sesli_yanit": False,  # EMA Lightning; yerel ortam kuruluysa ayarlardan açılır
    "ema_python": None,    # None: ~/.local/share/robu/ema-venv/bin/python
    "ema_akis": True,      # False: EMA say() ile sesi tamamen üretip sonra oynat
}

# Bağlam tahmini (gemma4:e4b ile ölçüldü: Türkçe metin ~3, komut çıktısı ~2,3 karakter/token)
KARAKTER_TOKEN = 2.5
RESIM_TOKEN = 300
CEVAP_PAYI = 1024      # bağlamda modelin cevabına bırakılan yer (token)
OLLAMA_VARSAYILAN_BAGLAM = 4096

# Veri kaybettirebilen ya da ne yapacağı denetlenemeyen (yorumlayıcı, sudo…) komutlar
TEHLIKELI_KOMUTLAR = {
    "rm", "rmdir", "unlink", "shred", "dd", "mv", "truncate", "wipefs", "fdisk", "sfdisk",
    "parted", "kill", "pkill", "killall", "sudo", "su", "doas", "pkexec", "reboot", "shutdown",
    "poweroff", "halt", "trash-empty", "eval", "source", ".", "sh", "bash", "dash", "zsh",
    "fish", "python", "python3", "perl", "ruby", "node", "php", "lua",
}
# Ardından gelen komutu çalıştıran sarmalayıcılar (xargs rm, timeout 5 rm …)
SARMALAYICILAR = {"env", "nohup", "nice", "ionice", "time", "timeout", "xargs", "exec",
                  "command", "builtin", "stdbuf", "watch", "setsid", "parallel"}


def ayarlari_yukle():
    ayar = dict(VARSAYILAN_AYARLAR)
    try:
        with open(AYAR_DOSYASI) as f:
            ayar.update(json.load(f))
    except (OSError, ValueError):
        pass
    return ayar


def ayarlari_kaydet(ayar):
    """Yarım yazılmış (bozuk) dosya kalmasın diye önce geçici dosyaya yazar."""
    os.makedirs(os.path.dirname(AYAR_DOSYASI), exist_ok=True)
    gecici = AYAR_DOSYASI + ".tmp"
    with open(gecici, "w") as f:
        json.dump(ayar, f, ensure_ascii=False, indent=2)
    os.replace(gecici, AYAR_DOSYASI)


def kisa_ad(ad):
    """hf.co/kullanici/Depo-GGUF:Q4_K_M -> Depo:Q4_K_M"""
    if ad.startswith("hf.co/"):
        ad = ad.rsplit("/", 1)[-1]
        for ek in ("-GGUF", "-gguf"):
            ad = ad.replace(ek, "")
    return ad


# Yalnızca okuyan, hiçbir şeyi değiştirmeyen komutlar
OKUMA_KOMUTLARI = {
    "ls", "ll", "dir", "pwd", "cat", "head", "tail", "less", "wc", "file", "stat", "du", "df",
    "free", "uptime", "uname", "hostname", "whoami", "id", "date", "cal", "ps", "pgrep",
    "lsblk", "lscpu", "lsusb", "lspci", "nproc", "sensors", "which", "whereis", "type",
    "grep", "egrep", "fgrep", "rg", "find", "locate", "sort", "uniq", "cut", "tr", "column",
    "echo", "printf", "basename", "dirname", "realpath", "readlink", "tree", "md5sum",
    "sha256sum", "pdfinfo", "pdftotext", "xdg-user-dir", "identify", "exiftool", "nl",
}
# Okuma komutunu yazmaya, program çalıştırmaya ya da hiç bitmemeye (tail -f) çeviren ekler.
# Tek tireli uzun ekler önekle eşleşir: -exec → -execdir, -fprint → -fprintf/-fprint0.
SAKINCALI_EKLER = {
    "find": ("-delete", "-exec", "-ok", "-fprint", "-fls"),
    "sort": ("-o", "--output", "--compress-program"),
    "tree": ("-o", "-R"),
    "rg": ("--pre",),
    "tail": ("-f", "-F", "--follow"),
    "file": ("-C", "--compile"),
    "date": ("-s", "--set"),
}
# exiftool'un yazan eki çok (-o, -w, -TAG=, -tagsFromFile…); yalnızca bunlara izin verilir
EXIFTOOL_EKLERI = {"-s", "-S", "-a", "-g", "-G", "-n", "-j", "-json", "-csv", "-r", "-q", "-u"}
SISTEM_KLASORLERI = ("/bin", "/usr/bin", "/usr/local/bin")
ISLEC_HARFLERI = set("();<>|&")

# Zararsız ve küçük modellerin çok sık yazdığı yönlendirmeler; onaya düşmesinler
_SESSIZ = re.compile(r"(?<!\S)(?:[12]?>|&>)\s*/dev/null(?![^\s;|&])|(?<!\S)2>&1(?![^\s;|&])")


def _parcala(cmd):
    """Komutu bash'e yakın biçimde sözcüklere ve işleçlere (| && ; & > ( …) ayırır.

    Tırnaklar ve kaçışlar bash gibi çözülür; satır sonu da komut ayırır (bash öyle
    çalıştırır). Tırnak içindeki tek başına işleç (';') de işleç sayılır: şüphede sıkı
    davranmak için. Kapanmamış tırnakta ValueError.
    """
    metin = re.sub(r"\s*[\r\n]+\s*", " ; ", _SESSIZ.sub(" ", cmd.strip()))
    s = shlex.shlex(metin, posix=True, punctuation_chars=True)
    s.whitespace_split = True
    s.commenters = ""  # bash '#'yi yalnızca sözcük başında yorum sayar, shlex her yerde
    return list(s)


def _islec_mi(sozcuk):
    return all(c in ISLEC_HARFLERI for c in sozcuk)


def _bolumler(sozcukler):
    """İşleçlerle ayrılmış komut bölümleri: [(sözcükler, ardından gelen işleç), …]."""
    sonuc, bolum = [], []
    for s in sozcukler:
        if _islec_mi(s):
            sonuc.append((bolum, s))
            bolum = []
        else:
            bolum.append(s)
    sonuc.append((bolum, None))
    return sonuc


def _ek_var_mi(argumanlar, ekler):
    """Sakıncalı eklerden biri var mı? GNU uzun ekleri kısaltılabildiği (--out=f), tek harfli
    ekler birleşik yazılabildiği (-ro f) için birebir karşılaştırma yetmez."""
    for a in argumanlar:
        if a.startswith("--"):
            ad = a.split("=", 1)[0]
            if len(ad) > 2 and any(e.startswith(ad) for e in ekler if e.startswith("--")):
                return True
        elif a.startswith("-") and len(a) > 1:
            for e in ekler:
                if e.startswith("--"):
                    continue
                if (len(e) == 2 and e[1] in a[1:]) or (len(e) > 2 and a.startswith(e)):
                    return True
    return False


def _okuma_bolumu_mu(k):
    if not k:
        return False
    ad = k[0]
    if "/" in ad:  # ./ls gibi sistem dışındaki bir program okuma komutu taklidi yapabilir
        if os.path.dirname(ad) not in SISTEM_KLASORLERI:
            return False
        ad = os.path.basename(ad)
    if any(re.search(r"\{.*(,|\.\.).*\}", a) for a in k):  # {-delete,} → -delete olur
        return False
    if ad == "gio":
        return len(k) > 1 and k[1] in ("list", "info")
    if ad not in OKUMA_KOMUTLARI:
        return False
    if ad == "pdftotext" and k[-1] != "-":  # aksi hâlde dosyaya yazar
        return False
    if ad == "exiftool" and any(a.startswith("-") and a not in EXIFTOOL_EKLERI for a in k[1:]):
        return False
    if ad == "uniq" and sum(not a.startswith("-") for a in k[1:]) > 1:  # uniq girdi ÇIKTI
        return False
    return not _ek_var_mi(k[1:], SAKINCALI_EKLER.get(ad, ()))


def okuma_komutu_mu(cmd):
    """Komut zinciri yalnızca okuma yapıyorsa True. Şüphede False (onay istenir).

    Bölümler arasında yalnızca | || && ; olabilir; yönlendirme (>), arka plan (&),
    alt kabuk ve alt komut ($(…), ters tırnak) her zaman onaya düşer.
    """
    if "`" in cmd or "$(" in cmd:
        return False
    try:
        bolumler = _bolumler(_parcala(cmd))
    except ValueError:
        return False
    return all(_okuma_bolumu_mu(k) and islec in ("|", "||", "&&", ";", None)
               for k, islec in bolumler)


def _alt_komutlar(cmd):
    """$(…), <(…), >(…) ve `…` içindeki komutlar; kapanmamışsa None."""
    if cmd.count("`") % 2:
        return None
    alt = re.findall(r"`([^`]*)`", cmd)
    acilis = re.compile(r"[$<>]\(")
    i = 0
    while m := acilis.search(cmd, i):
        derinlik, j = 1, m.end()
        while j < len(cmd) and derinlik:
            derinlik += {"(": 1, ")": -1}.get(cmd[j], 0)
            j += 1
        if derinlik:
            return None
        alt.append(cmd[m.end():j - 1])
        i = m.end()  # iç içe olanlar da bulunsun
    return alt


def _bolum_tehlikeli_mi(k):
    while k and re.match(r"[A-Za-z_]\w*=", k[0]):  # baştaki DEGISKEN=deger atamaları
        k = k[1:]
    if not k:
        return False
    if "$" in k[0] or "`" in k[0]:  # komut adı çalışırken belirleniyor; denetlenemez
        return True
    ad, arg = os.path.basename(k[0]), k[1:]
    if ad in SARMALAYICILAR:  # eklerini ayrıştırmak yerine her sözcüğü komut adı say
        return any(_bolum_tehlikeli_mi(arg[i:]) for i in range(len(arg)))
    if ad in TEHLIKELI_KOMUTLAR or ad.startswith("mkfs"):
        return True
    if ad in ("chmod", "chown", "chgrp"):
        return any(a == "--recursive" or re.fullmatch(r"-[a-zA-Z]*R[a-zA-Z]*", a) for a in arg)
    if ad == "find":
        if any(a.startswith("-delete") for a in arg):
            return True
        for i, a in enumerate(arg):
            if a.startswith(("-exec", "-ok")):
                return _bolum_tehlikeli_mi(arg[i + 1:])
    if ad == "gio":  # gio remove çöpe atmadan siler
        return bool(arg) and (arg[0] in ("remove", "rm") or (arg[0] == "trash" and "--empty" in arg))
    if ad == "git":
        return bool(arg) and (arg[0] == "clean" or (arg[0] == "reset" and "--hard" in arg))
    if ad == "rsync":
        return any(a.startswith("--del") for a in arg)
    if ad == "crontab":
        return "-r" in arg
    if ad == "tee":  # -a olmadan dosyanın üstüne yazar
        return not any(a in ("-a", "--append") for a in arg)
    return False


def tehlikeli_mi(cmd):
    """Veri kaybettirebilecek ya da denetlenemeyen komut mu? 'Tüm komutları sormadan
    çalıştır' açıkken bile bunlar için onay istenir. Şüphede True."""
    if ":(){" in cmd.replace(" ", ""):  # çatal bombası
        return True
    alt = _alt_komutlar(cmd)
    if alt is None or any(tehlikeli_mi(a) for a in alt):
        return True
    try:
        bolumler = _bolumler(_parcala(cmd))
    except ValueError:
        return True
    for k, islec in bolumler:
        if _bolum_tehlikeli_mi(k):
            return True
        if islec and ">" in islec and ">>" not in islec:  # dosyanın üstüne yazan yönlendirme
            return True
    return False


# Anahtarlar, şifreler, tarayıcı çerezleri, kabuk geçmişi… Bunlara dokunan komut her zaman
# onaya düşer: internetten gelen gizli bir talimat modeli bunları okumaya yönlendirebilir.
HASSAS = re.compile(
    r"\.ssh\b|\.gnupg|\.password-store|keyrings|\.mozilla|google-chrome|chromium|"
    r"BraveSoftware|\.aws\b|\.kube\b|\.docker\b|\.netrc|\.pgpass|git-credentials|"
    r"\.config/gh\b|\.ollama|robu/chrome|(?<![\w.-])\.env\b|id_(rsa|dsa|ecdsa|ed25519)|"
    r"\.(pem|key|kdbx|p12|pfx)\b|/etc/(shadow|gshadow|sudoers)|_history\b|"
    r"cookies|login data|wallet", re.I)


def hassas_mi(cmd):
    return bool(HASSAS.search(cmd))


RET_CEVABI = "Tamam, işleme devam etmiyorum."
RET = "ret"  # _arac dönüşü: kullanıcı reddetti, görev burada biter (model yeniden çağrılmaz)
_RET = re.compile(r"(?:hayir|yok|onaylamiyorum|istemiyorum|vazgec|vazgectim|iptal|gerek yok|"
                  r"devam etme|yapma|dur)(?:[\s,]+(?:bunu\s+)?(?:yapma|istemiyorum|"
                  r"devam etme|tesekkurler|sagol))*")


def ret_mi(metin):
    """Mesajın tamamı bir ret mi ("hayır", "Onaylamıyorum, bunu yapma.", "vazgeç")?
    Öyleyse model çağrılmadan "işleme devam etmiyorum" denir."""
    k = re.sub(r"[^\w\s,]", " ", _kucult(metin)).strip(" ,")
    return bool(k) and bool(_RET.fullmatch(" ".join(k.split())))


# Küçük modeller talimata rağmen cevabın sonuna "Başka bir şey ister misin? Öneriler: …" ekliyor.
_TEKLIF = re.compile(
    r"baska (?:bir )?(?:sey|konu|soru|istegin|yardim|islem)|yardimci olabilecegim|"
    r"yardimci olmami ister|^\W*oneriler?\b|^\W*ornegin\s*:|"
    r"(?:baska|ayrica|bunun disinda)\b.*\?\s*$|nasil (?:bir )?devam ede|"
    r"ne yapmami (?:ister|tercih)\w*\?\s*$|^\W*istersen(?:iz)?\b", re.M)
# Asıl cevap da liste olabilir; liste yalnızca önünde teklif cümlesi varsa atılır.
_LISTE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s", re.M)
_LISTE_ONU = re.compile(r"ornegin|ister mi(?:sin|siniz)|ister\w*\?|secenek|tercih")


def teklifleri_temizle(metin):
    """Cevabın sonundaki teklif sorularını ve öneri listelerini atar; asıl cevaba dokunmaz.
    Yalnızca teklif olan bir cevap olduğu gibi kalır (boş cevap gösterilmesin)."""
    paragraflar = re.split(r"\n\s*\n", metin.strip())
    while len(paragraflar) > 1:
        if _TEKLIF.search(_kucult(paragraflar[-1])):
            paragraflar.pop()
        elif len(paragraflar) > 2 and _LISTE.search(paragraflar[-1]) \
                and _LISTE_ONU.search(_kucult(paragraflar[-2])):
            del paragraflar[-2:]  # "Örneğin: / … ister misiniz?" + seçenek listesi
        else:
            break
    son = paragraflar[-1]
    cumleler = re.split(r"(?<=[.!?])\s+", son)
    while len(cumleler) > 1 and _TEKLIF.search(_kucult(cumleler[-1])):
        cumleler.pop()
    paragraflar[-1] = " ".join(cumleler)
    return "\n\n".join(paragraflar)


# Araç sonucunun başarısız olduğunu gösteren işaretler (Robu'nun kendi hata metinleri)
_ARAC_HATASI = re.compile(
    r"^(?:\(Not:[^\n]*\)\n)?(?:\(çıkış kodu \d+|Yapılamadı|Okunamadı|Dosya bulunamadı|"
    r"Eski dosya çöpe taşınamadığı|Değiştirilecek metin dosyada bulunamadı|Metin dosyada \d+ "
    r"yerde|Tarayıcı hatası|Resim açılamadı|Klasörde resim yok|Belge araması yapılamadı|"
    r"Ekran görüntüsü alınamadı|Komut \d+ saniyede bitmedi|Bilinmeyen araç)")
_BASARI = re.compile(r"\b(?:basariyla|tamamlandi|yapildi|tasindi|olusturuldu|silindi|"
                     r"degistirildi|kaydedildi|yazildi|guncellendi|tasidim|sildim|yaptim|"
                     r"olusturdum|degistirdim)\b")
_BASARISIZLIK = re.compile(r"basarisiz|hata|yapilamadi|bulunamadi|bulamadim|olmadi|"
                           r"tasinamadi|edemedim|yapamadim|calismadi|basaramadim")
YANILTICI_BASARI = "⚠ Son işlem hata verdi; cevabı kontrol et."


def arac_hatasi_mi(sonuc):
    return bool(_ARAC_HATASI.match(sonuc or ""))


def basari_iddiasi_mi(cevap):
    """Cevap başarı bildiriyor ve hiçbir başarısızlıktan söz etmiyor mu?"""
    k = _kucult(cevap or "")
    return bool(_BASARI.search(k)) and not _BASARISIZLIK.search(k)


# Kullanıcının sohbete yazdığı kestirme: "bu sohbette onay isteme" / "bu sohbette onay iste"
_ONAYSIZ = re.compile(r"\bbu sohbette\s+(?:hic\s+|artik\s+)?onay\s+(?:isteme|sorma)\b")
_ONAYLI = re.compile(r"\bbu sohbette\s+(?:tekrar\s+|yeniden\s+)?onay\s+(?:iste|sor)\b")


def _kucult(metin):
    """Türkçe büyük/küçük harf ve ı/i farkını yok sayar (İSTEME, ISTEME, isteme)."""
    metin = metin.replace("İ", "i").replace("I", "i").lower()
    for tr, en in ("ıi", "çc", "ğg", "şs", "üu", "öo"):
        metin = metin.replace(tr, en)
    return metin


def onay_kestirmesi(metin):
    """True: bu sohbette onay isteme · False: yeniden onay iste · None: kestirme yok."""
    k = _kucult(metin)
    if _ONAYSIZ.search(k):
        return True
    if _ONAYLI.search(k):
        return False
    return None


def yalniz_kestirme_mi(metin):
    """Mesaj kestirmeden ibaretse (modele gönderilmeden cevaplanabilir) True."""
    kalan = _ONAYLI.sub("", _ONAYSIZ.sub("", _kucult(metin)))
    return not re.search(r"\w", kalan)


SIZINTI_SINIRI = 16 # giden metinde bu uzunlukta yerel bir parça varsa onay istenir


def _duz(metin):
    return " ".join(metin.lower().split())


def sizinti_parcasi(giden, yerel, bilinen):
    """İnternete gidecek metinde (adres, arama, yazı) komut çıktılarından (`yerel`) alınmış,
    ama kullanıcının yazdıklarında ya da web sayfalarında (`bilinen`) geçmeyen en az
    SIZINTI_SINIRI karakterlik bir parça varsa onu döndürür. Adresler önce çözülür (%2F…)."""
    g = _duz(urllib.parse.unquote_plus(urllib.parse.unquote_plus(giden)))
    yerel, bilinen = _duz(yerel), _duz(bilinen)
    for i in range(len(g) - SIZINTI_SINIRI + 1):
        parca = g[i:i + SIZINTI_SINIRI]
        if parca in yerel and parca not in bilinen:
            return parca
    return None


XDG_ADLARI = {"DESKTOP": "Masaüstü", "DOWNLOAD": "İndirilenler", "DOCUMENTS": "Belgeler",
              "PICTURES": "Resimler", "MUSIC": "Müzik", "VIDEOS": "Videolar"}


def _xdg_yollari():
    """{'DESKTOP': '~/Desktop', …} — ~/.config/user-dirs.dirs dosyasından."""
    yollar = {}
    try:
        with open(os.path.expanduser("~/.config/user-dirs.dirs")) as f:
            for satir in f:
                if satir.startswith("XDG_") and "=" in satir:
                    anahtar, deger = satir.strip().split("=", 1)
                    yollar[anahtar[4:-4]] = deger.strip('"').replace("$HOME", "~")
    except OSError:
        pass
    return yollar


def xdg_klasoru(anahtar):
    """'DOCUMENTS' -> '/home/x/Documents' (yoksa None)."""
    yol = _xdg_yollari().get(anahtar)
    return os.path.expanduser(yol) if yol else None


def klasor_adlari():
    """'Masaüstü=~/Desktop, İndirilenler=~/Downloads, …' — küçük modeller Türkçe klasör
    adlarını yola çevirmeye çalışıp (/home/x/İndirilenler) yanılıyor."""
    yollar = _xdg_yollari()
    return ", ".join(f"{ad}={yollar[k]}" for k, ad in XDG_ADLARI.items() if k in yollar)


def kisisel_talimatlar():
    """~/.config/robu/talimatlar.md içeriği (HTML yorumları atılmış, sınırlı)."""
    try:
        with open(TALIMAT_DOSYASI) as f:
            metin = f.read()
    except OSError:
        return ""
    metin = re.sub(r"<!--.*?-->", "", metin, flags=re.S).strip()
    return metin[:TALIMAT_SINIRI]


def talimat_dosyasini_hazirla():
    """Dosya yoksa açıklamalı şablonla oluşturur; yolunu döndürür."""
    if not os.path.exists(TALIMAT_DOSYASI):
        os.makedirs(os.path.dirname(TALIMAT_DOSYASI), exist_ok=True)
        with open(TALIMAT_DOSYASI, "w") as f:
            f.write(TALIMAT_SABLONU)
    return TALIMAT_DOSYASI


def sistem_istemi(klasor, araclar=True, gorsel=False, tarayici=False, belge=False):
    talimat = kisisel_talimatlar()
    ek = f"\nKullanıcının kalıcı talimatları:\n{talimat}" if talimat else ""
    return _sistem_istemi(klasor, araclar, gorsel, tarayici, belge) + ek


def _sistem_istemi(klasor, araclar, gorsel, tarayici, belge=False):
    # Kısa tutuluyor: CPU'da her istem tokenı saniyeler demek.
    if not araclar:
        return (
            "Sen Robu'sun: Linux üzerinde çalışan küçük, yardımsever bir asistan. "
            "Türkçe, kısa ve net cevap ver. Komut çalıştıramazsın; gerekirse kullanıcının "
            "terminalde çalıştırması için bash komutunu kod bloğu içinde ver."
        )
    # Araçların ayrıntısı araç açıklamalarında; burada yalnızca davranış kuralları.
    return (
        "Sen Robu'sun: Linux'ta çalışan yardımsever bir asistan. Türkçe, kısa ve net cevap ver. "
        "Bilgisayarda bir şey öğrenmek ya da yapmak için araçları kullan. İstenen işi hemen yap; "
        "'emin misin' diye sorma, önceden anlatma: onayı arayüz sorar. Dosya adını aynen kullan, "
        "klasör tahmin etme. Silmek için `gio trash`; sudo kullanma. Metin dosyaları için "
        "`dosya_oku/dosya_yaz/dosya_degistir`; PDF: `pdftotext -layout f.pdf -`, Excel/Word: "
        "`libreoffice --headless --convert-to csv f.xlsx`. "
        "Veride olmayan değeri uydurma. "
        + ("Resim sorularında yol sorma, dosya adından tahmin etme. " if gorsel else "")
        + ("Genel bilgi sorularını kendi bilginle cevapla. Güncel ya da emin olmadığın bilgi "
           "(haber, fiyat, son sürüm…) gerekiyorsa Chrome araçlarıyla bak. Arama ve sayfa "
           "açmadan önce kullanıcı iznini arayüz sorar; izinsiz internete çıkma. Cevabı sayfada "
           "gördüğüne dayandır. " if tarayici else "")
        + ("Kullanıcının kendi bilgileri (fatura, sözleşme, tarih, tutar…) sorulursa önce "
           "`belge_ara` ile ara. " if belge else "")
        + "Bir yol işe yaramazsa başkasını dene. "
        + f"Ev klasörü: {os.path.expanduser('~')}. Klasörler: {klasor_adlari()}. "
        + f"Çalışma klasörü: {klasor}"
    )


RESIM_ARACI = {
    "type": "function",
    "function": {
        "name": "resim_bak",
        "description": "Resimlere bakar. yol: dosya; klasör (içindeki en fazla 6 resim "
                       "birlikte, 'hangi resimde…' için) ya da ekran görüntüsü için 'ekran'.",
        "parameters": {
            "type": "object",
            "properties": {"yol": {"type": "string"}},
            "required": ["yol"],
        },
    },
}

RESIM_UZANTILARI = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
RESIM_SINIRI = 6  # tek seferde gösterilecek en fazla resim (CPU'da her biri ~30 sn)


def resim_yollari(yol):
    """Dosya ise kendisi, klasör ise içindeki resimler: (yollar, hata)."""
    if os.path.isdir(yol):
        yollar = sorted(os.path.join(yol, ad) for ad in os.listdir(yol)
                        if ad.lower().endswith(RESIM_UZANTILARI))
        if not yollar:
            return [], f"Klasörde resim yok: {yol}"
        return yollar[:RESIM_SINIRI], None
    if not os.path.exists(yol):
        return [], f"Dosya bulunamadı: {yol}"
    return [yol], None


EKRAN_ADLARI = {"ekran", "ekran görüntüsü", "screen", "screenshot"}
EKRAN_KLASORU = os.path.expanduser("~/.cache/robu/ekran")
EKRAN_SAKLAMA = 20      # bu kadar son ekran görüntüsü saklanır (geçmişteki kartlar için)
EKRAN_BOYUTU = 1280     # ekran yazıları okunabilsin diye resimlerden (1024) biraz büyük
# Masaüstüne göre ekran görüntüsü araçları; dosya yolu sona eklenir
EKRAN_ARACLARI = [
    ["xfce4-screenshooter", "-f", "-s"], ["gnome-screenshot", "-f"],
    ["spectacle", "-b", "-n", "-f", "-o"], ["scrot", "-o"], ["grim"],
    ["import", "-window", "root"], ["maim"],
]


def ekran_goruntusu():
    """Tüm ekranın görüntüsünü ~/.cache/robu/ekran altına kaydeder: (yol, hata)."""
    os.makedirs(EKRAN_KLASORU, exist_ok=True)
    yol = os.path.join(EKRAN_KLASORU, time.strftime("ekran-%Y%m%d-%H%M%S.png"))
    for arac in EKRAN_ARACLARI:
        if not shutil.which(arac[0]):
            continue
        try:
            p = subprocess.run(arac + [yol], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if p.returncode == 0 and os.path.isfile(yol) and os.path.getsize(yol):
            eskiler = sorted(a for a in os.listdir(EKRAN_KLASORU) if a.startswith("ekran-"))
            for ad in eskiler[:-EKRAN_SAKLAMA]:  # Robu'nun kendi önbelleği
                try:
                    os.remove(os.path.join(EKRAN_KLASORU, ad))
                except OSError:
                    pass
            return yol, None
    return None, ("Ekran görüntüsü alınamadı. Kurulum: sudo apt install xfce4-screenshooter "
                  "(ya da gnome-screenshot / scrot)")


def resim_hazirla(yol, en_buyuk=1024):
    """Resmi modele gönderilecek base64 JPEG'e çevirir: (veri, hata).

    Büyük fotoğraflar küçültülür; model zaten düşük çözünürlükte görür ve
    CPU'da gereksiz büyük veri yalnızca yavaşlatır.
    """
    if not os.path.isfile(yol):
        return None, f"Dosya bulunamadı: {yol}"
    if not yol.lower().endswith(RESIM_UZANTILARI):
        return None, f"Resim dosyası değil: {yol}"
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        resim = GdkPixbuf.Pixbuf.new_from_file(yol)
        resim = resim.apply_embedded_orientation() or resim
        oran = en_buyuk / max(resim.get_width(), resim.get_height())
        if oran < 1:
            resim = resim.scale_simple(int(resim.get_width() * oran),
                                       int(resim.get_height() * oran),
                                       GdkPixbuf.InterpType.BILINEAR)
        if resim.get_has_alpha():
            resim = resim.composite_color_simple(resim.get_width(), resim.get_height(),
                                                 GdkPixbuf.InterpType.BILINEAR, 255, 1,
                                                 0xFFFFFF, 0xFFFFFF)
        _, veri = resim.save_to_bufferv("jpeg", ["quality"], ["85"])
    except Exception as e:
        return None, f"Resim açılamadı: {e}"
    return base64.b64encode(veri).decode(), None


def _arac(ad, aciklama, ozellikler, zorunlu):
    return {"type": "function", "function": {
        "name": ad, "description": aciklama,
        "parameters": {"type": "object", "properties": ozellikler, "required": zorunlu}}}


TARAYICI_ARACLARI = [
    _arac("web_ara", "Chrome'da internette arar.",
          {"sorgu": {"type": "string"}}, ["sorgu"]),
    _arac("sayfa_ac", "Chrome'da adres açar.",
          {"adres": {"type": "string"}}, ["adres"]),
    _arac("sayfa_oku", "Sayfanın devamını okur (parca=2, 3…); ilk parça zaten gelir.",
          {"parca": {"type": "integer"}}, []),
    _arac("tikla", "Numaralı öğeye tıklar.",
          {"no": {"type": "integer"}}, ["no"]),
    _arac("yaz", "Numaralı kutuya yazar; gonder=true Enter'a basar.",
          {"no": {"type": "integer"}, "metin": {"type": "string"},
           "gonder": {"type": "boolean"}}, ["no", "metin"]),
]
TARAYICI_ADLARI = {a["function"]["name"] for a in TARAYICI_ARACLARI}


def tarayici_aciklamasi(ad, arg):
    """Kartta gösterilecek kısa açıklama."""
    return {
        "web_ara": lambda: f"Ara: {arg.get('sorgu', '')}",
        "sayfa_ac": lambda: f"Aç: {arg.get('adres', '')}",
        "sayfa_oku": lambda: f"Sayfayı oku (parça {arg.get('parca') or 1})",
        "tikla": lambda: f"Tıkla: [{arg.get('no')}]",
        "yaz": lambda: f"Yaz [{arg.get('no')}]: {arg.get('metin', '')}"
                       + ("  ⏎" if arg.get("gonder") else ""),
    }.get(ad, lambda: ad)()


ARACLAR = [{
    "type": "function",
    "function": {
        "name": "komut",
        "description": "Bash komutu çalıştırır.",
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
    },
}]


class Ollama:
    def __init__(self, adres, olcum=None):
        self.adres = adres.rstrip("/")
        self.olcum = olcum  # isteğe bağlı içeriksiz zaman noktası callback'i

    def _istek(self, yol, govde=None, zaman_asimi=10, yontem=None):
        veri = json.dumps(govde).encode() if govde is not None else None
        istek = urllib.request.Request(self.adres + yol, veri,
                                       {"Content-Type": "application/json"}, method=yontem)
        return urllib.request.urlopen(istek, timeout=zaman_asimi)

    def surum(self):
        with self._istek("/api/version", zaman_asimi=3) as r:
            return json.load(r).get("version", "?")

    def modeller(self):
        """Kurulu modeller: [{ad, boyut_gb, parametre}] (küçükten büyüğe)."""
        with self._istek("/api/tags") as r:
            liste = json.load(r).get("models", [])
        sonuc = []
        for m in liste:
            yetenek = self.yetenekler(m["name"])
            if "embedding" in yetenek or "embed" in m["name"]:
                continue
            sonuc.append({
                "ad": m["name"],
                "boyut_gb": m.get("size", 0) / 1e9,
                "parametre": m.get("details", {}).get("parameter_size", ""),
                "araclar": "tools" in yetenek,
                "gorsel": "vision" in yetenek,
            })
        return sorted(sonuc, key=lambda m: m["boyut_gb"])

    def yetenekler(self, model):
        """['completion', 'tools', 'vision', ...]"""
        try:
            with self._istek("/api/show", {"model": model}) as r:
                return json.load(r).get("capabilities") or []
        except (urllib.error.URLError, ValueError):
            return []

    def cek(self, ad, dur=None):
        """Model indirir (ollama pull). İlerleme sözlüklerini üretir.

        Bağlantı kapatılınca Ollama indirmeyi bırakır; yarım kalan
        parçalar saklanır ve sonraki denemede kaldığı yerden sürer.
        """
        r = self._istek("/api/pull", {"model": ad, "stream": True}, zaman_asimi=120)
        try:
            for satir in r:
                if dur is not None and dur.is_set():
                    return
                if satir.strip():
                    veri = json.loads(satir)
                    if "error" in veri:
                        raise RuntimeError(veri["error"])
                    yield veri
        finally:
            r.close()

    def vektor(self, model, girdiler):
        """Metinlerin embedding vektörleri (/api/embed)."""
        with self._istek("/api/embed", {"model": model, "input": girdiler}, 600) as r:
            return json.load(r)["embeddings"]

    def bosalt(self, ad):
        """Modeli bellekten çıkarır (diskte kalır)."""
        with self._istek("/api/generate", {"model": ad, "keep_alive": 0}, 30):
            pass

    def sil(self, ad):
        """Modeli diskten siler; bellekteyse önce boşaltır."""
        try:
            with self._istek("/api/generate", {"model": ad, "keep_alive": 0}, 30):
                pass
        except urllib.error.URLError:
            pass
        with self._istek("/api/delete", {"model": ad}, 60, yontem="DELETE"):
            pass

    def yuklu(self):
        """Bellekteki modeller: {ad: {'ram_gb', 'gpu'}}."""
        with self._istek("/api/ps") as r:
            liste = json.load(r).get("models", [])
        return {m["name"]: {"ram_gb": m.get("size", 0) / 1e9,
                            "gpu": m.get("size_vram", 0) > 0} for m in liste}

    def sohbet_akisi(self, govde, tutucu=None):
        """Akışlı /api/chat; her JSON satırını üretir.

        `tutucu` listesine yanıt nesnesi konur; başka bir iş parçacığı onu kapatarak
        (bkz. Ajan.durdur) model daha ilk kelimeyi üretmeden bile isteği kesebilir.
        """
        govde = dict(govde, stream=True)
        # urlopen, Ollama ilk kelimeyi üretip başlıkları gönderene kadar (CPU'da dakikalar)
        # bloklar ve bu sırada kesilecek bir nesne vermez. Bağlantıyı elle açıp önceden
        # tutucuya koyuyoruz ki durdurma her an soketi kapatabilsin.
        p = urllib.parse.urlparse(self.adres)
        if p.scheme == "https":
            baglanti = http.client.HTTPSConnection(p.hostname, p.port or 443, timeout=900)
        else:
            baglanti = http.client.HTTPConnection(p.hostname, p.port or 80, timeout=900)
        baglanti.connect()
        if tutucu is not None:
            tutucu[:] = [baglanti]
        try:
            baglanti.request("POST", p.path.rstrip("/") + "/api/chat", json.dumps(govde).encode(),
                             {"Content-Type": "application/json"})
            if self.olcum:
                self.olcum("http_request_sent")
            r = baglanti.getresponse()
            if r.status != 200:
                hata = r.read().decode("utf-8", "replace")
                raise urllib.error.URLError(f"HTTP {r.status}: {hata[:200]}")
            for satir in r:
                if satir.strip():
                    veri = json.loads(satir)
                    if self.olcum:
                        self.olcum("stream_event")
                    if "error" in veri:
                        raise RuntimeError(veri["error"])
                    yield veri
        finally:
            baglanti.close()


class UykuEngeli:
    """Robu bir görev üzerinde çalışırken bilgisayarın uykuya girmesini engeller
    (systemd-inhibit). Engelleyici Robu'nun sürecine bağlıdır: Robu çökse bile
    `tail --pid` biter ve engel kendiliğinden kalkar."""

    def __init__(self):
        self._surec = None

    def baslat(self):
        if self._surec is not None and self._surec.poll() is None:
            return
        try:
            self._surec = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=Robu",
                 "--why=Robu bir görev üzerinde çalışıyor", "--mode=block",
                 "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except OSError:  # systemd-inhibit yok: engel olmadan devam
            self._surec = None

    def bitir(self):
        if self._surec is not None and self._surec.poll() is None:
            _grubu_oldur(self._surec)
        self._surec = None


COKME_METNI = ("Ollama çöktü; büyük olasılıkla bellek yetmedi. Açık programları kapatmayı, daha "
               "küçük bir model ya da bağlam boyutu seçmeyi dene.")


_METIN_CAGRI = re.compile(r"^\s*(?:```\w*\s*)?`?(\w+)\((.*)\)`?\s*(?:```)?\s*$", re.S)
_ARGUMAN = re.compile(r"""(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^,]+)""")


def arac_metni_olabilir(metin, adlar):
    """Belirsiz araç/kod önekini, tamamlanıp ayrıştırılana kadar ekrana verme."""
    s = metin.lstrip()
    if not s or s.startswith(("{", "[", "`", "<")):
        return True
    return any(ad.startswith(s) or re.match(re.escape(ad) + r"\s*\(", s)
               for ad in adlar)


def metindeki_arac_cagrisi(metin, adlar):
    """Küçük modeller bazen aracı çağırmak yerine çağrıyı metin olarak yazıyor:
    `dosya_oku(yol="notlar.md")` ya da {"name": "dosya_oku", "arguments": {...}}.
    Cevap YALNIZCA böyle bir çağrıdan ibaretse ve araç adı bilinen bir araçsa, araç çağrısı
    sözlüğüne çevirir; değilse None (normal metin cevaplarına dokunulmaz)."""
    metin = (metin or "").strip()
    if not metin or len(metin) > 2000:
        return None
    try:  # JSON biçimi
        veri = json.loads(metin.strip("`").removeprefix("json").strip())
        if isinstance(veri, dict) and veri.get("name") in adlar:
            arg = veri.get("arguments") or veri.get("parameters") or {}
            if isinstance(arg, dict):
                return {"function": {"name": veri["name"], "arguments": arg}}
    except ValueError:
        pass
    m = _METIN_CAGRI.match(metin)
    if not m or m[1] not in adlar:
        return None
    arg = {}
    for anahtar, deger in _ARGUMAN.findall(m[2]):
        deger = deger.strip()
        if deger[:1] in "\"'":
            try:
                deger = ast.literal_eval(deger)
            except (ValueError, SyntaxError):
                deger = deger[1:-1]
        elif deger.lower() in ("true", "false"):
            deger = deger.lower() == "true"
        elif re.fullmatch(r"-?\d+", deger):
            deger = int(deger)
        arg[anahtar] = deger
    if not arg and m[2].strip():
        return None  # anlaşılmayan argümanlar: tahmin etme
    return {"function": {"name": m[1], "arguments": arg}}


def cokme_mi(hata):
    """Ollama'nın istek sırasında kapandığını (çoğunlukla bellek yetersizliği, OOM) gösteren
    hata mı? Robu bu durumda bir kez yeniden dener."""
    if isinstance(hata, (http.client.RemoteDisconnected, http.client.IncompleteRead,
                         ConnectionResetError, ConnectionRefusedError, BrokenPipeError)):
        return True
    neden = str(getattr(hata, "reason", hata)).lower()
    return any(k in neden for k in ("terminated", "killed", "connection reset", "refused",
                                    "remote end closed", "eof"))


def _grubu_oldur(p):
    """Kabuğu ve başlattığı tüm alt süreçleri sonlandırır."""
    for sinyal, bekle in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 0)):
        try:
            os.killpg(p.pid, sinyal)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(timeout=bekle or None)
            return
        except subprocess.TimeoutExpired:
            continue


class Ajan:
    """Tek bir sohbeti yürütür. Olaylar `olay(tur, veri)` ile bildirilir.

    Olay türleri:
      basladi, dusunce(metin), metin(metin), komut(kimlik, cmd, tehlikeli, otomatik, baslik),
      tarayici(kimlik, aciklama, uyari), cikti(kimlik, cikti, reddedildi), adim_bitti(istatistik),
      bitti(), hata(mesaj), durduruldu()
    `onay(cmd)` çağrısı True/False döner (arayüz iş parçacığını bekletebilir).
    """

    def __init__(self, ayar, olay, onay, olcum=None):
        self.ayar = ayar
        self.olcum = olcum
        self.olay = olay
        self.onay = onay
        self.dur = threading.Event()
        self._yanit = []      # süren Ollama yanıtı (durdururken kesilir)
        self._surec = None    # süren kabuk komutu (durdururken öldürülür)
        self.mesajlar = []
        self.arsiv = []       # bağlam sınırı yüzünden modele artık gönderilmeyen eski mesajlar
        self.notlar = []      # bir sonraki soruda modele iletilecek Robu notları (geri alma…)
        self.araclar = True  # model araç çağırmayı destekliyor mu
        self.gorsel = False  # model resim görebiliyor mu
        self.sifirla()

    def _tarayici_acik(self):
        return self.araclar and bool(self.ayar.get("tarayici", True))

    def sifirla(self):
        istem = sistem_istemi(self.ayar["klasor"], self.araclar, self.gorsel,
                              self._tarayici_acik(), self.araclar and belgeler.dizin_var())
        self.mesajlar = [{"role": "system", "content": istem}]
        self.arsiv = []

    def durdur(self):
        """Acil durdurma: süren komutu öldürür, Ollama bağlantısını hemen keser."""
        self.dur.set()
        p = self._surec
        if p is not None and p.poll() is None:
            _grubu_oldur(p)
        for baglanti in list(self._yanit):
            try:  # bekleyen soketi kapat; Ollama bağlantı kopunca üretimi bırakır
                baglanti.sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass

    def gecmis(self):
        """Kaydedilecek mesajlar: arşivlenenler dahil, kısaltılmış çıktıların tam hâliyle.
        Sistem istemi her açılışta yeniden üretilir; resim verisi dosyayı şişirmesin diye
        atılır (yolu `robu_resim` alanında kalır)."""
        sonuc = []
        for m in self._tum()[1:]:
            k = {a: d for a, d in m.items() if a not in ("images", "robu_tam")}
            if "robu_tam" in m:
                k["content"] = m["robu_tam"]
            sonuc.append(k)
        return sonuc

    def gecmisi_yukle(self, mesajlar):
        self.mesajlar = self.mesajlar[:1] + [dict(m) for m in mesajlar]
        self.arsiv = []

    def _tum(self):
        """Arşivlenenler dahil bütün mesajlar. Güvenlik kararları (internet içeriği okundu mu,
        onay isteme denildi mi) buna bakar; bağlam kırpılınca sıfırlanmasınlar."""
        return self.mesajlar[:1] + self.arsiv + self.mesajlar[1:]

    # ---------- bağlam penceresi

    def baglam_siniri(self):
        return int(self.ayar.get("baglam") or OLLAMA_VARSAYILAN_BAGLAM)

    def baglam_tahmini(self):
        """Modele gidecek istemin yaklaşık token sayısı (araç tanımları dahil)."""
        n = len(json.dumps(self._govde([]).get("tools", []), ensure_ascii=False)) / 3.5
        for m in self.mesajlar:
            n += 4 + len(m.get("content") or "") / KARAKTER_TOKEN
            if m.get("tool_calls"):
                n += len(json.dumps(m["tool_calls"], ensure_ascii=False)) / KARAKTER_TOKEN
            n += RESIM_TOKEN * len(m.get("images") or ())
        return int(n)

    def _sigdir(self):
        """İstem, bağlamın (cevap payı düşülmüş) %85'ini aşarsa %60'a indirir; indirdiyse True.

        Ollama aynı öneki yeniden işlemediği için kırpma seyrek ve toplu yapılır: önek her
        değiştiğinde istemin tamamı CPU'da baştan işlenir. Sıra: (1) son iki araç çıktısı
        dışındakileri kısalt ve son resim mesajı dışındaki resimleri at, (2) yetmezse en eski
        konuşma turlarını arşive taşı. Son tur (şu anki soru) hiç arşivlenmez. Kayıtta her şey
        tam kalır (bkz. gecmis).
        """
        sinir = self.baglam_siniri() - CEVAP_PAYI
        if self.baglam_tahmini() <= sinir * 0.85:
            return False
        araclar = [m for m in self.mesajlar if m.get("role") == "tool"]
        for m in araclar[:-2]:
            if len(m["content"]) > 400 and "robu_tam" not in m:
                m["robu_tam"] = m["content"]
                m["content"] = m["content"][:300] + "\n…(eski çıktı; bağlam için kısaltıldı)"
        resimli = [m for m in self.mesajlar if m.get("images")]
        for m in resimli[:-1]:
            del m["images"]
        while self.baglam_tahmini() > sinir * 0.6:
            turlar = [i for i, m in enumerate(self.mesajlar) if self._tur_basi_mi(m)]
            if len(turlar) < 2:
                break
            self.arsiv += self.mesajlar[1:turlar[1]]
            del self.mesajlar[1:turlar[1]]
        return True

    @staticmethod
    def _tur_basi_mi(m):
        return m.get("role") == "user" and not m.get("robu_hatirlatma") and "robu_resim" not in m

    def arac_destegi(self, var, gorsel=False):
        """Model değişince çağrılır; sistem istemi buna göre güncellenir."""
        self.araclar = var
        self.gorsel = gorsel and var
        self.mesajlar[0]["content"] = sistem_istemi(self.ayar["klasor"], var, self.gorsel,
                                                    self._tarayici_acik(),
                                                    var and belgeler.dizin_var())

    def _govde(self, mesajlar, **secenek):
        mesajlar = [{k: v for k, v in m.items()
                     if k not in ("robu_tam", "robu_geri_al", "robu_uyari")}
                    for m in mesajlar]
        govde = {"model": self.ayar["model"], "messages": mesajlar,
                 "think": bool(self.ayar["dusunme"])}
        if self.ayar.get("baglam"):  # isit ile aynı olmalı; değişirse Ollama modeli yeniden yükler
            secenek = dict(secenek, num_ctx=int(self.ayar["baglam"]))
        thread = self.ayar.get("model_thread")
        if thread is not None:
            if isinstance(thread, bool) or not isinstance(thread, int) or thread < 1:
                raise ValueError("model_thread pozitif tam sayı ya da null olmalı")
            secenek.setdefault("num_thread", thread)
        if self.ayar.get("model_keep_alive") is not None:
            govde["keep_alive"] = self.ayar["model_keep_alive"]
        if self.araclar:
            govde["tools"] = ARACLAR + dosyalar.ARACLAR + ([RESIM_ARACI] if self.gorsel else []) + \
                (TARAYICI_ARACLARI if self._tarayici_acik() else []) + \
                ([belgeler.ARAC] if belgeler.dizin_var() else [])
        if secenek:
            govde["options"] = secenek
        return govde

    def isit(self):
        """Modeli belleğe yükler ve sistem istemini önbelleğe alır.

        Aynı önek (sistem + araçlar) sonraki isteklerde yeniden işlenmez,
        böylece ilk soru hızlı cevaplanır.
        """
        ollama = Ollama(self.ayar["ollama"])
        try:
            for _ in ollama.sohbet_akisi(self._govde(self.mesajlar[:1], num_predict=1)):
                pass
        except Exception as hata:
            # Bazı sohbet şablonları (ör. Qwen3.5) kullanıcı mesajı olmayan isteği reddeder
            # ("No user query found in messages"); model yüklenmiştir ama ısınma 500 döner.
            # Kısa bir kullanıcı mesajıyla bir kez daha dene: sistem öneki yine önbelleğe girer.
            try:
                yedek = self.mesajlar[:1] + [{"role": "user", "content": "merhaba"}]
                for _ in ollama.sohbet_akisi(self._govde(yedek, num_predict=1)):
                    pass
            except Exception:
                raise hata from None

    def not_ekle(self, metin):
        """Kullanıcının arayüzde yaptığı (ör. geri alma) bir şeyi bir sonraki soruda modele
        bildirir; model dosyayı hâlâ yazılmış sanmasın."""
        self.notlar.append(metin)

    def calistir(self, metin):
        if self.olcum:
            self.olcum("input_accepted")
        self.dur.clear()
        if self.notlar:
            self.mesajlar.append({"role": "user", "robu_hatirlatma": True,
                                  "content": "(Robu notu: " + " ".join(self.notlar) + ")"})
            self.notlar = []
        self.mesajlar.append({"role": "user", "content": metin})
        ollama = Ollama(self.ayar["ollama"], self.olcum)
        self.olay("basladi")
        try:
            hatirlatildi = False
            for _ in range(int(self.ayar["adim_siniri"])):
                cagrilar = self._adim_tekrarli(ollama)
                if self.dur.is_set():
                    self.olay("durduruldu")
                    return
                if not cagrilar and not self.mesajlar[-1].get("content", "").strip() \
                        and not hatirlatildi:
                    # Küçük modeller araç sonrası bazen boş cevapla bitiriyor; bir kez dürt.
                    hatirlatildi = True
                    self.mesajlar.pop()
                    self.mesajlar.append({"role": "user", "content": (
                        "(Robu: Boş cevap verdin. Şimdiye kadar gördüklerine dayanarak "
                        "kullanıcıya cevap ver ya da görevi bitirmek için bir araç kullan.)"),
                        "robu_hatirlatma": True})
                    continue
                if not cagrilar:
                    son = self.mesajlar[-1]
                    temiz = teklifleri_temizle(son.get("content", ""))
                    arac_sonucu = self._son_arac_sonucu()
                    if _TEKLIF.search(_kucult(temiz)) and arac_sonucu is not None:
                        # cevap yalnızca "Başka bir şey ister misin?" ise: sonucu kısa söyle
                        temiz = "Son işlem hata verdi; ayrıntılar yukarıdaki kartta." \
                            if arac_hatasi_mi(arac_sonucu) else "Tamam, yapıldı."
                    if temiz != son.get("content", "").strip():
                        son["content"] = temiz
                        self.olay("metin", temiz)  # ekrandaki akmış metni de düzelt
                    if arac_sonucu is not None and arac_hatasi_mi(arac_sonucu) \
                            and basari_iddiasi_mi(temiz):
                        son["robu_uyari"] = YANILTICI_BASARI
                    self.olay("bitti")
                    return
                for i, c in enumerate(cagrilar):
                    sonuc = self._arac(c)
                    if sonuc == RET:
                        # aynı adımdaki diğer çağrılar cevapsız kalmasın
                        for d in cagrilar[i + 1:]:
                            self._sonuc("Kullanıcı önceki işlemi reddettiği için yapılmadı.",
                                        d.get("function", {}).get("name", "komut"))
                        self.mesajlar.append({"role": "assistant", "content": RET_CEVABI})
                        self.olay("metin", RET_CEVABI)
                        self.olay("bitti")
                        return
                    if sonuc:
                        return
            self.olay("hata", "Adım sınırına ulaşıldı; görevi daha küçük parçalara bölmeyi dene.")
        except Exception as e:  # arayüz çökmesin
            if self.dur.is_set():  # bağlantıyı durdurma kesti; hata değil
                self.olay("durduruldu")
            elif cokme_mi(e):
                self.olay("hata", COKME_METNI)
            elif isinstance(e, urllib.error.URLError):
                self.olay("hata", f"Ollama'ya ulaşılamadı: {e.reason}")
            else:
                self.olay("hata", f"{type(e).__name__}: {e}")
        finally:
            self._yanit.clear()
            if self.olcum:
                self.olcum("request_completed")

    def _son_arac_sonucu(self):
        """Bu turdaki (son kullanıcı sorusundan beri) son araç sonucu; yoksa None."""
        for m in reversed(self.mesajlar):
            if m.get("role") == "tool":
                return m.get("content", "")
            if self._tur_basi_mi(m):
                return None
        return None

    def _bu_turda_islem_var(self):
        return self._son_arac_sonucu() is not None

    def _arac_adlari(self):
        return {a["function"]["name"] for a in self._govde([]).get("tools", [])}

    def _adim_tekrarli(self, ollama, bekle=5):
        """Ollama adım sırasında çökerse diğer modelleri bellekten boşaltıp bir kez yeniden
        dener (systemd Ollama'yı birkaç saniyede yeniden başlatır). Yarım kalan cevap geçmişe
        eklenmez; _adim mesajı ancak akış bitince ekler."""
        try:
            return self._adim(ollama)
        except Exception as e:
            if self.dur.is_set() or not cokme_mi(e):
                raise
        self.olay("uyari", "Ollama yanıt vermeyi bıraktı (büyük olasılıkla bellek yetmedi); "
                           "yeniden deneniyor…")
        time.sleep(bekle)
        try:
            for ad in ollama.yuklu():
                if ad != self.ayar["model"]:
                    ollama.bosalt(ad)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return self._adim(ollama)

    def _adim(self, ollama):
        kirpildi = self._sigdir()
        t0 = time.perf_counter()
        icerik, gorunen, cagrilar, son = "", "", [], {}
        govde = self._govde(self.mesajlar)
        adlar = {a["function"]["name"] for a in govde.get("tools", [])}
        if self.olcum:
            self.olcum("prompt_ready")
        for parca in ollama.sohbet_akisi(govde, self._yanit):
            if self.dur.is_set():
                break
            m = parca.get("message", {})
            if m.get("tool_calls"):
                cagrilar.extend(m["tool_calls"])
            if m.get("content"):
                icerik += m["content"]
                if not cagrilar and not arac_metni_olabilir(icerik, adlar):
                    self.olay("metin", icerik)
                    gorunen = icerik
                    if self.olcum:
                        self.olcum("first_text_callback")
            if parca.get("done"):
                son = parca
                break
        if self.dur.is_set():
            return []
        if not son:
            # EOF başarı değildir. Yarım araç JSON'u/geçmiş kesinleşmesin.
            raise RuntimeError("Ollama akışı tamamlanmadan kesildi")
        for cagri in cagrilar:
            fn = cagri.get("function", {})
            arg = fn.get("arguments", {})
            if isinstance(arg, str):
                try:
                    arg = json.loads(arg)
                except ValueError as e:
                    raise RuntimeError("Ollama geçersiz araç argümanı döndürdü") from e
                fn["arguments"] = arg
            if not isinstance(arg, dict):
                raise RuntimeError("Ollama araç argümanı bir nesne olmalı")
        if not cagrilar and self.araclar:
            metin_cagrisi = metindeki_arac_cagrisi(icerik, adlar)
            if metin_cagrisi:  # model aracı çağırmak yerine çağrıyı yazdı: yine de çalıştır
                cagrilar, icerik = [metin_cagrisi], ""
        if not cagrilar and icerik and gorunen != icerik:
            self.olay("metin", icerik)
            if self.olcum and icerik.strip():
                self.olcum("first_text_callback")
        mesaj = {"role": "assistant", "content": icerik}
        if cagrilar:
            mesaj["tool_calls"] = cagrilar
        self.mesajlar.append(mesaj)
        if son:
            uretilen = son.get("eval_count", 0)
            sure_ns = son.get("eval_duration", 0) or 1
            self.olay("adim_bitti", {
                "sure": time.perf_counter() - t0,
                "istem": son.get("prompt_eval_count", 0),
                "uretilen": uretilen,
                "hiz": uretilen / sure_ns * 1e9,
                "baglam": self.baglam_tahmini(),
                "baglam_siniri": self.baglam_siniri(),
                "kirpildi": kirpildi,
                **{k: son[k] for k in ("load_duration", "prompt_eval_duration",
                                      "prompt_eval_cached_count", "eval_duration",
                                      "total_duration") if k in son},
            })
        return cagrilar

    def _arac(self, cagri):
        """Bir araç çağrısını işler; durdurulduysa True döner."""
        fn = cagri.get("function", {})
        arg = fn.get("arguments") or {}
        if isinstance(arg, str):
            try:
                arg = json.loads(arg)
            except ValueError:
                arg = {"cmd": arg}
        kimlik = id(cagri)
        if fn.get("name") == "resim_bak" and self.gorsel:
            return self._resim(kimlik, (arg.get("yol") or "").strip())
        if fn.get("name") in TARAYICI_ADLARI and self._tarayici_acik():
            return self._tarayici(kimlik, fn["name"], arg)
        if fn.get("name") in dosyalar.ADLAR:
            return self._dosya(kimlik, fn["name"], arg)
        if fn.get("name") == "belge_ara":
            return self._belge(kimlik, str(arg.get("sorgu") or "").strip())
        cmd = (arg.get("cmd") or "").strip()
        if fn.get("name") != "komut" or not cmd:
            self._sonuc("Bilinmeyen araç ya da boş komut. Sadece `komut` aracını kullan.")
            return False
        tehlikeli, hassas = tehlikeli_mi(cmd), hassas_mi(cmd)
        normalde = (self.ayar.get("okuma_otomatik", True) and okuma_komutu_mu(cmd)) or \
            (self.ayar["onaysiz"] and not tehlikeli)
        otomatik, baslik = self._onay_karari(normalde, hassas)
        self.olay("komut", kimlik, cmd, tehlikeli or hassas, otomatik, baslik)
        izin = otomatik or self.onay(cmd)
        if self.dur.is_set():
            # geçmişte cevapsız araç çağrısı kalmasın; sohbet sonra sürdürülebilir
            self._sonuc("Kullanıcı görevi durdurdu.")
            self.olay("durduruldu")
            return True
        if not izin:
            return self._reddedildi(kimlik, "komut")
        baslangic = time.time()
        cikti = self._kabuk(cmd)
        self.olay("cikti", kimlik, cikti, False)
        if self.dur.is_set():
            self._sonuc("Kullanıcı görevi durdurdu; komut sonlandırıldı.")
            self.olay("durduruldu")
            return True
        kayit = geri_al.komut_kaydi(cmd, self.ayar["klasor"], baslangic)
        if kayit:
            self.olay("geri_alinabilir", kimlik, kayit)
        sinir = int(self.ayar["cikti_siniri"])
        if len(cikti) > sinir:
            cikti = cikti[:sinir] + "\n...(kısaltıldı)"
        self._sonuc(cikti)
        if kayit:  # sohbetle saklanır; yeniden açılınca da Geri al düğmesi çıkar
            self.mesajlar[-1]["robu_geri_al"] = kayit
        return False

    def _reddedildi(self, kimlik, ad, ek=""):
        """Kullanıcı işlemi reddetti: görev burada biter, model alternatif önermez."""
        self.olay("cikti", kimlik, "", True)
        self._sonuc("Kullanıcı reddetti; işlem durduruldu." + ek, ad)
        return RET

    def _onay_karari(self, normalde, hassas, baslik=None, durum=True):
        """Bir işlem sormadan yapılsın mı: (otomatik, kart başlığı).

        `normalde`: ayarlara göre sormadan yapılır mıydı. Gizli bilgiye dokunan ya da internet
        içeriği okunduktan sonraki işlemler sorulur; "bu sohbette onay isteme" hepsini aşar.
        `durum`: otomatikse kartta gösterilecek metin (True: arayüzün varsayılanı).
        """
        hassas_baslik = "⚠  Gizli bilgilere dokunan işlem"
        if self.onaysiz_sohbet():
            return "Bu sohbette onay istenmiyor; yapılıyor…", hassas_baslik if hassas else baslik
        if hassas:
            return False, hassas_baslik
        if normalde and self._web_icerigi_var():
            return False, (baslik or "⚙  Komut") + " · internetten içerik okunduğu için onay gerekiyor"
        return (durum if normalde else False), baslik

    def _belge(self, kimlik, sorgu):
        """Belgelerde anlamsal arama. Okuma sayılır (dosya_oku gibi)."""
        aciklama = f"Ara: {sorgu}"
        otomatik, baslik = self._onay_karari(bool(self.ayar.get("okuma_otomatik", True)),
                                             False, "📚  Belge arama", "Belgelerde aranıyor…")
        self.olay("komut", kimlik, aciklama, False, otomatik, baslik)
        izin = otomatik or self.onay(aciklama)
        if self.dur.is_set():
            self._sonuc("Kullanıcı görevi durdurdu.", "belge_ara")
            self.olay("durduruldu")
            return True
        if not izin:
            return self._reddedildi(kimlik, "belge_ara")
        try:
            sonuc = belgeler.ara(Ollama(self.ayar["ollama"]), self.ayar.get("belge_modeli")
                                 or "embeddinggemma", sorgu, sinir=int(self.ayar["cikti_siniri"]))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            sonuc = f"Belge araması yapılamadı: {e}"
        self.olay("cikti", kimlik, sonuc, False)
        self._sonuc(sonuc, "belge_ara")
        return False

    def _dosya(self, kimlik, ad, arg):
        """dosya_oku / dosya_yaz / dosya_degistir; durdurulduysa True döner."""
        # var olması beklenen dosyada yanlış yolu (~/Desktop/… gibi) düzeltmeyi dene
        beklenen = ad != "dosya_yaz" or dosyalar._dogru(arg.get("ekle"))
        yol = dosyalar.tam_yol(arg.get("yol"), self.ayar["klasor"], var_olmali=beklenen)
        duz = dosyalar.tam_yol(arg.get("yol"), self.ayar["klasor"])
        yol_notu = f"(Not: {arg.get('yol')} yok; {yol} kullanıldı.)\n" if yol != duz else ""
        gosterim = dosyalar.aciklama(ad, arg)
        hassas = hassas_mi(yol)
        if ad == "dosya_oku":
            otomatik, baslik = self._onay_karari(bool(self.ayar.get("okuma_otomatik", True)),
                                                 hassas, "📄  Dosya okuma", "Sormadan okunuyor…")
        else:
            baslik = "✎  Dosya yazma" if ad == "dosya_yaz" else "✎  Dosya değiştirme"
            yeni, onizleme, hata = dosyalar.hazirla(ad, yol, arg)
            if hata:
                self.olay("komut", kimlik, gosterim, False, "Yapılamadı", baslik)
                self.olay("cikti", kimlik, hata, False)
                self._sonuc(yol_notu + hata, ad)
                return False
            gosterim += "\n" + onizleme
            otomatik, baslik = self._onay_karari(bool(self.ayar["onaysiz"]), hassas, baslik,
                                                 "Sormadan yazılıyor…")
        self.olay("komut", kimlik, gosterim, hassas, otomatik, baslik)
        izin = otomatik or self.onay(gosterim)
        if self.dur.is_set():
            self._sonuc("Kullanıcı görevi durdurdu.", ad)
            self.olay("durduruldu")
            return True
        if not izin:
            return self._reddedildi(kimlik, ad)
        try:
            if ad == "dosya_oku":
                try:
                    satir = int(arg.get("satir") or 1)
                except (TypeError, ValueError):
                    satir = 1
                sonuc = dosyalar.oku(yol, satir, int(self.ayar["cikti_siniri"]))
            else:
                vardi, baslangic = os.path.exists(yol), time.time()
                sonuc = dosyalar.uygula(yol, yeni)
                kayit = geri_al.dosya_kaydi(yol, vardi, baslangic) \
                    if sonuc.startswith("Yazıldı") else None
        except OSError as e:
            sonuc, kayit = f"Yapılamadı: {e}", None
        sonuc = yol_notu + sonuc
        self.olay("cikti", kimlik, sonuc, False)
        if ad != "dosya_oku" and kayit:
            self.olay("geri_alinabilir", kimlik, kayit)
        self._sonuc(sonuc, ad)
        if ad != "dosya_oku" and kayit:
            self.mesajlar[-1]["robu_geri_al"] = kayit
        return False

    def _resim(self, kimlik, yol):
        """Resim(ler)i okuyup modele gösterir. Salt okunur olduğu için onay istenmez."""
        if yol.strip(" '\"").lower() in EKRAN_ADLARI:
            return self._ekran(kimlik)
        tam = os.path.join(self.ayar["klasor"], os.path.expanduser(yol))
        if not os.path.exists(tam):  # ~/sekiller gibi yanlış yol: yakın yolu dene
            tam = dosyalar.yakin_yol(yol.strip(), self.ayar["klasor"]) or tam
        yollar, hata = resim_yollari(tam)
        self.olay("resim", kimlik, yollar or [tam], None)
        return self._resimleri_goster(kimlik, yollar, hata)

    def _ekran(self, kimlik):
        """Ekran görüntüsü alıp modele gösterir. Okuma sayılır: varsayılan otomatik, ama
        internet içeriği okunduktan sonra onaya düşer (ekranda kişisel bilgiler olabilir)."""
        aciklama, baslik = "Ekran görüntüsü al", "🖥  Ekran görüntüsü"
        otomatik, kart_baslik = self._onay_karari(bool(self.ayar.get("okuma_otomatik", True)),
                                                  False, baslik)
        kart = not otomatik
        if kart:
            self.olay("komut", kimlik, aciklama, False, False, kart_baslik)
            izin = self.onay(aciklama)
            if self.dur.is_set():
                self._sonuc("Kullanıcı görevi durdurdu.", "resim_bak")
                self.olay("durduruldu")
                return True
            if not izin:
                return self._reddedildi(kimlik, "resim_bak")
        yol, hata = ekran_goruntusu()
        if hata:
            if not kart:
                self.olay("komut", kimlik, aciklama, False, "Yapılamadı", baslik)
            self.olay("cikti", kimlik, hata, False)
            self._sonuc(hata, "resim_bak")
            return False
        if kart:
            self.olay("cikti", kimlik, "Alındı.", False)
        self.olay("resim", kimlik, [yol], baslik)
        return self._resimleri_goster(kimlik, [yol], None, EKRAN_BOYUTU)

    def _resimleri_goster(self, kimlik, yollar, hata, en_buyuk=1024):
        veriler = []
        for y in yollar:
            veri, hata = resim_hazirla(y, en_buyuk)
            if hata:
                break
            veriler.append(veri)
        self.olay("resim_sonuc", kimlik, hata)
        if hata:
            self._sonuc(hata, "resim_bak")
            return False
        adlar = [os.path.basename(y) for y in yollar]
        self._sonuc(f"{len(adlar)} resim açıldı; resimler bir sonraki mesajda bu sırayla: "
                    + ", ".join(adlar), "resim_bak")
        # Araç mesajı resim taşıyamadığı için resimler ayrı bir kullanıcı mesajıyla gider
        self.mesajlar.append({"role": "user", "content": "[Resimler, sırayla: "
                              + ", ".join(adlar) + "]",
                              "images": veriler, "robu_resim": yollar})
        return False

    def _tarayici(self, kimlik, ad, arg):
        from . import tarayici  # Chrome yalnızca gerektiğinde açılır
        aciklama = tarayici_aciklamasi(ad, arg)
        giden = {"web_ara": arg.get("sorgu"), "sayfa_ac": arg.get("adres"),
                 "yaz": arg.get("metin")}.get(ad)
        onaysiz = self.onaysiz_sohbet()
        internet_onayi = ad in ("web_ara", "sayfa_ac")
        sizinti = giden and not onaysiz and sizinti_parcasi(str(giden), *self._yerel_ve_bilinen())
        uyari = f"Chrome · bilgisayardaki bilgi internete gidebilir: “{sizinti}…”" \
            if sizinti else None
        self.olay("tarayici", kimlik, aciklama, uyari)
        # Arama/adres açma izni, genel onaysız ayarlardan ve sohbet kestirmesinden bağımsızdır.
        if internet_onayi or sizinti or (not onaysiz and self.ayar.get("tarayici_onay") and ad in ("tikla", "yaz")):
            izin = self.onay(aciklama)
            if self.dur.is_set():
                self._sonuc("Kullanıcı görevi durdurdu.", ad)
                self.olay("durduruldu")
                return True
            if not izin:
                return self._reddedildi(kimlik, ad, " Bilgisayardaki bilgileri internete "
                                        "gönderme." if sizinti else "")
        t = tarayici.tarayici()
        try:
            if ad == "web_ara":
                sonuc = t.ara(str(arg.get("sorgu", "")))
            elif ad == "sayfa_ac":
                sonuc = t.ac(str(arg.get("adres", "")))
            elif ad == "sayfa_oku":
                sonuc = t.oku(int(arg.get("parca") or 1))
            elif ad == "tikla":
                sonuc = t.tikla(int(arg.get("no")))
            else:
                gonder = arg.get("gonder") in (True, "true", "True", 1)
                sonuc = t.yaz(int(arg.get("no")), str(arg.get("metin", "")), gonder)
        except (tarayici.TarayiciHatasi, OSError, ValueError, TypeError) as e:
            sonuc = f"Tarayıcı hatası: {e}"
        self.olay("cikti", kimlik, sonuc, False)
        self._eski_sayfalari_kisalt(sonuc)
        self._sonuc(sonuc, ad)
        return False

    def onaysiz_sohbet(self):
        """Kullanıcı bu sohbette "bu sohbette onay isteme" yazdıysa (ve sonra "bu sohbette
        onay iste" ile geri almadıysa) True: arama ve sayfa açma dışında onay istenmez. Yalnızca
        kullanıcının kendi yazdığı mesajlara bakılır; web sayfaları ve araç çıktıları
        (rol: tool) ya da Robu'nun eklediği mesajlar bu durumu açamaz."""
        durum = False
        for m in self._tum():
            if m.get("role") == "user" and not m.get("robu_hatirlatma") \
                    and "robu_resim" not in m:
                k = onay_kestirmesi(m.get("content", ""))
                if k is not None:
                    durum = k
        return durum

    def ret(self, metin):
        """Ret mesajını modele göndermeden cevaplar; cevabı döndürür."""
        return self._yerel_cevap(metin, RET_CEVABI)

    def _yerel_cevap(self, metin, cevap):
        self.mesajlar += [{"role": "user", "content": metin},
                          {"role": "assistant", "content": cevap}]
        return cevap

    def kestirme(self, metin):
        """Yalnızca kestirmeden ibaret mesajı modele göndermeden cevaplar; cevabı döndürür."""
        cevap = ("Tamam, bu sohbette komutlar için onay istemeyeceğim. "
                 "İnternette arama ve sayfa açma için yine izin isteyeceğim. "
                 "Geri almak için: “bu sohbette onay iste”." if onay_kestirmesi(metin) else
                 "Tamam, bu sohbette yeniden onay isteyeceğim.")
        return self._yerel_cevap(metin, cevap)

    def _web_icerigi_var(self):
        """Sohbete internetten metin girdi mi? Sayfadaki gizli bir talimat (prompt injection)
        modeli yönlendirebilir; o andan sonra hiçbir komut sormadan çalışmaz. Geçmiş
        kaydedilip yeniden açılsa da geçerlidir (araç mesajları saklanır)."""
        return any(m.get("role") == "tool" and m.get("tool_name") in TARAYICI_ADLARI
                   for m in self._tum())

    def _yerel_ve_bilinen(self):
        """(komut çıktıları, kullanıcının yazdıkları + sistem istemi + web sayfaları)"""
        yerel, bilinen = [], []
        for m in self._tum():
            rol, ad = m.get("role"), m.get("tool_name")
            if rol == "tool" and ad in ("komut", "dosya_oku", "belge_ara"):
                yerel.append(m.get("robu_tam", m["content"]))
            elif rol in ("system", "user") or (rol == "tool" and ad in TARAYICI_ADLARI):
                bilinen.append(m.get("content", ""))
        return "\n".join(yerel), "\n".join(bilinen)

    @staticmethod
    def _adres(ozet):
        satir = ozet.split("\n")[1] if ozet.count("\n") >= 1 else ""
        return satir[len("Adres: "):] if satir.startswith("Adres: ") else None

    def _eski_sayfalari_kisalt(self, yeni):
        """Başka sayfalara ait önceki özetleri başlık+adres satırına indirir; bağlam
        şişmesin. Aynı sayfanın parçaları (sayfa_oku parca=2…) birbirini silmez."""
        yeni_adres = self._adres(yeni)
        for m in self.mesajlar:
            if m.get("role") == "tool" and m.get("tool_name") in TARAYICI_ADLARI \
                    and m["content"].startswith("Sayfa: ") and "\n--- " in m["content"] \
                    and self._adres(m["content"]) != yeni_adres:
                m["content"] = "\n".join(m["content"].split("\n")[:2]) + "\n(eski sayfa özeti)"

    def _kabuk(self, cmd, sure=None):
        """Komutu kendi süreç grubunda çalıştırır; durdurulursa grubun tamamı ölür."""
        sure = sure or int(self.ayar.get("komut_suresi") or 120)
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors="replace", cwd=self.ayar["klasor"],
                             start_new_session=True)
        self._surec = p
        bitis = time.time() + sure
        try:
            while True:
                try:
                    cikti, _ = p.communicate(timeout=0.2)
                    if self.dur.is_set():  # durdurma süreci başka iş parçacığından öldürdü
                        return "Komut kullanıcı tarafından durduruldu."
                    cikti = cikti.strip()
                    if p.returncode:
                        # başa: uzun çıktı sondan kısaltılınca kaybolmasın; model başarı sanmasın
                        durum = (f"(çıkış kodu {p.returncode}: komut hata verdi ya da "
                                 "sonuç bulamadı)")
                        return f"{durum}\n{cikti}" if cikti else durum
                    return cikti or "(çıktı yok)"
                except subprocess.TimeoutExpired:
                    if self.dur.is_set():
                        _grubu_oldur(p)
                        p.communicate()
                        return "Komut kullanıcı tarafından durduruldu."
                    if time.time() > bitis:
                        _grubu_oldur(p)
                        p.communicate()
                        return f"Komut {sure} saniyede bitmedi; sonlandırıldı."
        finally:
            self._surec = None

    def _sonuc(self, metin, arac="komut"):
        self.mesajlar.append({"role": "tool", "tool_name": arac, "content": metin})
