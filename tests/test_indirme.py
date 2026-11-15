"""Model indirme ilerlemesinin katmanlar boyunca toplanması."""
import unittest

from robu.indirme import IlerlemeToplami

GB = 1_000_000_000


class Toplam(unittest.TestCase):
    def test_ikinci_dosyada_sifirlanmaz(self):
        t = IlerlemeToplami()
        t.ekle({"status": "pulling a", "digest": "sha256:a", "total": 6 * GB, "completed": 6 * GB})
        t.ekle({"status": "pulling b", "digest": "sha256:b", "total": 1 * GB, "completed": 0})
        self.assertAlmostEqual(t.oran, 6 / 7)
        self.assertEqual(t.metin(), "6.00 / 7.00 GB · 2 dosya")
        t.ekle({"status": "pulling b", "digest": "sha256:b", "total": 1 * GB, "completed": GB // 2})
        self.assertAlmostEqual(t.oran, 6.5 / 7)

    def test_ayni_katman_guncellenir_kucukler_sayilmaz(self):
        t = IlerlemeToplami()
        for inen in (0, GB, 2 * GB):
            t.ekle({"digest": "sha256:a", "total": 4 * GB, "completed": inen})
        t.ekle({"digest": "sha256:sablon", "total": 1500, "completed": 1500})
        self.assertEqual(t.inen, 2 * GB + 1500)
        self.assertEqual(t.dosya_sayisi, 1)
        self.assertEqual(t.metin(), "2.00 / 4.00 GB")

    def test_ilerleme_olmayan_satirlar(self):
        t = IlerlemeToplami()
        for v in ({"status": "pulling manifest"}, {"status": "success"},
                  {"digest": "sha256:a", "total": 5}, {"digest": "sha256:a", "completed": 3}):
            self.assertFalse(t.ekle(v))
        self.assertEqual(t.oran, 0.0)
        self.assertEqual(t.metin(), "0.00 / 0.00 GB")


if __name__ == "__main__":
    unittest.main()
