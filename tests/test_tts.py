"""EMA bağımlılıkları olmadan protokol, iptal ve metin filtresi testleri."""
import io
import unittest
from unittest.mock import Mock, patch
from robu import tts


class TTSRegression(unittest.TestCase):
    def test_code_json_and_urls_are_not_spoken(self):
        self.assertEqual(tts.okunacak_metin('{"tool_calls": []}'), '')
        self.assertEqual(tts.okunacak_metin('```python\nprint(1)\n```'), '')
        self.assertEqual(tts.okunacak_metin('Merhaba. `sudo x` https://example.org'), 'Merhaba.')
        self.assertEqual(tts.okunacak_metin('[Kaynak](https://example.org)'), 'Kaynak')

    def test_partial_bytes_and_disconnect(self):
        class Pieces:
            def read(self, n): return b'x'
        self.assertEqual(tts._tam_oku(Pieces(), 4), b'xxxx')
        with self.assertRaises(RuntimeError): tts._tam_oku(io.BytesIO(b'xx'), 4)

    def test_old_generation_and_disabled_do_not_start_worker(self):
        voice = tts.SesliYanit({'sesli_yanit': True})
        old = voice.yeni_istek(); voice.yeni_istek()
        with patch.object(tts.threading, 'Thread') as thread:
            voice.soyle('Eski yanıt.', old)
            self.assertFalse(thread.called)
            voice.ayar['sesli_yanit'] = False
            voice.soyle('Yeni yanıt.', voice._epoch)
            self.assertFalse(thread.called)

    def test_cancel_kills_active_but_reuses_idle_model(self):
        voice = tts.SesliYanit({'sesli_yanit': True})
        worker, player = Mock(), Mock()
        voice._worker = worker; voice._player = player
        with patch.object(voice, '_kes') as kill:
            voice.yeni_istek()
            self.assertIs(voice._worker, worker)
            voice._active = True; voice._player = player
            voice.yeni_istek()
            self.assertIsNone(voice._worker)
            kill.assert_any_call(worker); kill.assert_any_call(player)

    def test_close_releases_idle_model(self):
        voice = tts.SesliYanit({})
        voice._worker = Mock()
        with patch.object(voice, '_kes') as kill:
            voice.kapat()
            self.assertIsNone(voice._worker)
            self.assertTrue(kill.called)

if __name__ == '__main__': unittest.main()
