"""Sohbet geçmişi: her sohbet ~/.local/share/robu/sohbetler/<kimlik>.json dosyasıdır."""
import json
import os
import subprocess
import time
import uuid

KLASOR = os.path.expanduser("~/.local/share/robu/sohbetler")


def _yol(kimlik):
    return os.path.join(KLASOR, kimlik + ".json")


def yeni_kimlik():
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def baslik_uret(metin, sinir=48):
    tek = " ".join(metin.split())
    return tek if len(tek) <= sinir else tek[:sinir].rsplit(" ", 1)[0] + "…"


def kaydet(sohbet):
    """Yarım yazılmış dosya kalmasın diye önce geçici dosyaya yazar."""
    os.makedirs(KLASOR, exist_ok=True)
    sohbet["guncelleme"] = time.time()
    gecici = _yol(sohbet["id"]) + ".tmp"
    with open(gecici, "w") as f:
        json.dump(sohbet, f, ensure_ascii=False)
    os.replace(gecici, _yol(sohbet["id"]))


def yukle(kimlik):
    with open(_yol(kimlik)) as f:
        return json.load(f)


def listele():
    """Özet liste, en son güncellenen en üstte."""
    if not os.path.isdir(KLASOR):
        return []
    sonuc = []
    for ad in os.listdir(KLASOR):
        if not ad.endswith(".json"):
            continue
        try:
            with open(os.path.join(KLASOR, ad)) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        sonuc.append({
            "id": s["id"],
            "baslik": s.get("baslik") or "Adsız sohbet",
            "guncelleme": s.get("guncelleme", 0),
            "model": s.get("model", ""),
            "soru": sum(1 for m in s.get("mesajlar", []) if m.get("role") == "user"),
        })
    return sorted(sonuc, key=lambda s: s["guncelleme"], reverse=True)


def sil(kimlik):
    """Sohbeti çöp kutusuna taşır (yanlışlıkla silineni geri getirebilmek için)."""
    yol = _yol(kimlik)
    if not os.path.exists(yol):
        return
    p = subprocess.run(["gio", "trash", yol], capture_output=True, text=True)
    if p.returncode:
        raise OSError(p.stderr.strip() or "çöpe taşınamadı")


def _kucult(metin):
    metin = metin.replace("İ", "i").replace("I", "ı").lower()
    return metin


def ara(sorgu):
    """Başlığında ya da mesajlarında `sorgu` geçen sohbetlerin kimlikleri (büyük/küçük harf
    duyarsız). Boş sorgu None döndürür (filtre yok)."""
    sorgu = _kucult(sorgu.strip())
    if not sorgu:
        return None
    bulunan = set()
    if not os.path.isdir(KLASOR):
        return bulunan
    for ad in os.listdir(KLASOR):
        if not ad.endswith(".json"):
            continue
        try:
            with open(os.path.join(KLASOR, ad)) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        metinler = [s.get("baslik") or ""] + [m.get("content") or "" for m in s.get("mesajlar", [])
                                               if m.get("role") in ("user", "assistant")]
        if any(sorgu in _kucult(m) for m in metinler):
            bulunan.add(s["id"])
    return bulunan


def markdown(sohbet):
    """Sohbeti okunabilir Markdown metnine çevirir (dışa aktarma)."""
    tarih = time.strftime("%d.%m.%Y %H:%M", time.localtime(sohbet.get("guncelleme", time.time())))
    satirlar = [f"# {sohbet.get('baslik') or 'Adsız sohbet'}", "",
                f"*{tarih} · {sohbet.get('model', '')}*", ""]
    for m in sohbet.get("mesajlar", []):
        rol, icerik = m.get("role"), (m.get("content") or "").strip()
        if m.get("robu_hatirlatma"):
            continue
        if rol == "user" and m.get("robu_resim"):
            satirlar += ["> 🖼 " + ", ".join(os.path.basename(y) for y in m["robu_resim"]), ""]
        elif rol == "user":
            satirlar += ["## 🙂 Sen", "", icerik, ""]
        elif rol == "assistant":
            if icerik:
                satirlar += ["## 🤖 Robu", "", icerik, ""]
            for c in m.get("tool_calls") or []:
                fn = c.get("function", {})
                arg = fn.get("arguments") or {}
                ozet = arg.get("cmd") if isinstance(arg, dict) and arg.get("cmd") else \
                    json.dumps(arg, ensure_ascii=False)
                satirlar += [f"`{fn.get('name', '?')}`", "", "```", ozet, "```", ""]
        elif rol == "tool":
            kisa = icerik if len(icerik) <= 1500 else icerik[:1500] + "\n…"
            satirlar += ["<details><summary>Çıktı</summary>", "", "```", kisa, "```", "",
                         "</details>", ""]
    return "\n".join(satirlar).rstrip() + "\n"
