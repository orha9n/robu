"""Model ısınması: kullanıcı mesajı istemeyen ve isteyen sohbet şablonları."""
import unittest
from unittest import mock

from robu import cekirdek


def _ajan():
    ayar = dict(cekirdek.VARSAYILAN_AYARLAR, model="m", baglam=4096)
    return cekirdek.Ajan(ayar, lambda *o: None, lambda c: False)


class Isinma(unittest.TestCase):
    def test_yalniz_sistem_yeterliyse_tek_istek(self):
        gonderilen = []
        with mock.patch.object(cekirdek.Ollama, "sohbet_akisi",
                               lambda self, govde: gonderilen.append(govde["messages"]) or iter(())):
            _ajan().isit()
        self.assertEqual(len(gonderilen), 1)
        self.assertEqual([m["role"] for m in gonderilen[0]], ["system"])

    def test_sablon_kullanici_mesaji_isterse_yeniden_dener(self):
        gonderilen = []

        def akis(self, govde):
            gonderilen.append(govde["messages"])
            if len(gonderilen) == 1:
                raise RuntimeError("No user query found in messages.")
            return iter(())
        with mock.patch.object(cekirdek.Ollama, "sohbet_akisi", akis):
            _ajan().isit()
        self.assertEqual([m["role"] for m in gonderilen[1]], ["system", "user"])

    def test_ikinci_deneme_de_basarisizsa_ilk_hata(self):
        def akis(self, govde):
            raise RuntimeError("ilk" if len(govde["messages"]) == 1 else "ikinci")
        with mock.patch.object(cekirdek.Ollama, "sohbet_akisi", akis):
            with self.assertRaisesRegex(RuntimeError, "ilk"):
                _ajan().isit()


if __name__ == "__main__":
    unittest.main()
