"""Yerel, sentetik Ajan benchmark'ı. Ham metin/ses kaydetmez; kurulum yapmaz."""
import argparse
import contextlib
import csv
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robu import cekirdek as c


class Trace:
    def __init__(self, expected=None):
        self.expected = expected
        self.start = time.perf_counter_ns()
        self.points = {}
        self.steps = []
        self.errors = 0
        self.tool_ok = False

    def mark(self, name):
        self.points.setdefault(name, (time.perf_counter_ns() - self.start) / 1e9)

    def event(self, name, *args):
        if name == 'adim_bitti':
            self.steps.append(args[0])
        elif name == 'hata':
            self.errors += 1
        elif name == 'cikti' and len(args) > 1 and args[1] == 'ROBU_BENCH_OK':
            self.tool_ok = True
            if self.expected == 'TOOL':
                self.mark('first_meaningful_text')
        elif name == 'metin' and self.expected and self.expected != 'TOOL' and self.expected in args[0].casefold():
            self.mark('first_meaningful_text')


def environment():
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k, value = line.split(':', 1)
        if k in ('MemAvailable', 'SwapFree', 'MemTotal'):
            mem[k] = int(value.split()[0])
    temps = []
    cpu_temps = []
    for f in Path('/sys/class/hwmon').glob('hwmon*/temp*_input'):
        try:
            temp = int(f.read_text().strip()) / 1000
            temps.append(temp)
            if (f.parent / 'name').read_text().strip() == 'k10temp':
                cpu_temps.append(temp)
        except OSError:
            pass
    vm = {k: int(v) for k, v in (line.split() for line in Path('/proc/vmstat').read_text().splitlines())
          if k in ('pswpin', 'pswpout')}
    return dict(mem, load=os.getloadavg(), temperatures_c=temps, cpu_temperature_c=max(cpu_temps, default=None), **vm)


def percentile(values, p):
    a = sorted(values)
    return a[max(0, math.ceil(len(a) * p) - 1)] if a else None


def summary(rows):
    result = {}
    for variant in dict.fromkeys(r['variant'] for r in rows):
        groups = ['all'] + list(dict.fromkeys(r['scenario'] for r in rows if r['variant'] == variant))
        result[variant] = {}
        for group in groups:
            selected = [r for r in rows if r['variant'] == variant and (group == 'all' or r['scenario'] == group)]
            stats = {'n': len(selected), 'quality_pass': sum(r['quality_pass'] for r in selected),
                     'errors': sum(r['errors'] for r in selected)}
            for field in ('first_text_callback', 'first_meaningful_text', 'request_completed', 'http_request_sent', 'stream_event'):
                values = [r[field] for r in selected if r.get(field) is not None]
                stats[field] = {'n': len(values), 'p50': statistics.median(values) if values else None,
                                'p95': percentile(values, .95)}
            stats['decode_tok_s_p50'] = statistics.median([r['decode_tok_s'] for r in selected])
            result[variant][group] = stats
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--variants', default='baseline,2,4,6,8', help='baseline or CPU thread counts, comma separated')
    ap.add_argument('--repeats', type=int, default=3, help='7 scenarios x repeats; default 21 warm requests per variant')
    ap.add_argument('--output', default='docs/performance/results/runtime')
    args = ap.parse_args()
    settings = c.ayarlari_yukle()
    u = urllib.parse.urlparse(settings['ollama'])
    if u.hostname not in ('localhost', '127.0.0.1', '::1'):
        ap.error('Only existing loopback Ollama may be benchmarked')
    variants = args.variants.split(',')
    if args.repeats < 1 or any(v != 'baseline' and v not in ('2', '4', '6', '8') for v in variants):
        ap.error('Invalid repeats/variant')
    client = c.Ollama(settings['ollama'])
    with client._istek('/api/tags') as r:
        model = next(m for m in json.load(r)['models'] if m['name'] == settings['model'])
    with client._istek('/api/show', {'model': settings['model']}) as r:
        show = json.load(r)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {'started_at': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(),
            'python': platform.python_version(), 'ollama': client.surum(),
            'source_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ('robu/cekirdek.py', 'tests/performance.py')},
            'model': model['name'], 'model_digest': model['digest'], 'details': model['details'],
            'template_sha256': hashlib.sha256(show.get('template', '').encode()).hexdigest(),
            'context': settings['baglam'], 'thinking': settings['dusunme'],
            'sampling': 'unchanged backend defaults; no output limit override',
            'first_text_scope': 'Ajan callback, not painted GTK frame', 'cold': [], 'warmups': [], 'rows': []}
    def save():
        data['summary'] = summary(data['rows'])
        out.with_suffix('.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
        if data['rows']:
            fields = list(data['rows'][0])
            with out.with_suffix('.csv').open('w') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(data['rows'])
    original_tool = c.Ajan._arac
    def sandbox_tool(agent, call):
        fn = call.get('function', {})
        cmd = fn.get('arguments', {}).get('cmd', '') if isinstance(fn.get('arguments'), dict) else ''
        try:
            tokens = c._parcala(cmd)
        except ValueError:
            tokens = []
        if fn.get('name') == 'komut' and tokens in (["printf", "ROBU_BENCH_OK"], ["printf", "ROBU_BENCH_OK\\n"], ["printf", "%s", "ROBU_BENCH_OK"], ["printf", "%s\\n", "ROBU_BENCH_OK"]):
            return original_tool(agent, call)  # retains production permission checks
        return agent._reddedildi(id(call), fn.get('name', 'komut'))
    original_expand = os.path.expanduser
    with tempfile.TemporaryDirectory(prefix='robu-perf-') as folder, contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(c, 'kisisel_talimatlar', return_value=''))
        stack.enter_context(patch.object(c, 'klasor_adlari', return_value=''))
        stack.enter_context(patch.object(c.belgeler, 'dizin_var', return_value=False))
        stack.enter_context(patch.object(c.os.path, 'expanduser', side_effect=lambda s: folder if s == '~' else original_expand(s)))
        stack.enter_context(patch.object(c.Ajan, '_arac', sandbox_tool))
        settings = dict(settings, klasor=folder)
        def agent(araclar, variant):
            cfg = dict(settings, model_thread=None if variant == 'baseline' else int(variant))
            a = c.Ajan(cfg, lambda *a: None, lambda *a: False)
            a.arac_destegi(araclar, gorsel=araclar)
            return a
        def request(a, prompt, scenario, variant, repeat, expected):
            t = Trace(expected); a.olcum = t.mark; a.olay = t.event
            before = environment()
            a.calistir(prompt)
            after = environment()
            answer = a.mesajlar[-1].get('content', '').casefold()
            counts = sum(s.get('uretilen', 0) for s in t.steps)
            decode = sum(s.get('eval_duration', 0) for s in t.steps) / 1e9
            row = dict(variant=variant, scenario=scenario, repeat=repeat,
                       **{k: t.points.get(k) for k in ('input_accepted', 'prompt_ready', 'http_request_sent',
                                                      'stream_event', 'first_text_callback', 'first_meaningful_text', 'request_completed')},
                       errors=t.errors, quality_pass=(t.errors == 0 and (t.tool_ok if expected == 'TOOL' else expected in answer)),
                       tool_ok=t.tool_ok, steps=len(t.steps), output_tokens=counts,
                       decode_tok_s=counts / decode if decode else 0,
                       load_s=sum(s.get('load_duration', 0) for s in t.steps) / 1e9,
                       prefill_s=sum(s.get('prompt_eval_duration', 0) for s in t.steps) / 1e9,
                       cached_tokens=sum(s.get('prompt_eval_cached_count', 0) for s in t.steps),
                       prompt_tokens=sum(s.get('istem', 0) for s in t.steps),
                       available_kib_before=before['MemAvailable'], available_kib_after=after['MemAvailable'],
                       swap_in_delta=after['pswpin']-before['pswpin'], swap_out_delta=after['pswpout']-before['pswpout'],
                       max_temperature_c=max(after['temperatures_c'], default=0), cpu_temperature_c=after['cpu_temperature_c'],
                       load1_before=before['load'][0])
            print(json.dumps({k: row[k] for k in ('variant', 'scenario', 'first_text_callback', 'request_completed', 'quality_pass')}, ensure_ascii=False), flush=True)
            return row
        # Natural cold start only; never unload another caller's active model.
        if not client.yuklu():
            a = agent(False, 'baseline')
            data['cold'].append(request(a, 'Türkiye\'nin başkenti neresi? Kısa cevap ver.', 'short_tr', 'baseline', -1, 'ankara'))
            save()
        for variant in variants:
            print('variant '+variant, flush=True)
            for tools in (False, True):
                a = agent(tools, variant)
                start = time.perf_counter_ns(); a.isit()
                data['warmups'].append({'variant': variant, 'tools': tools, 'seconds': (time.perf_counter_ns()-start)/1e9})
            for scenario in ('short_tr', 'short_en', 'multi', 'medium', 'tools_no_call', 'tool'):
                for repeat in range(args.repeats):
                    a = agent(scenario in ('tools_no_call', 'tool'), variant)
                    if scenario == 'multi':
                        # First turn is setup, recorded separately from second/third-turn latency.
                        setup = request(a, 'Bu sentetik konuşmada seçtiğim renk turkuaz. Aklında tut ve kısaca onayla.', 'multi_setup', variant, repeat, 'turkuaz')
                        data['warmups'].append(setup)
                        for n in (2, 3):
                            data['rows'].append(request(a, 'Seçtiğim renk neydi? Kısa cevap ver.', 'multi_'+str(n), variant, repeat, 'turkuaz')); save()
                        continue
                    if scenario == 'medium':
                        for n in range(28):
                            a.mesajlar.extend([{'role': 'user', 'content': f'Sentetik not {n}: Parkta yürüyüş, kitap okuma ve çay içme hakkında konuşuyoruz.'},
                                              {'role': 'assistant', 'content': 'Bu notu hatırlıyorum. Yürüyüş ve kitap okuma günlük alışkanlıklar olarak konuşuldu.'}])
                        a.mesajlar.extend([{'role': 'user', 'content': 'Sentetik oda numarası 347.'}, {'role': 'assistant', 'content': 'Oda numarası 347.'}])
                        prompt, expected = 'Oda numarası neydi? Kısa cevap ver.', '347'
                    elif scenario == 'short_en':
                        prompt, expected = 'What is the capital of France? Answer briefly.', 'paris'
                    elif scenario == 'tool':
                        prompt, expected = 'komut aracını kullanarak yalnızca printf ROBU_BENCH_OK çalıştır, sonra sonucu kısaca söyle.', 'TOOL'
                    else:
                        prompt, expected = 'Türkiye\'nin başkenti neresi? Kısa cevap ver.', 'ankara'
                    data['rows'].append(request(a, prompt, scenario, variant, repeat, expected)); save()
            with client._istek('/api/ps') as r:
                active = json.load(r)['models']
            data.setdefault('residency', []).append({'variant':variant, 'models': [
                {k:m.get(k) for k in ('name','size','size_vram','context_length','expires_at')} for m in active]})
            save()
    print(json.dumps(data['summary'], ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
