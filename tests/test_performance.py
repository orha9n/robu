"""Akış tamamlanması, ölçüm ve ayar regresyonları; gerçek ağ/model kullanmaz."""
import unittest
from unittest.mock import patch
from robu import cekirdek as c


class PerformanceRegression(unittest.TestCase):
    def setUp(self):
        self.stack = patch.object(c, 'kisisel_talimatlar', return_value='')
        self.stack.start(); self.addCleanup(self.stack.stop)
        self.events = []
        self.agent = c.Ajan(dict(c.VARSAYILAN_AYARLAR, model='synthetic', klasor='/tmp'),
                            lambda *e: self.events.append(e), lambda *a: False)

    def test_default_body_and_flags(self):
        body = self.agent._govde(self.agent.mesajlar)
        self.assertNotIn('num_thread', body['options'])
        self.assertNotIn('keep_alive', body)
        self.agent.ayar.update(model_thread=2, model_keep_alive='5m')
        self.assertEqual(self.agent._govde([])['options']['num_thread'], 2)
        self.assertEqual(self.agent._govde([])['keep_alive'], '5m')
        self.assertEqual(self.agent._govde([], num_thread=4)['options']['num_thread'], 4)
        for bad in (True, 0, -1, '4'):
            self.agent.ayar['model_thread'] = bad
            with self.assertRaises(ValueError): self.agent._govde([])

    def test_no_tool_execution_or_history_on_incomplete_stream(self):
        class Broken:
            def sohbet_akisi(self, *a):
                yield {'message': {'tool_calls': [{'function': {'name': 'komut', 'arguments': {'cmd': 'printf x'}}}]}}
        before = list(self.agent.mesajlar)
        with self.assertRaises(RuntimeError): self.agent._adim(Broken())
        self.assertEqual(self.agent.mesajlar, before)

    def test_cancel_does_not_commit_partial_turn(self):
        a = self.agent
        class Cancel:
            def sohbet_akisi(self, *args):
                yield {'message': {'content': 'yarım'}}
                a.dur.set()
                yield {'done': True}
        before = list(a.mesajlar)
        self.assertEqual(a._adim(Cancel()), [])
        self.assertEqual(a.mesajlar, before)

    def test_partial_tool_text_is_never_published_or_executed(self):
        class ToolText:
            def sohbet_akisi(self, *args):
                for text in ('ko', 'mut(', 'cmd="printf x")'):
                    yield {'message': {'content': text, 'thinking': 'private'}}
                yield {'done': True}
        calls = self.agent._adim(ToolText())
        self.assertEqual(calls[0]['function']['arguments'], {'cmd': 'printf x'})
        self.assertFalse(any(e[0] in ('metin', 'dusunce', 'komut') for e in self.events))

    def test_finished_json_answer_is_released(self):
        class JsonAnswer:
            def sohbet_akisi(self, *args):
                yield {'message': {'content': '{"sonuc":'}}
                self.check()
                yield {'message': {'content': ' 3}'}}
                yield {'done': True}
            def check(inner):
                self.assertFalse(any(e[0] == 'metin' for e in self.events))
        self.agent._adim(JsonAnswer())
        self.assertIn(('metin', '{"sonuc": 3}'), self.events)

    def test_done_with_malformed_arguments_is_not_committed(self):
        class Malformed:
            def sohbet_akisi(self, *args):
                yield {'message': {'tool_calls': [{'function': {'name': 'komut', 'arguments': '{"cmd":'}}]}}
                yield {'done': True}
        before = list(self.agent.mesajlar)
        with self.assertRaises(RuntimeError): self.agent._adim(Malformed())
        self.assertEqual(self.agent.mesajlar, before)

    def test_clock_metadata_does_not_contain_content(self):
        points = []
        self.agent.olcum = points.append
        class Complete:
            def sohbet_akisi(self, *a):
                yield {'message': {'content': 'Türkçe yanıt.'}}
                yield {'done': True, 'eval_count': 3, 'eval_duration': 1000000000,
                       'load_duration': 50, 'prompt_eval_cached_count': 9}
        self.agent._adim(Complete())
        self.assertEqual(points, ['prompt_ready', 'first_text_callback'])
        stats = next(e[1] for e in self.events if e[0] == 'adim_bitti')
        self.assertEqual(stats['prompt_eval_cached_count'], 9)
        self.assertNotIn('content', stats)

    def test_prefix_and_conversation_isolation(self):
        first = self.agent._govde(self.agent.mesajlar)
        self.agent.mesajlar.extend([{'role': 'user', 'content': 'Sentetik tur'},
                                   {'role': 'assistant', 'content': 'Sentetik yanıt'}])
        second = self.agent._govde(self.agent.mesajlar)
        self.assertEqual(first['messages'][0], second['messages'][0])
        self.assertEqual(first['tools'], second['tools'])
        self.agent.sifirla()
        self.assertEqual(len(self.agent.mesajlar), 1)
        self.agent.arac_destegi(False)
        self.assertNotIn('tools', self.agent._govde([]))
        self.assertNotEqual(first['messages'][0], self.agent.mesajlar[0])
        self.agent.gecmisi_yukle([{'role': 'user', 'content': 'Yeni oturum'}])
        self.assertEqual(len(self.agent.mesajlar), 2)


if __name__ == '__main__': unittest.main()
