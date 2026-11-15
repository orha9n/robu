"""Modelin dosya araçları: dosya_oku, dosya_yaz, dosya_degistir.

Küçük modeller bash'te dosya yazarken (tırnak, heredoc, kaçış) çok hata yapıyor; bu araçlar
metni olduğu gibi alır. Üstüne yazmadan önce eski dosya çöpe taşınır, yani her değişiklik
geri alınabilir. Yalnızca standart kütüphane.
"""
import difflib
import os
import stat
import subprocess
import tempfile

EN_BUYUK = 2_000_000   # okuma: bundan büyük dosyanın yalnızca başı okunur (bayt)
DUZENLEME_SINIRI = 50_000_000  # yazma/değiştirme: bundan büyük dosyaya dokunulmaz (bayt)
FARK_SATIRI = 40       # onay kartında gösterilen en fazla fark satırı


def _arac(ad, aciklama, ozellikler, zorunlu):
    return {"type": "function", "function": {
        "name": ad, "description": aciklama,
        "parameters": {"type": "object", "properties": ozellikler, "required": zorunlu}}}


ARACLAR = [
    _arac("dosya_oku", "Metin dosyası okur; uzunsa satir ile devam.",
          {"yol": {"type": "string"}, "satir": {"type": "integer"}}, ["yol"]),
    _arac("dosya_yaz", "Dosyaya yazar (yoksa oluşturur); ekle=true sonuna ekler.",
          {"yol": {"type": "string"}, "metin": {"type": "string"},
           "ekle": {"type": "boolean"}}, ["yol", "metin"]),
    _arac("dosya_degistir", "Dosyada bir metin parçasını değiştirir.",
          {"yol": {"type": "string"}, "eski": {"type": "string"},
           "yeni": {"type": "string"}}, ["yol", "eski", "yeni"]),
]
ADLAR = {a["function"]["name"] for a in ARACLAR}


def tam_yol(yol, klasor, var_olmali=False):
    """Mutlak yol; kısayol (symlink) ise gösterdiği dosya — düzenlenen ve gizli dosya denetimine
    giren gerçek dosya o. `var_olmali`: yol yoksa yakin_yol ile düzeltmeyi dener."""
    ham = (yol or "").strip()
    sonuc = os.path.realpath(os.path.join(klasor, os.path.expanduser(ham)))
    if var_olmali and not os.path.exists(sonuc):
        return yakin_yol(ham, klasor) or sonuc
    return sonuc


def yakin_yol(ham, klasor):
    """Küçük modeller yolun başına kendiliğinden ~/ ya da ~/Desktop/ ekleyebiliyor
    (~/rapor.txt, ~/Desktop/notlar.md, hatta /tmp/x yerine ~/tmp/x). Verilen yol yoksa
    çalışma klasörüne göre, ~ olmadan ve yalnızca dosya adıyla dener; tam olarak bir var olan
    dosyaya çıkarsa onu döndürür (birden çok aday varsa tahmin etmez)."""
    adaylar = []
    if ham.startswith("~/"):
        adaylar += [os.path.join(klasor, ham[2:]), "/" + ham[2:]]
    ad = os.path.basename(ham.rstrip("/"))
    if ad:
        adaylar.append(os.path.join(klasor, ad))
    bulunan = {os.path.realpath(a) for a in adaylar if os.path.exists(a)}
    return bulunan.pop() if len(bulunan) == 1 else None


def aciklama(ad, arg):
    """Kartta (ve geçmişte) gösterilecek kısa açıklama."""
    yol = arg.get("yol", "")
    if ad == "dosya_oku":
        return f"Oku: {yol}" + (f" (satır {arg['satir']}…)" if arg.get("satir") else "")
    if ad == "dosya_yaz":
        return ("Sonuna ekle: " if _dogru(arg.get("ekle")) else "Yaz: ") + yol
    return f"Değiştir: {yol}"


def _dogru(deger):
    return deger in (True, "true", "True", 1)


def _metin_oku(yol, tam=False):
    """tam=False (okuma): ilk EN_BUYUK bayt, bozuk baytlar '�' olur.
    tam=True (düzenleme): dosyanın TAMAMI ve kesin UTF-8. Eksik ya da bozulmuş metin dosyaya
    geri yazılırsa veri kaybolur; bu yüzden düzenlemede sınır aşılırsa ya da dosya UTF-8
    değilse hata verilir."""
    with open(yol, "rb") as f:
        if tam:
            boyut = os.fstat(f.fileno()).st_size
            if boyut > DUZENLEME_SINIRI:
                raise ValueError(f"Dosya çok büyük ({boyut / 1e6:.0f} MB); düzenlenmedi.")
            veri = f.read()
        else:
            veri = f.read(EN_BUYUK)
    if b"\0" in veri[:8192]:
        raise ValueError("İkili dosya, metin değil. PDF için `pdftotext -layout f.pdf -`, "
                         "Excel/Word için libreoffice ile dönüştür.")
    if not tam:
        return veri.decode("utf-8", "replace")
    try:
        return veri.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Dosya UTF-8 değil; bozulmasın diye düzenlenmedi.") from None


def oku(yol, satir=1, sinir=3000):
    """Dosyayı `satir`dan başlayarak en fazla `sinir` karakter okur."""
    try:
        metin = _metin_oku(yol)
    except FileNotFoundError:
        return f"Dosya bulunamadı: {yol}"
    except IsADirectoryError:
        return f"Bu bir klasör: {yol}. İçeriği için `komut` ile ls kullan."
    except (OSError, ValueError) as e:
        return f"Okunamadı: {e}"
    satirlar = metin.splitlines()
    if not satirlar:
        return "(boş dosya)"
    try:
        kesik = os.path.getsize(yol) > EN_BUYUK
    except OSError:
        kesik = False
    i = max(1, int(satir or 1)) - 1
    parca, n = [], 0
    while i < len(satirlar) and n + len(satirlar[i]) < sinir:
        parca.append(satirlar[i])
        n += len(satirlar[i]) + 1
        i += 1
    if not parca and i < len(satirlar):  # tek satır sınırdan uzun
        parca, i = [satirlar[i][:sinir]], i + 1
    sonuc = "\n".join(parca)
    if i < len(satirlar):
        sonuc += f"\n…(devamı var: dosya_oku satir={i + 1}; toplam {len(satirlar)} satır)"
    if kesik and i >= len(satirlar) - 1:
        sonuc += (f"\n(Dosya {os.path.getsize(yol) / 1e6:.1f} MB; yalnızca ilk "
                  f"{EN_BUYUK // 1_000_000} MB okunabildi. Gerisi için `komut` ile tail/grep kullan.)")
    return sonuc


def hazirla(ad, yol, arg):
    """Yazma/değiştirmeyi uygulamadan hazırlar: (yeni_icerik, onizleme, hata).

    Önizleme onay kartında gösterilir: var olan dosya için fark, yeni dosya için içerik.
    """
    try:
        eski = _metin_oku(yol, tam=True) if os.path.exists(yol) else None
    except IsADirectoryError:
        return None, "", f"Bu bir klasör: {yol}"
    except (OSError, ValueError) as e:
        return None, "", f"Okunamadı: {e}"
    if ad == "dosya_yaz":
        metin = str(arg.get("metin", ""))
        yeni = (eski or "") + metin if _dogru(arg.get("ekle")) else metin
    else:
        if eski is None:
            return None, "", f"Dosya bulunamadı: {yol}"
        parca, yerine = str(arg.get("eski", "")), str(arg.get("yeni", ""))
        adet = eski.count(parca) if parca else 0
        if adet == 0:
            return None, "", ("Değiştirilecek metin dosyada bulunamadı. Önce dosya_oku ile "
                              "dosyaya bak ve metni boşluklarıyla birlikte aynen ver.")
        if adet > 1:
            return None, "", (f"Metin dosyada {adet} yerde geçiyor; tek bir yeri seçmek için "
                              "çevresindeki satırlarla birlikte daha uzun bir parça ver.")
        yeni = eski.replace(parca, yerine, 1)
    if eski is None:
        satirlar = yeni.splitlines()
        onizleme = f"(yeni dosya, {len(satirlar)} satır)\n" + "\n".join(satirlar[:FARK_SATIRI])
        if len(satirlar) > FARK_SATIRI:
            onizleme += "\n…"
    elif yeni == eski:
        return None, "", "Dosya zaten bu içerikte; değişiklik yok."
    else:
        fark = list(difflib.unified_diff(eski.splitlines(), yeni.splitlines(), lineterm="", n=1))[2:]
        onizleme = "\n".join(fark[:FARK_SATIRI]) + ("\n…" if len(fark) > FARK_SATIRI else "")
    return yeni, onizleme, None


def uygula(yol, yeni):
    """Yeni içeriği yazar; var olan dosyanın eski hâli çöpe taşınır (geri alınabilsin).

    Var olan dosyada içerik önce aynı klasörde geçici dosyaya yazılır ve eski dosyanın izinleri
    (ör. çalıştırma izni, 700) ona kopyalanır; sonra eski dosya çöpe taşınır ve yenisi tek
    adımda yerine konur. Yarıda kalırsa eski dosya yerinde kalır.
    """
    yol = os.path.realpath(yol)
    os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
    if not os.path.exists(yol):
        with open(yol, "x", encoding="utf-8", newline="") as f:
            f.write(yeni)
        return f"Yazıldı: {yol} ({len(yeni.splitlines())} satır)."
    kip = stat.S_IMODE(os.stat(yol).st_mode)
    fd, gecici = tempfile.mkstemp(dir=os.path.dirname(yol), prefix=".robu-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(yeni)
        os.chmod(gecici, kip)
        p = subprocess.run(["gio", "trash", yol], capture_output=True, text=True)
        if p.returncode:
            os.remove(gecici)
            return f"Eski dosya çöpe taşınamadığı için yazılmadı: {p.stderr.strip()}"
        os.replace(gecici, yol)
    except BaseException:
        if os.path.exists(gecici):
            os.remove(gecici)
        raise
    return f"Yazıldı: {yol} ({len(yeni.splitlines())} satır); eski hâli çöp kutusunda."
