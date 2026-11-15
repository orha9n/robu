"""Hugging Face'te GGUF model arama.

İndirmeyi Ollama yapar: `hf.co/<depo>:<nicemleme>` adıyla /api/pull.
"""
import json
import re
import urllib.parse
import urllib.request

API = "https://huggingface.co/api"

# Dosya adındaki nicemleme etiketi: Q4_K_M, IQ4_XS, UD-Q4_K_XL, BF16, F16...
NICEMLEME = re.compile(r"((?:UD-)?(?:I?Q\d(?:_[A-Z0-9]+)*|BF16|F16|F32))", re.I)
PARCALI = re.compile(r"-\d{5}-of-\d{5}\.gguf$")


def _getir(yol, zaman_asimi=20):
    istek = urllib.request.Request(API + yol, headers={"User-Agent": "robu"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as r:
        return json.load(r)


# Ollama'da sohbet için kullanılabilen türler
TURLER = {
    "metin": ("text-generation",),
    "gorsel": ("image-text-to-text",),
    "hepsi": ("text-generation", "image-text-to-text"),
}
SIRALAR = {"trend": "trendingScore", "indirme": "downloads", "begeni": "likes"}


# Depo adındaki boyut: "27B", "E4B", "2.6B" — "A3B" (aktif parametre) sayılmaz
ADDAKI_BOYUT = re.compile(r"(?<![A-Za-z0-9.])E?(\d+(?:\.\d+)?)B(?![A-Za-z])", re.I)


def parametre_tahmini(depo, gguf_toplam):
    """HF'nin sayısı bazen depodaki küçük bir yardımcı dosyadan (MTP taslağı) gelir;
    depo adındaki boyutla karşılaştırıp büyük olanı kullan."""
    adda = [float(x) * 1e9 for x in ADDAKI_BOYUT.findall(depo.split("/")[-1])]
    return max([gguf_toplam or 0] + adda)


def sigar_mi(parametre, ram=None):
    """Q4_K_M sürümü (~0,6 bayt/parametre) belleğe rahat sığar mı?"""
    return uyum(parametre * 0.6, ram) == "rahat"


def ara(sorgu, tur="hepsi", sira="trend", sigan=True, sinir=30):
    """GGUF sohbet modellerini arar.

    tur: metin|gorsel|hepsi, sira: trend|indirme|begeni,
    sigan: yalnızca bu bilgisayarın belleğine sığanlar (parametre sayısı bilinmeyenler kalır).
    """
    anahtar = SIRALAR[sira]
    sonuc = {}
    for pipeline in TURLER[tur]:  # API tek tür kabul ediyor; türleri ayrı sorgulayıp birleştir
        q = urllib.parse.urlencode([
            ("search", sorgu), ("filter", "gguf"), ("pipeline_tag", pipeline),
            ("sort", anahtar), ("direction", "-1"),
            ("limit", 100 if sigan else sinir),  # filtre sonrası yeterli sonuç kalsın
        ] + [("expand[]", a) for a in ("gguf", "downloads", "likes", "tags",
                                       "pipeline_tag", anahtar)])
        for m in _getir("/models?" + q):
            sonuc[m["id"]] = m
    liste = sorted(sonuc.values(), key=lambda m: m.get(anahtar) or 0, reverse=True)
    ram = toplam_ram()
    cikti = []
    for m in liste:
        parametre = parametre_tahmini(m["id"], (m.get("gguf") or {}).get("total"))
        if sigan and parametre and not sigar_mi(parametre, ram):
            continue
        cikti.append({
            "depo": m["id"],
            "indirme": m.get("downloads", 0),
            "begeni": m.get("likes", 0),
            "parametre": _kisa_sayi(parametre) if parametre else "",
            "yetenekler": yetenekler(m.get("tags", []) + [m.get("pipeline_tag") or ""],
                                     "", m["id"]),
        })
        if len(cikti) >= sinir:
            break
    return cikti


def dosyalar(depo):
    """Depodaki indirilebilir GGUF nicemlemeleri, küçükten büyüğe."""
    liste = _getir(f"/models/{depo}/tree/main")  # Ollama yalnızca kökteki dosyaları çeker
    sonuc, gorulen = [], set()
    for f in liste:
        yol = f.get("path", "")
        ad = yol.rsplit("/", 1)[-1]
        kucuk = ad.lower()
        # görüntü projektörü / taslak (MTP) gibi yardımcı dosyalar model değildir
        if not kucuk.endswith(".gguf") or PARCALI.search(ad) or \
                any(k in kucuk for k in ("mmproj", "mtp", "draft", "imatrix")):
            continue
        m = NICEMLEME.search(ad[:-5])
        if not m:
            continue
        etiket = m.group(1).upper()
        if etiket in gorulen:
            continue
        gorulen.add(etiket)
        sonuc.append({
            "etiket": etiket,
            "boyut": f.get("lfs", {}).get("size") or f.get("size", 0),
            "dosya": yol,
        })
    return sorted(sonuc, key=lambda d: d["boyut"])


def toplam_ram():
    with open("/proc/meminfo") as f:
        for satir in f:
            if satir.startswith("MemTotal:"):
                return int(satir.split()[1]) * 1024
    return 0


def uyum(boyut, ram=None):
    """'rahat' | 'agir' | 'sigmaz' — modelin bu makinedeki durumu."""
    ram = ram or toplam_ram()
    if boyut <= ram * 0.45:
        return "rahat"
    if boyut <= ram * 0.7:
        return "agir"
    return "sigmaz"


def oneri(liste, ram=None):
    """Rahat sığan en iyi Q4 türevini, yoksa rahat sığan en büyüğünü önerir."""
    rahat = [d for d in liste if uyum(d["boyut"], ram) == "rahat"]
    for tercih in ("Q4_K_M", "UD-Q4_K_XL", "Q4_K_S", "IQ4_XS", "Q4_0"):
        for d in rahat:
            if d["etiket"] == tercih:
                return d["etiket"]
    return rahat[-1]["etiket"] if rahat else None


def ollama_adi(depo, etiket):
    return f"hf.co/{depo}:{etiket}"


def _metin_getir(url, zaman_asimi=20):
    istek = urllib.request.Request(url, headers={"User-Agent": "robu"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as r:
        return r.read(200_000).decode("utf-8", "replace")


def _kisa_sayi(n):
    for bolen, ek in ((1e9, "B"), (1e6, "M")):
        if n >= bolen:
            return f"{n / bolen:.1f}".rstrip("0").rstrip(".") + ek
    return str(n)


def yetenekler(etiketler, sablon="", ad=""):
    """Etiketlerden ve sohbet şablonundan okunabilir yetenek listesi çıkarır.

    Dönüş: [(metin, tür)] — tür: 'iyi' | 'bilgi' | 'uyari'
    """
    e = {t.lower() for t in etiketler}
    ad = ad.lower()
    sonuc = []
    if "tools" in sablon:
        sonuc.append(("⚙ Komut çalıştırabilir", "iyi"))
    elif sablon:
        sonuc.append(("💬 Sadece sohbet", "uyari"))
    if "conversational" in e or "text-generation" in e or sablon:
        sonuc.append(("Sohbet", "bilgi"))
    if e & {"image-text-to-text", "vision", "multimodal", "any-to-any"}:
        sonuc.append(("🖼 Görsel anlar", "bilgi"))
    if e & {"audio", "any-to-any", "audio-text-to-text"}:
        sonuc.append(("🔊 Ses anlar", "bilgi"))
    if "think" in sablon or e & {"reasoning", "thinking"}:
        sonuc.append(("🧠 Düşünme modu", "bilgi"))
    if "code" in ad or "coder" in ad or e & {"code", "coding"}:
        sonuc.append(("⌨ Kodlama", "bilgi"))
    if e & {"uncensored", "abliterated", "heretic"} or "uncensored" in ad:
        sonuc.append(("Sansürsüz", "uyari"))
    return sonuc


# Nicemleyenlerin duyuru/kurulum paragrafları: model tanıtımı değil
REKLAM = re.compile(
    r"unsloth|gguf|quantiz|update|guide|please refer|we recommend|click|discord|"
    r"run (it|this|the model)|llama\.cpp|ollama|lm studio|download|benchmark|"
    r"for more details|install|pip |huggingface-cli|thank|^note\b|out-of-memory", re.I)


def _aciklama(readme, sinir=700):
    """Model kartından ilk anlamlı düz yazı paragraflarını çıkarır."""
    if readme.startswith("---"):
        readme = readme.split("---", 2)[-1]
    readme = re.sub(r"```.*?```", "", readme, flags=re.S)
    readme = re.sub(r"<[^>]+>", " ", readme)                    # HTML
    readme = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", readme)        # resimler
    readme = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", readme)     # bağlantılar
    readme = re.sub(r"\[!\w+\]", "", readme)                    # > [!Note]
    paragraflar = []
    for p in re.split(r"\n\s*\n", readme):
        satirlar = [s.strip().lstrip(">").strip() for s in p.strip().splitlines()]
        # madde imleri ("- ", "* "), başlıklar ve tablolar atlanır; **kalın** satırlar kalır
        satirlar = [s for s in satirlar
                    if s and not s.startswith(("#", "|", "<", "- ", "* ", "+ "))]
        metin = re.sub(r"\s+", " ", " ".join(satirlar)).replace("**", "").strip()
        harf = sum(c.isalpha() for c in metin)
        if len(metin) >= 120 and harf / len(metin) > 0.7 and not REKLAM.search(metin):
            paragraflar.append(metin)
        if sum(len(x) for x in paragraflar) >= sinir:
            break
    metin = "\n\n".join(paragraflar)
    return metin if len(metin) <= sinir else metin[:sinir].rsplit(" ", 1)[0] + "…"


def bilgi(depo):
    """Depo hakkında özet: parametre, bağlam, lisans, yetenekler, açıklama."""
    d = _getir(f"/models/{depo}")
    gguf = d.get("gguf") or {}
    kart = d.get("cardData") or {}
    temel = kart.get("base_model")
    if isinstance(temel, list):
        temel = temel[0] if temel else None
    # Asıl tanıtım genelde orijinal modelin kartındadır; önce onu dene.
    aciklama = ""
    for kaynak in filter(None, (temel, depo)):
        try:
            aciklama = _aciklama(_metin_getir(
                f"https://huggingface.co/{kaynak}/raw/main/README.md"))
        except Exception:
            continue
        if aciklama:
            break
    return {
        "parametre": _kisa_sayi(parametre_tahmini(depo, gguf.get("total"))) if (
            gguf.get("total") or ADDAKI_BOYUT.search(depo)) else "",
        "baglam": f"{gguf['context_length'] // 1024}K" if gguf.get("context_length") else "",
        "mimari": gguf.get("architecture", ""),
        "lisans": kart.get("license", ""),
        "temel": temel or "",
        "guncelleme": (d.get("lastModified") or "")[:10],
        "kilitli": bool(d.get("gated")),
        "yetenekler": yetenekler(d.get("tags", []), gguf.get("chat_template", ""), depo),
        "aciklama": aciklama,
    }
