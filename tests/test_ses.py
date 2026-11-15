"""Gerçek kayıtların enerji eşiği yüzünden kaybolmasına karşı regresyonlar."""
import array
import io
import math
import unittest
import wave
from unittest import mock

from robu import ses


def parca(genlik):
    return array.array("h", (int(genlik * math.sin(i / 3)) for i in range(800))).tobytes()


class SesKaydi(unittest.TestCase):
    def test_dusuk_sesli_konusma_sonrasi_durur(self):
        d = ses.SessizlikDedektoru()
        for _ in range(10):
            d.besle(parca(20))
        for _ in range(12):
            self.assertFalse(d.besle(parca(200)))
        self.assertTrue(any(d.besle(parca(20)) for _ in range(30)))

    def test_ilk_anda_konusma_gurultu_sayilmaz(self):
        d = ses.SessizlikDedektoru()
        for _ in range(20):
            self.assertFalse(d.besle(parca(6000)))
        self.assertTrue(any(d.besle(parca(20)) for _ in range(30)))

    def _kayit(self, veri):
        k = ses.Kayit()
        k._ses = bytearray(veri)
        k._surec = mock.Mock(stdout=io.BytesIO())
        k._surec.poll.return_value = 0
        self.addCleanup(k.temizle)
        return k

    def test_dedektor_tanimasa_da_gercek_kayit_saklanir(self):
        k = self._kayit(parca(150) * 10)
        self.assertEqual(k._dedektor.konusma_parca, 0)
        yol = k.bitir()
        self.assertIsNotNone(yol)
        with wave.open(yol, "rb") as wav:
            self.assertEqual(wav.getnframes(), 8000)
            self.assertEqual(wav.getframerate(), 16000)

    def test_sessiz_ve_kisa_kayit_ayri_hata_verir(self):
        sessiz = self._kayit(parca(0) * 10)
        self.assertIsNone(sessiz.bitir())
        self.assertIn("Mikrofondan ses gelmedi", sessiz.hata)
        kisa = self._kayit(parca(2000))
        self.assertIsNone(kisa.bitir())
        self.assertIn("0,2 saniyeden kısa", kisa.hata)

    @mock.patch.object(ses.shutil, "which", return_value="/usr/bin/var")
    @mock.patch.object(ses.subprocess, "check_output")
    def test_monitor_yerine_mikrofon_secilir(self, output, which):
        output.side_effect = ['[{"name":"speaker.monitor","properties":{"device.class":"monitor"}},'
                              '{"name":"mic","properties":{"device.class":"sound"}}]',
                              'speaker.monitor\n']
        self.assertEqual(ses.mikrofon_kaynagi(), "mic")

    @mock.patch.object(ses.shutil, "which", return_value="/usr/bin/var")
    @mock.patch.object(ses.subprocess, "check_output")
    def test_monitor_disinda_kaynak_yoksa_anlasilir_hata(self, output, which):
        output.side_effect = ['[{"name":"speaker.monitor"}]', 'speaker.monitor\n']
        with self.assertRaisesRegex(RuntimeError, "Gerçek mikrofon bulunamadı"):
            ses.mikrofon_kaynagi()

    def test_ses_yoksa_tek_callback_ve_bos_kayit(self):
        callback = mock.Mock()
        k = ses.Kayit(sessizlikte=callback)
        k._oku(mock.Mock(stdout=io.BytesIO(parca(0) * 120)))
        callback.assert_called_once()
        self.assertEqual(len(k._ses), ses.KONUSMA_BEKLEME * ses.ORAN * 2)

    @mock.patch.object(ses.subprocess, "run")
    def test_sessiz_wav_modele_gonderilmez(self, run):
        import tempfile
        import os
        fd, yol = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(yol, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(parca(0) * 20)
            self.assertEqual(ses.yaziya_cevir(yol), "")
            run.assert_not_called()
        finally:
            os.unlink(yol)

    @mock.patch.object(ses.shutil, "which", return_value="/usr/bin/var")
    @mock.patch.object(ses.subprocess, "check_output")
    def test_bagli_olmayan_giris_sessizce_kaydedilmez(self, output, which):
        output.side_effect = ['[{"name":"mic","active_port":"input",'
                              '"ports":[{"name":"input","availability":"not available"}]}]', 'mic\n']
        with self.assertRaisesRegex(RuntimeError, "mikrofon girişini kullanılamıyor"):
            ses.mikrofon_kaynagi()


if __name__ == "__main__":
    unittest.main()
