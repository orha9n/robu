#!/usr/bin/env bash
# Robu kurulumu: bağımlılıkları denetler, eksikleri (sorarak) kurar, menüye ekler.
#
#   ./kur.sh            denetle, eksikleri sorarak kur
#   ./kur.sh --kontrol  yalnızca denetle; hiçbir şey kurmaz, indirmez
#   ./kur.sh --evet     sormadan kur (sudo gereken adımda şifre yine sorulur)
#
# sudo yalnızca apt paketleri ve Ollama'nın resmî kurulum betiği için gerekir; geri kalan her
# şey (whisper.cpp, modeller, cmake, menü kısayolu) kullanıcı klasörüne kurulur.
set -u

DIZIN="$(cd "$(dirname "$0")" && pwd)"
KOK="$HOME/.local/share/robu"
SOHBET_MODELI="gemma4:e4b"
BELGE_MODELI="embeddinggemma"
WHISPER_MODELI="ggml-small-q5_1.bin"
CMAKE_SURUM="3.30.5"
OLLAMA_ADRESI="${OLLAMA_HOST:-http://localhost:11434}"

KIP="sor"
case "${1:-}" in
    --kontrol) KIP="kontrol" ;;
    --evet) KIP="evet" ;;
    "") ;;
    *) echo "Kullanım: $0 [--kontrol | --evet]"; exit 2 ;;
esac

YESIL=$'\033[32m'; KIRMIZI=$'\033[31m'; SARI=$'\033[33m'; KALIN=$'\033[1m'; SON=$'\033[0m'
tamam()   { printf '  %s✓%s %s\n' "$YESIL" "$SON" "$1"; }
eksik()   { printf '  %s✗%s %s\n' "$KIRMIZI" "$SON" "$1"; ZORUNLU_EKSIK=1; }
istege()  { printf '  %s–%s %s\n' "$SARI" "$SON" "$1"; }
baslik()  { printf '\n%s%s%s\n' "$KALIN" "$1" "$SON"; }
var()     { command -v "$1" >/dev/null 2>&1; }

# Evet/hayır sorusu. --kontrol: hep hayır, --evet: hep evet.
sor() {
    [ "$KIP" = "kontrol" ] && return 1
    [ "$KIP" = "evet" ] && return 0
    local cevap
    read -r -p "    $1 [E/h] " cevap
    case "$cevap" in [hHnN]*) return 1 ;; *) return 0 ;; esac
}

indir() {  # indir URL HEDEF: yarım dosya kalmasın diye önce .part'a
    curl -fL --progress-bar -o "$2.part" "$1" && mv "$2.part" "$2"
}

ZORUNLU_EKSIK=0
APT=()          # eksik apt paketleri (tek sudo komutunda kurulur)
SES_KUR=0
BELGE_KUR=0
MODEL_KUR=""

ollama_calisiyor() { curl -s -m 3 "$OLLAMA_ADRESI/api/version" >/dev/null 2>&1; }

# ---------------------------------------------------------------- denetim

baslik "Temel"
if var python3 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    tamam "Python $(python3 -c 'import platform; print(platform.python_version())')"
else
    eksik "Python 3.10 veya üstü gerekli"; APT+=(python3)
fi
if python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
    tamam "GTK 3 (PyGObject)"
else
    eksik "GTK 3 / PyGObject"; APT+=(python3-gi gir1.2-gtk-3.0)
fi
if var gio; then tamam "gio (çöp kutusu)"; else eksik "gio"; APT+=(libglib2.0-bin); fi
if var curl; then tamam "curl"; else eksik "curl"; APT+=(curl); fi

RAM_GB=$(awk '/MemTotal/ {printf "%d", $2 / 1048576 + 0.5}' /proc/meminfo)
if [ "$RAM_GB" -ge 10 ]; then
    tamam "Bellek: ${RAM_GB} GB"
else
    istege "Bellek: ${RAM_GB} GB — 6 GB'lık modeller zorlanabilir; daha küçük bir model seçin"
fi

baslik "Ollama ve model"
OLLAMA_YOK=0
if var ollama; then
    tamam "Ollama $(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if ollama_calisiyor; then
        tamam "Ollama servisi çalışıyor ($OLLAMA_ADRESI)"
        MODELLER=$(curl -s "$OLLAMA_ADRESI/api/tags" | python3 -c '
import json, sys
for m in json.load(sys.stdin).get("models", []):
    print(m["name"])' 2>/dev/null)
        SOHBETLER=$(printf '%s\n' "$MODELLER" | grep -v -i embed | grep -v '^$' || true)
        if [ -n "$SOHBETLER" ]; then
            SAYI=$(printf '%s\n' "$SOHBETLER" | wc -l)
            tamam "Sohbet modeli: $SAYI kurulu ($(printf '%s\n' "$SOHBETLER" | head -1)…)"
        else
            eksik "Sohbet modeli yok"; MODEL_KUR="$SOHBET_MODELI"
        fi
        if printf '%s\n' "$MODELLER" | grep -q "^$BELGE_MODELI"; then
            tamam "Belge araması modeli ($BELGE_MODELI)"
        else
            istege "Belge araması modeli yok ($BELGE_MODELI, ~620 MB)"; BELGE_KUR=1
        fi
    else
        eksik "Ollama servisi çalışmıyor — başlatmak için: sudo systemctl start ollama"
    fi
else
    eksik "Ollama kurulu değil"; OLLAMA_YOK=1
fi

baslik "İsteğe bağlı özellikler"
if var pdftotext; then tamam "PDF okuma (pdftotext)"; else istege "PDF okuma yok"; APT+=(poppler-utils); fi
if var libreoffice; then
    tamam "Excel/Word okuma (libreoffice)"
else
    istege "Excel/Word okuma yok (libreoffice; büyük paket, kendiniz kurun: sudo apt install libreoffice)"
fi

EKRAN=""
for arac in xfce4-screenshooter gnome-screenshot spectacle scrot grim maim import; do
    var "$arac" && { EKRAN="$arac"; break; }
done
if [ -n "$EKRAN" ]; then
    tamam "Ekran görüntüsü ($EKRAN)"
else
    case "${XDG_CURRENT_DESKTOP:-}" in
        *XFCE*) PAKET=xfce4-screenshooter ;;
        *KDE*) PAKET=spectacle ;;
        *) PAKET=gnome-screenshot ;;
    esac
    istege "Ekran görüntüsü aracı yok"; APT+=("$PAKET")
fi

CHROME=""
for c in google-chrome google-chrome-stable chromium chromium-browser; do
    var "$c" && { CHROME="$c"; break; }
done
if [ -n "$CHROME" ]; then
    tamam "İnternet işleri ($CHROME)"
else
    istege "Chrome/Chromium yok — internet araçları çalışmaz (https://www.google.com/chrome/)"
fi

WHISPER_CLI="$KOK/whisper.cpp/build/bin/whisper-cli"
if { [ -x "$WHISPER_CLI" ] || var whisper-cli; } && ls "$KOK/whisper-modelleri/"ggml-*.bin >/dev/null 2>&1 \
        && var arecord; then
    tamam "Sesli giriş (whisper.cpp)"
else
    istege "Sesli giriş kurulu değil (~200 MB indirme, derleme 3–5 dk)"; SES_KUR=1
fi

# ---------------------------------------------------------------- kurulum

if [ "$KIP" = "kontrol" ]; then
    baslik "Özet (yalnızca denetim)"
    [ "$OLLAMA_YOK" = 1 ] && echo "  Ollama: curl -fsSL https://ollama.com/install.sh | sh"
    [ -n "$MODEL_KUR" ] && echo "  Model:  ollama pull $MODEL_KUR"
    [ "${#APT[@]}" -gt 0 ] && echo "  Paketler: sudo apt install -y ${APT[*]}"
    [ "$SES_KUR" = 1 ] && echo "  Sesli giriş: ./kur.sh (sorarak kurar)"
    if [ "$ZORUNLU_EKSIK" = 0 ]; then
        echo "  ${YESIL}Robu çalışmaya hazır.${SON}"
    else
        echo "  ${KIRMIZI}Zorunlu eksikler var; ./kur.sh ile kurun.${SON}"
    fi
    exit "$ZORUNLU_EKSIK"
fi

if [ "$SES_KUR" = 1 ]; then
    baslik "Sesli giriş"
    if sor "Sesli giriş kurulsun mu? (whisper.cpp derlenir, ~200 MB indirilir)"; then
        var arecord || APT+=(alsa-utils)
        var git || APT+=(git)
        { var g++ && var make; } || APT+=(build-essential)
    else
        SES_KUR=0
    fi
fi

if [ "${#APT[@]}" -gt 0 ]; then
    baslik "Sistem paketleri"
    # tekrarları at
    mapfile -t APT < <(printf '%s\n' "${APT[@]}" | awk '!g[$0]++')
    echo "    Kurulacak: ${APT[*]}"
    if sor "sudo apt install ile kurulsun mu? (şifreniz sorulur)"; then
        sudo apt-get update -qq && sudo apt-get install -y "${APT[@]}" \
            || echo "  ${KIRMIZI}Paket kurulumu başarısız; yukarıdaki hataya bakın.${SON}"
    else
        echo "    Sonra kurmak için: sudo apt install -y ${APT[*]}"
    fi
fi

if [ "$OLLAMA_YOK" = 1 ]; then
    baslik "Ollama"
    if sor "Ollama resmî betikle kurulsun mu? (ollama.com, sudo ister)"; then
        curl -fsSL https://ollama.com/install.sh | sh
        for _ in $(seq 1 20); do ollama_calisiyor && break; sleep 1; done
        if ollama_calisiyor; then
            MODELLER=$(ollama list 2>/dev/null | awk 'NR > 1 {print $1}')
            printf '%s\n' "$MODELLER" | grep -v -i embed | grep -q . || MODEL_KUR="$SOHBET_MODELI"
            printf '%s\n' "$MODELLER" | grep -q "^$BELGE_MODELI" || BELGE_KUR=1
        fi
    else
        echo "    Sonra kurmak için: curl -fsSL https://ollama.com/install.sh | sh"
    fi
fi

if [ -n "$MODEL_KUR" ] && ollama_calisiyor; then
    baslik "Sohbet modeli"
    echo "    Önerilen: $MODEL_KUR (~6,6 GB; araç çağırma ve görsel destekli)."
    echo "    Daha zayıf bilgisayarlar için: gemma4:e2b (~4,6 GB)."
    if sor "Önerilen model indirilsin mi?"; then
        ollama pull "$MODEL_KUR"
    fi
fi

if [ "$BELGE_KUR" = 1 ] && ollama_calisiyor; then
    baslik "Belge araması"
    if sor "Belge araması için $BELGE_MODELI indirilsin mi? (~620 MB)"; then
        ollama pull "$BELGE_MODELI"
    fi
fi

if [ "$SES_KUR" = 1 ]; then
    baslik "Sesli giriş: whisper.cpp"
    mkdir -p "$KOK" "$KOK/whisper-modelleri" "$HOME/.local/opt"
    CMAKE="$(command -v cmake || true)"
    if [ -z "$CMAKE" ]; then  # sudo'suz: Kitware'in resmî hazır paketi
        HEDEF="$HOME/.local/opt/cmake-$CMAKE_SURUM-linux-$(uname -m)"
        if [ ! -x "$HEDEF/bin/cmake" ]; then
            echo "    cmake indiriliyor…"
            GECICI="$(mktemp -d)"
            indir "https://github.com/Kitware/CMake/releases/download/v$CMAKE_SURUM/cmake-$CMAKE_SURUM-linux-$(uname -m).tar.gz" \
                "$GECICI/cmake.tar.gz" && tar xzf "$GECICI/cmake.tar.gz" -C "$HOME/.local/opt"
            rm -rf "$GECICI"
        fi
        CMAKE="$HEDEF/bin/cmake"
    fi
    if [ ! -d "$KOK/whisper.cpp" ]; then
        git clone -q --depth 1 https://github.com/ggml-org/whisper.cpp "$KOK/whisper.cpp"
    fi
    if [ ! -x "$WHISPER_CLI" ]; then
        echo "    Derleniyor (3–5 dk)…"
        ( cd "$KOK/whisper.cpp" \
            && "$CMAKE" -B build -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF \
                -DGGML_NATIVE=ON >"$KOK/whisper-derleme.log" 2>&1 \
            && "$CMAKE" --build build -j "$(nproc)" --target whisper-cli >>"$KOK/whisper-derleme.log" 2>&1 ) \
            || echo "  ${KIRMIZI}Derleme başarısız: $KOK/whisper-derleme.log${SON}"
    fi
    if [ ! -f "$KOK/whisper-modelleri/$WHISPER_MODELI" ]; then
        echo "    Whisper modeli indiriliyor (~190 MB)…"
        indir "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$WHISPER_MODELI" \
            "$KOK/whisper-modelleri/$WHISPER_MODELI"
    fi
    [ -x "$WHISPER_CLI" ] && tamam "Sesli giriş hazır"
fi

# ---------------------------------------------------------------- menü ve test

baslik "Menü kısayolu"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/robu.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=Robu
Comment=Çevrimdışı küçük asistan (Ollama)
Exec=python3 -m robu
Path=$DIZIN
Icon=$DIZIN/robu/robu.svg
Terminal=false
Categories=Development;Utility;
StartupWMClass=robu
Keywords=ai;ollama;asistan;
EOD
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
tamam "Uygulamalar > Geliştirme > Robu"

baslik "Testler"
if (cd "$DIZIN" && python3 -m unittest discover -q tests >/dev/null 2>&1); then
    tamam "Birim testleri geçti"
else
    istege "Bazı testler başarısız: cd $DIZIN && python3 -m unittest discover tests"
fi

echo
echo "${KALIN}Bitti.${SON} Robu'yu menüden ya da 'cd $DIZIN && python3 -m robu' ile açın."
echo "Denetimi yinelemek için: $0 --kontrol"
