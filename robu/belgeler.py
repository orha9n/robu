"""Yerel doküman araması: belgeleri parçalara böler, Ollama'nın embedding modeliyle vektöre
çevirir ve `belge_ara` aracına anlamca en yakın parçaları döndürür.

Dizin ~/.local/share/robu/dizin.json dosyasındadır; vektörler float32 + base64 saklanır.
Dizinleme artımlıdır: değişmeyen dosyalar (aynı boyut ve değişiklik zamanı) yeniden işlenmez.
Yalnızca standart kütüphane: PDF için pdftotext, .docx/.odt için zipfile.
"""
import array
import base64
import json
import math
import os
import re
import subprocess
import zipfile

DIZIN = os.path.expanduser("~/.local/share/robu/dizin.json")
UZANTILAR = (".txt", ".md", ".csv", ".pdf", ".docx", ".odt", ".rtf", ".html", ".htm")
EN_BUYUK_DOSYA = 20_000_000   # bayt; daha büyük dosyalar atlanır
EN_UZUN_METIN = 300_000       # bir dosyadan alınan en fazla karakter
PARCA = 900                   # karakter
ORTUSME = 150
TOPLU = 16                    # tek istekte vektöre çevrilen parça sayısı
ATLANAN_KLASORLER = {"node_modules", "__pycache__", ".git", ".cache", "venv", ".venv"}

ARAC = {"type": "function", "function": {
    "name": "belge_ara",
    "description": "Kullanıcının belgelerinde (PDF, Word, metin) anlamca arar.",
    "parameters": {"type": "object", "properties": {"sorgu": {"type": "string"}},
                   "required": ["sorgu"]}}}


# ---------------------------------------------------------------- metin çıkarma

def _xml_metni(veri):
    veri = re.sub(rb"<(?:w:p|text:p|text:h)[ >/]", b"\n\\g<0>", veri)  # paragraf sonları
    metin = re.sub(rb"<[^>]+>", b"", veri).decode("utf-8", "replace")
    for kod, harf in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"),
                      ("&amp;", "&")):
        metin = metin.replace(kod, harf)
    return metin


def metin_cikar(yol):
    """Dosyanın düz metni; okunamazsa boş metin."""
    uzanti = os.path.splitext(yol)[1].lower()
    try:
        if uzanti == ".pdf":
            p = subprocess.run(["pdftotext", "-layout", yol, "-"], capture_output=True,
                               timeout=60)
            metin = p.stdout.decode("utf-8", "replace")
        elif uzanti in (".docx", ".odt"):
            ic = "word/document.xml" if uzanti == ".docx" else "content.xml"
            with zipfile.ZipFile(yol) as z:
                metin = _xml_metni(z.read(ic))
        else:
            with open(yol, "rb") as f:
                veri = f.read(EN_UZUN_METIN * 2)
            if b"\0" in veri[:4096]:
                return ""
            metin = veri.decode("utf-8", "replace")
            if uzanti in (".html", ".htm", ".rtf"):
                metin = re.sub(r"<[^>]+>|\\[a-z]+\d* ?|[{}]", " ", metin)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile, KeyError):
        return ""
    return metin[:EN_UZUN_METIN]


def parcala(metin):
    """Metni paragraf sınırlarına yakın, örtüşen parçalara böler."""
    metin = re.sub(r"[ \t]+", " ", metin)
    metin = re.sub(r"\n\s*\n+", "\n\n", metin).strip()
    parcalar, bas = [], 0
    while bas < len(metin):
        son = min(len(metin), bas + PARCA)
        if son < len(metin):  # paragraf ya da cümle sonunda kes
            kesim = max(metin.rfind("\n\n", bas + PARCA // 2, son),
                        metin.rfind(". ", bas + PARCA // 2, son))
            if kesim > bas:
                son = kesim + 1
        parca = metin[bas:son].strip()
        if len(parca) > 30:
            parcalar.append(parca)
        if son >= len(metin):
            break
        bas = max(son - ORTUSME, bas + 1)
    return parcalar


# ---------------------------------------------------------------- vektörler

def _normal(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array.array("f", (x / n for x in v))


def _kodla(v):
    return base64.b64encode(v.tobytes()).decode()


def _coz(metin):
    v = array.array("f")
    v.frombytes(base64.b64decode(metin))
    return v


def vektorler(ollama, model, metinler, belge=True):
    """embeddinggemma görev önekleriyle (belge / sorgu) normalleştirilmiş vektörler."""
    if belge:
        girdi = [f"title: none | text: {m}" for m in metinler]
    else:
        girdi = [f"task: search result | query: {m}" for m in metinler]
    return [_normal(v) for v in ollama.vektor(model, girdi)]


# ---------------------------------------------------------------- dizin

def varsayilan_klasorler():
    from .cekirdek import xdg_klasoru
    return [k for k in (xdg_klasoru("DOCUMENTS"), xdg_klasoru("DESKTOP")) if k]


def yukle():
    try:
        with open(DIZIN) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"model": "", "dosyalar": {}}


def kaydet(dizin):
    os.makedirs(os.path.dirname(DIZIN), exist_ok=True)
    gecici = DIZIN + ".tmp"
    with open(gecici, "w") as f:
        json.dump(dizin, f, ensure_ascii=False)
    os.replace(gecici, DIZIN)


def dizin_var():
    """Dizinde en az bir parça var mı? (belge_ara aracı yalnızca o zaman verilir)"""
    try:
        return os.path.getsize(DIZIN) > 100
    except OSError:
        return False


def dosyalari_bul(klasorler):
    from .cekirdek import hassas_mi
    for kok in klasorler:
        for klasor, alt, adlar in os.walk(os.path.expanduser(kok)):
            alt[:] = [a for a in alt if not a.startswith(".") and a not in ATLANAN_KLASORLER]
            for ad in adlar:
                yol = os.path.join(klasor, ad)
                if ad.lower().endswith(UZANTILAR) and not ad.startswith(".") \
                        and not hassas_mi(yol):
                    yield yol


def dizinle(ollama, model, klasorler, ilerleme=None, dur=None):
    """Klasörleri dizinler; değişmeyen dosyaları atlar, silinenleri çıkarır.
    `ilerleme(yapilan, toplam, dosya)` çağrılır. Özet sözlüğü döndürür."""
    dizin = yukle()
    if dizin.get("model") != model:  # başka modelin vektörleri karşılaştırılamaz
        dizin = {"model": model, "dosyalar": {}}
    eski = dizin["dosyalar"]
    yollar = sorted(set(dosyalari_bul(klasorler)))
    yeni, islenen, parca_sayisi = {}, 0, 0
    for i, yol in enumerate(yollar):
        if dur is not None and dur.is_set():
            yeni.update({y: k for y, k in eski.items() if y not in yeni})  # yarım kalmasın
            break
        try:
            st = os.stat(yol)
        except OSError:
            continue
        if st.st_size > EN_BUYUK_DOSYA:
            continue
        kayit = eski.get(yol)
        if kayit and kayit["boyut"] == st.st_size and kayit["zaman"] == st.st_mtime:
            yeni[yol] = kayit
            continue
        if ilerleme:
            ilerleme(i, len(yollar), yol)
        parcalar = parcala(metin_cikar(yol))
        vler = []
        for j in range(0, len(parcalar), TOPLU):
            vler += vektorler(ollama, model, parcalar[j:j + TOPLU])
        yeni[yol] = {"boyut": st.st_size, "zaman": st.st_mtime,
                     "parcalar": [{"metin": p, "v": _kodla(v)} for p, v in zip(parcalar, vler)]}
        islenen += 1
        parca_sayisi += len(parcalar)
        if islenen % 20 == 0:  # uzun dizinlemede ara kayıt
            kaydet({"model": model, "dosyalar": {**eski, **yeni}})
    silinen = len(set(eski) - set(yeni))
    if islenen or silinen or dizin["dosyalar"] != yeni:
        dizin["dosyalar"] = yeni
        kaydet(dizin)
    toplam = sum(len(k["parcalar"]) for k in yeni.values())
    return {"dosya": len(yeni), "islenen": islenen, "silinen": silinen,
            "yeni_parca": parca_sayisi, "parca": toplam}


def ara(ollama, model, sorgu, adet=5, sinir=3000):
    """Sorguya anlamca en yakın parçalar, modele gidecek metin olarak."""
    dizin = yukle()
    if not dizin["dosyalar"]:
        return "Belge dizini boş. Kullanıcı ayarlardan 'Belgeleri dizinle'ye basmalı."
    if dizin.get("model") != model:
        return "Belge dizini başka bir modelle oluşturulmuş; yeniden dizinlenmeli."
    q = vektorler(ollama, model, [sorgu], belge=False)[0]
    skorlar = []
    for yol, kayit in dizin["dosyalar"].items():
        for p in kayit["parcalar"]:
            v = _coz(p["v"])
            skorlar.append((sum(a * b for a, b in zip(q, v)), yol, p["metin"]))
    skorlar.sort(reverse=True)
    satirlar, uzunluk = [], 0
    for skor, yol, metin in skorlar[:adet]:
        parca = f"[{yol}] (benzerlik {skor:.2f})\n{metin}"
        if uzunluk + len(parca) > sinir and satirlar:
            break
        satirlar.append(parca[:sinir])
        uzunluk += len(parca)
    return "\n\n".join(satirlar) if satirlar else "Eşleşen belge parçası yok."


def aciklama(dizin=None):
    """Ayarlarda gösterilecek kısa durum: '12 dosya, 340 parça'."""
    dizin = dizin or yukle()
    d = dizin["dosyalar"]
    return f"{len(d)} dosya, {sum(len(k['parcalar']) for k in d.values())} parça" if d \
        else "henüz dizinlenmedi"

