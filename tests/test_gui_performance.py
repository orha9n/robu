"""GTK entegrasyon regresyonu. Kişisel geçmiş/config okunmaz veya yazılmaz."""
import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from robu import arayuz
    HAVE_GTK = arayuz.Gtk.init_check()[0]
except (ImportError, RuntimeError):
    HAVE_GTK = False


@unittest.skipUnless(HAVE_GTK, 'GTK/display unavailable')
class GUIRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = arayuz.Gtk.Application(application_id='io.robu.PerformanceTest', flags=arayuz.Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.app.quit()

    def setUp(self):
        stack = contextlib.ExitStack(); self.addCleanup(stack.close)
        cfg = dict(arayuz.cekirdek.VARSAYILAN_AYARLAR, model='synthetic', klasor='/tmp')
        stack.enter_context(patch.object(arayuz.cekirdek, 'ayarlari_yukle', return_value=cfg))
        stack.enter_context(patch.object(arayuz.cekirdek, 'sistem_istemi', return_value='Sentetik sistem.'))
        stack.enter_context(patch.object(arayuz.cekirdek, 'ayarlari_kaydet'))
        stack.enter_context(patch.object(arayuz.belgeler if hasattr(arayuz, 'belgeler') else arayuz.cekirdek.belgeler, 'aciklama', return_value='Sentetik'))
        stack.enter_context(patch.object(arayuz.ses, 'hazir_mi', return_value=False))
        for name in ('_modelleri_yenile', '_gecmisi_yenile', '_kaydet', '_bildir'):
            stack.enter_context(patch.object(arayuz.RobuPenceresi, name))
        self.window = arayuz.RobuPenceresi(self.app)
        self.addCleanup(self.window.destroy)

    def test_escape_stops_audio_after_llm_finishes(self):
        w = self.window
        self.assertFalse(w.mesgul)
        with patch.object(w.sesli_yanit, 'yeni_istek', return_value=99) as cancel:
            event = SimpleNamespace(state=0, keyval=arayuz.Gdk.KEY_Escape)
            self.assertTrue(w._kisayol(None, event))
            cancel.assert_called_once(); self.assertEqual(w._tts_epoch, 99)

    def test_only_final_answer_is_sent_to_tts(self):
        w = self.window
        w.balon = arayuz.RobuBalonu()
        with patch.object(w.sesli_yanit, 'soyle') as speak:
            w._olay('metin', 'Yarım metin')
            self.assertFalse(speak.called)
            w.ajan.mesajlar.append({'role': 'assistant', 'content': 'Kesinleşmiş yanıt.'})
            w._olay('bitti')
            speak.assert_called_once_with('Kesinleşmiş yanıt.', w._tts_epoch)

    def test_disabling_tts_closes_worker(self):
        w = self.window
        with patch.object(w.sesli_yanit, 'kapat') as close:
            w._ayar_degis('sesli_yanit', False)
            close.assert_called_once()

    def test_local_reply_uses_same_audio_epoch(self):
        w = self.window
        with patch.object(w.sesli_yanit, 'soyle') as speak:
            w._yerel('Sentetik soru.', lambda _text: 'Sentetik yerel yanıt.')
            speak.assert_called_once_with('Sentetik yerel yanıt.', w._tts_epoch)

if __name__ == '__main__': unittest.main()
