"""自动选择写入模型（用户要求：不写死模型，自动识别当前可用的模型，用其中最便宜且够用的一个）。

1. 列出可用模型：从宿主 agent 自己的渠道读取——codebuddy --help 里 --model 的说明、qodercli --list-models、
   Codex 的 ~/.codex/models_cache.json；Claude Code 没有列表命令，用别名 haiku / sonnet / opus（别名自动指向最新版）。
2. 按名字粗排：名字带 flash / lite / mini / haiku / luna / efficient / fast 等低价档字样的排前面；auto、本地自定义模型不参与。
3. 试探：对排在前面的几个各发一次极小的 JSON 抽取任务，确认能按要求输出（太弱的模型会把记忆写坏，不能只看便宜），
   并记下宿主报告的单次消耗（credit / 美元）。选消耗最低且通过的；宿主不报告消耗时（Codex）按粗排顺序取第一个通过的。
4. 结果缓存在 ~/.hyperthymesia/models.json，7 天后或调用报“模型不可用”时重新识别。"""
import json, os, re, shutil, subprocess, time
from pathlib import Path

from . import paths

TTL = 7 * 86400
PROBE_TOP = 4
CHEAP_WORDS = ('free', 'flash', 'lite', 'mini', 'nano', 'haiku', 'luna', 'efficient', 'fast', 'small', 'turbo')
EXPENSIVE_WORDS = ('max', 'pro', 'opus', 'ultimate', 'astra', 'sol', 'preview')
SKIP = re.compile(r'^(auto|custom-local:.*|codex-auto-review)$', re.I)
PROBE_SYSTEM = '你是信息抽取程序。只回复一个 JSON 对象，不要任何其他文字。'
PROBE_PROMPT = ('从下面对话抽取事实，回复 {"facts":[{"key":"…","value":"…"}]}，key 只用 page_size 和 reviewer。\n'
                '用户：默认分页原来是 20，现在改成 50。代码评审以后交给 Marco。')


def _cache_path(): return paths.home() / 'models.json'


def _load():
    try: return json.loads(_cache_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _save(d): _cache_path().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')


def list_models(provider):
    """当前可用的模型 ID 列表（顺序即宿主给出的顺序）。"""
    from .install import codebuddy_exe
    from .providers import qodercli_cmd
    try:
        if provider == 'codebuddy' and codebuddy_exe():
            # CodeBuddy 没有列模型的子命令（“codebuddy models”会被当成一句提问交给 agent）；--help 里 --model 的说明列出了当前账号可用的模型
            out = subprocess.run([codebuddy_exe(), '--help'], capture_output=True, text=True, encoding='utf-8', timeout=120).stdout
            m = re.search(r'Currently supported:\s*\(([^)]*)\)', out)
            return [i.strip() for i in m.group(1).split(',') if i.strip()] if m else []
        if provider == 'qoder' and qodercli_cmd():
            out = subprocess.run(qodercli_cmd() + ['--list-models'], capture_output=True, text=True, encoding='utf-8', timeout=120,
                                 stdin=subprocess.DEVNULL).stdout
            return [l.strip() for l in out.splitlines()[1:] if l.strip()]
        if provider == 'codex':
            d = json.loads((Path.home() / '.codex' / 'models_cache.json').read_text(encoding='utf-8'))
            return [m['slug'] for m in d.get('models', []) if m.get('visibility', 'list') == 'list']
        if provider == 'claude' and shutil.which('claude'):
            return ['haiku', 'sonnet', 'opus']
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return []


def rank(ids):
    """按名字粗排：低价档字样加分、高价档字样减分；同分保持宿主原顺序。"""
    def score(i):
        n = i.lower()
        return -sum(w in n for w in CHEAP_WORDS) * 2 + sum(w in n for w in EXPENSIVE_WORDS)
    return sorted([i for i in ids if not SKIP.match(i)], key=lambda i: (score(i), ids.index(i)))


def _probe(provider, model):
    """一次极小的抽取：(是否通过, 单次消耗或 None)。"""
    from . import providers, writer
    old = os.environ.get('HYPERTHYMESIA_MODEL'); os.environ['HYPERTHYMESIA_MODEL'] = model
    try:
        rep = providers.call(paths.home(), PROBE_SYSTEM, PROBE_PROMPT)
        got = {f.get('key'): str(f.get('value')) for f in writer.parse(rep.text).get('facts', [])}
        ok = '50' in got.get('page_size', '') and 'marco' in got.get('reviewer', '').lower()
        return ok, rep.usage.get('cost')
    except Exception:
        return False, None
    finally:
        if old is None: os.environ.pop('HYPERTHYMESIA_MODEL', None)
        else: os.environ['HYPERTHYMESIA_MODEL'] = old


def choose(provider, refresh=False):
    """该提供方当前最便宜且够用的模型；识别不出时返回空串（由调用方用宿主默认模型）。"""
    cache = _load(); c = cache.get(provider)
    if c and not refresh and time.time() - c.get('at', 0) < TTL: return c.get('model', '')
    cands = rank(list_models(provider))[:PROBE_TOP]
    tried = []
    for m in cands:
        ok, cost = _probe(provider, m); tried.append({'model': m, 'ok': ok, 'cost': cost})
        if ok and cost is None: break        # 宿主不报告消耗：按粗排取第一个通过的
    good = [t for t in tried if t['ok']]
    best = min(good, key=lambda t: (t['cost'] is None, t['cost'] or 0)) if good else None
    cache[provider] = {'model': best['model'] if best else '', 'at': time.time(), 'tried': tried}
    _save(cache)
    return cache[provider]['model']


def forget(provider):
    """调用报“模型不可用”时清掉缓存，下次重新识别。"""
    cache = _load(); cache.pop(provider, None); _save(cache)
