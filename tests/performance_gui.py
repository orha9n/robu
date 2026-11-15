"""Sentetik GTK balonunda ilk label çizimini ölçer; ekrana pencere çıkarmaz."""
import contextlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robu import arayuz


def main():
    rows = []
    cfg = dict(arayuz.cekirdek.VARSAYILAN_AYARLAR, model='synthetic', klasor='/tmp')
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(arayuz.cekirdek, 'ayarlari_yukle', return_value=cfg))
        stack.enter_context(patch.object(arayuz.cekirdek, 'sistem_istemi', return_value='Sentetik sistem.'))
        stack.enter_context(patch.object(arayuz.cekirdek, 'ayarlari_kaydet'))
        stack.enter_context(patch.object(arayuz.cekirdek.belgeler, 'aciklama', return_value='Sentetik'))
        stack.enter_context(patch.object(arayuz.ses, 'hazir_mi', return_value=False))
        for name in ('_modelleri_yenile', '_gecmisi_yenile', '_kaydet', '_bildir'):
            stack.enter_context(patch.object(arayuz.RobuPenceresi, name))
        app = arayuz.Gtk.Application(application_id='io.robu.PaintTest', flags=arayuz.Gio.ApplicationFlags.NON_UNIQUE)
        app.register(None)
        window = arayuz.RobuPenceresi(app)  # unshown, no history/config access
        offscreen = arayuz.Gtk.OffscreenWindow(); offscreen.set_default_size(700, 160)
        try:
            for repeat in range(20):
                balon = arayuz.RobuBalonu(); offscreen.add(balon); offscreen.show_all()
                window.balon = balon; window._paint_trace_started = False
                loop = arayuz.GLib.MainLoop(); points = {}; start = time.perf_counter_ns()
                def mark(name):
                    points.setdefault(name, (time.perf_counter_ns()-start)/1e9)
                    if name == 'first_text_painted': loop.quit()
                window.ajan.olcum = mark
                def deliver():
                    points['callback_queued_s'] = (time.perf_counter_ns()-start)/1e9
                    window._olay_kopru('metin', 'Türkiye’nin başkenti Ankara’dır.')
                    return False
                arayuz.GLib.idle_add(deliver)
                timeout = arayuz.GLib.timeout_add(2000, lambda: (loop.quit(), False)[1])
                loop.run(); arayuz.GLib.source_remove(timeout)
                if 'first_text_painted' not in points: raise RuntimeError('GTK draw timed out')
                rows.append(points); offscreen.remove(balon); balon.destroy()
        finally:
            offscreen.destroy(); window.destroy(); app.quit()
    summary = {}
    for name in rows[0]:
        values = sorted(r[name] for r in rows)
        summary[name] = {'p50': statistics.median(values), 'p95': values[18]}
    output = Path(__file__).resolve().parents[1] / 'docs/performance/results/gui-20261101.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'scope':'synthetic GTK OffscreenWindow, actual draw signal; not monitor scanout or real end-to-end inference',
                                 'n':len(rows), 'rows':rows, 'summary':summary}, indent=2))
    print(json.dumps(summary, indent=2))

if __name__ == '__main__': main()
