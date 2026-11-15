"""Robu'nun yaptığı değişiklikleri geri alma.

Geri alınabilenler: dosya_yaz / dosya_degistir (eski hâli çöpte), `gio trash …` ile çöpe
atılanlar ve basit `mv kaynak hedef` taşımaları. Çöp kutusu freedesktop biçimindedir:
~/.local/share/Trash/{files,info}; info/<ad>.trashinfo dosyasında orijinal yol ve silinme
zamanı yazar. Yalnızca standart kütüphane.
"""
import datetime
import os
import shlex
import shutil
import subprocess
import urllib.parse

COP = os.path.expanduser("~/.local/share/Trash")


class GeriAlinamaz(Exception):
    pass


def cop_ogesi(yol, sonra):
    """`yol`un `sonra` (time.time) anından beri çöpe atılmış en yeni kaydının adı ya da None."""
    klasor = os.path.join(COP, "info")
    try:
        adlar = os.listdir(klasor)
    except OSError:
        return None
    sinir = datetime.datetime.fromtimestamp(sonra - 2)  # DeletionDate saniye hassasiyetinde
    bulunan, en_yeni = None, None
    for ad in adlar:
        if not ad.endswith(".trashinfo"):
            continue
        kayit = {}
        try:
            with open(os.path.join(klasor, ad)) as f:
                for satir in f:
                    if "=" in satir:
                        anahtar, deger = satir.strip().split("=", 1)
                        kayit[anahtar] = deger
            zaman = datetime.datetime.fromisoformat(kayit["DeletionDate"])
        except (OSError, KeyError, ValueError):
            continue
        if urllib.parse.unquote(kayit.get("Path", "")) == yol and zaman >= sinir \
                and (en_yeni is None or zaman > en_yeni):
            bulunan, en_yeni = ad[:-len(".trashinfo")], zaman
    return bulunan


def _copten_cikar(ad, hedef):
    if os.path.lexists(hedef):
        raise GeriAlinamaz(f"{hedef} zaten var; üstüne yazmamak için geri alınmadı.")
    kaynak = os.path.join(COP, "files", ad)
    if not os.path.lexists(kaynak):
        raise GeriAlinamaz(f"{os.path.basename(hedef)} artık çöp kutusunda değil.")
    os.makedirs(os.path.dirname(hedef), exist_ok=True)
    shutil.move(kaynak, hedef)
    try:
        os.remove(os.path.join(COP, "info", ad + ".trashinfo"))
    except OSError:
        pass


def _cope_at(yol):
    p = subprocess.run(["gio", "trash", yol], capture_output=True, text=True)
    if p.returncode:
        raise GeriAlinamaz(f"{yol} çöpe taşınamadı: {p.stderr.strip()}")


# ---------------------------------------------------------------- kayıt oluşturma

def dosya_kaydi(yol, vardi, baslangic):
    """dosya_yaz / dosya_degistir sonrası. Eski hâl çöpteyse onu da hatırlar."""
    cop = cop_ogesi(yol, baslangic) if vardi else None
    if vardi and cop is None:
        return None  # eski hâli bulunamadı; geri almak veri kaybettirebilir
    return {"tur": "dosya", "yol": yol, "cop": cop, "aciklama": f"{os.path.basename(yol)} yazıldı"}


def komut_kaydi(cmd, klasor, baslangic):
    """Başarılı bir komut geri alınabilir mi? `gio trash …` ve basit `mv a b` için kayıt."""
    from .cekirdek import _islec_mi, _parcala  # döngüsel içe aktarmayı önle
    try:
        k = _parcala(cmd)
    except ValueError:
        return None
    if not k or any(_islec_mi(s) for s in k):
        return None  # yalnızca tek komut; zincirlerde ne olduğu kesin değil
    ad, arg = os.path.basename(k[0]), k[1:]

    def tam(y):
        return os.path.normpath(os.path.join(klasor, os.path.expanduser(y)))

    if ad == "gio" and arg[:1] == ["trash"]:
        if any(a.startswith("-") for a in arg[1:]):
            return None  # --empty, --restore, --force…
        yollar = []
        for a in arg[1:]:
            if any(c in a for c in "*?["):
                return None  # joker; çöpe atılanlar artık listelenemez (silindiler)
            yollar.append(tam(a))
        ogeler = [(cop_ogesi(y, baslangic), y) for y in yollar]
        ogeler = [(c, y) for c, y in ogeler if c]
        if not ogeler:
            return None
        return {"tur": "cop", "ogeler": ogeler,
                "aciklama": "çöpe atıldı: " + ", ".join(os.path.basename(y) for _, y in ogeler)}
    if ad == "mv":
        dosyalar = [a for a in arg if a not in ("-v", "--verbose")]
        if len(dosyalar) != 2 or any(a.startswith("-") for a in dosyalar):
            return None
        kaynak, hedef = tam(dosyalar[0]), tam(dosyalar[1])
        if os.path.isdir(hedef) and not os.path.lexists(kaynak):
            hedef = os.path.join(hedef, os.path.basename(kaynak))
        if os.path.lexists(kaynak) or not os.path.lexists(hedef):
            return None  # taşıma olmamış
        return {"tur": "tasima", "kaynak": kaynak, "hedef": hedef,
                "aciklama": f"{os.path.basename(kaynak)} → {hedef} taşındı"}
    return None


# ---------------------------------------------------------------- geri alma

def geri_al(kayit):
    """Kaydı geri alır; kullanıcıya gösterilecek kısa sonucu döndürür."""
    tur = kayit["tur"]
    if tur == "dosya":
        yol = kayit["yol"]
        if kayit["cop"] and not os.path.lexists(os.path.join(COP, "files", kayit["cop"])):
            # önce kontrol: yeni hâli çöpe atıp eskisini bulamamak dosyayı ortadan kaldırırdı
            raise GeriAlinamaz(f"{os.path.basename(yol)} dosyasının eski hâli artık çöp "
                               "kutusunda değil.")
        if os.path.lexists(yol):
            _cope_at(yol)  # yeni hâl de çöpe: geri almayı geri almak mümkün olsun
        if kayit["cop"]:
            _copten_cikar(kayit["cop"], yol)
            return f"{os.path.basename(yol)} önceki hâline döndü."
        return f"{os.path.basename(yol)} çöpe taşındı (Robu oluşturmuştu)."
    if tur == "cop":
        geri, hatalar = [], []
        for ad, yol in kayit["ogeler"]:
            try:
                _copten_cikar(ad, yol)
                geri.append(os.path.basename(yol))
            except (GeriAlinamaz, OSError) as e:
                hatalar.append(str(e))
        if not geri:
            raise GeriAlinamaz("; ".join(hatalar))
        return "Çöpten geri getirildi: " + ", ".join(geri) + \
            (" (" + "; ".join(hatalar) + ")" if hatalar else "")
    if tur == "tasima":
        kaynak, hedef = kayit["kaynak"], kayit["hedef"]
        if os.path.lexists(kaynak):
            raise GeriAlinamaz(f"{kaynak} zaten var; üstüne yazmamak için geri alınmadı.")
        if not os.path.lexists(hedef):
            raise GeriAlinamaz(f"{hedef} artık yok.")
        shutil.move(hedef, kaynak)
        return f"{os.path.basename(kaynak)} eski yerine taşındı."
    raise GeriAlinamaz("Bilinmeyen işlem.")


def ozet(cmd):
    """Kayıt açıklamalarında komutu kısa göstermek için."""
    try:
        return " ".join(shlex.split(cmd))[:60]
    except ValueError:
        return cmd[:60]
