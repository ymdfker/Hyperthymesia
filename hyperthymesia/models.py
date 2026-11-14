"""自动选择写入模型：用户使用时识别当前可用的模型，按价格选最便宜且够用的一个；不写死模型，不维护价格表，不靠名字猜。

价格从哪里来（按宿主 agent）：
- CodeBuddy / WorkBuddy：它从服务器拉下来的模型配置缓存在本机 ~/.codebuddy/local_storage/，每个模型带官方倍率
  （如 "credits": "x0.08"），直接读取，不花任何额度。
- Qoder：读取官方文档的模型倍率表（docs.qoder.com 模型选择器页面的 Markdown 版，如 Qwen3.8-Flash 0.1×），不花额度。
  文档里没有的模型排在最后；文档读不到时才退回实测（对每个模型发一次短请求，按宿主报告的消耗比较）。
- Claude Code：只有 haiku/sonnet/opus 三档别名（各自指向最新版）。读 Anthropic 官方价格页（Markdown 版），取每一档最新版的价格。
  （短请求实测不可用：提示缓存会让后测的模型显得更便宜，实测曾把 opus 误判为最便宜。）
- Codex：既不给价格也不报告消耗。读取 OpenAI 官方价格页（platform.openai.com/docs/pricing），
  截取各模型名附近的文字，由便宜模型整理出价格；读取失败时退回 Codex 模型说明里标为 affordable 的模型。
选择：按价格从低到高，对候选依次做一次能力试探（必须正确输出 JSON：太弱的模型会把记忆写坏），第一个通过的即选中。
结果缓存在 ~/.hyperthymesia/models.json；模型列表变化、30 天到期或调用报“模型不可用”时重新识别。"""
import json, os, re, shutil, subprocess, time, urllib.request
from pathlib import Path

from . import paths

TTL = 30 * 86400
SKIP = re.compile(r'^(auto|custom-local:.*|codex-auto-review)$', re.I)
PROBE_SYSTEM = '你是信息抽取程序。只回复一个 JSON 对象，不要任何其他文字。'
PROBE_PROMPT = ('从下面对话抽取事实，回复 {"facts":[{"key":"…","value":"…"}]}，key 只用 page_size 和 reviewer。\n'
                '用户：默认分页原来是 20，现在改成 50。代码评审以后交给 Marco。')
TINY_PROMPT = '只回复 {"ok":true}'
OPENAI_PRICING = 'https://platform.openai.com/docs/pricing'   # openai.com/api/pricing 对脚本返回 403（已实测）
CLAUDE_PRICING = 'https://platform.claude.com/docs/en/about-claude/pricing.md'
QODER_PRICING = 'https://docs.qoder.com/user-guide/chat/model-tier-selector.md'


def _cache_path(): return paths.home() / 'models.json'


def _load():
    try: return json.loads(_cache_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _save(d): _cache_path().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')


# ---------------------------------------------------------------- 可用模型
def list_models(provider):
    from .install import codebuddy_exe
    from .providers import qodercli_cmd
    try:
        if provider == 'codebuddy' and codebuddy_exe():
            # CodeBuddy 没有列模型的子命令（“codebuddy models”会被当成一句提问交给 agent）；--help 里 --model 的说明列出了可用模型
            out = subprocess.run([codebuddy_exe(), '--help'], capture_output=True, text=True, encoding='utf-8', timeout=120).stdout
            m = re.search(r'Currently supported:\s*\(([^)]*)\)', out)
            return [i.strip() for i in m.group(1).split(',') if i.strip()] if m else []
        if provider == 'qoder' and qodercli_cmd():
            out = subprocess.run(qodercli_cmd() + ['--list-models'], capture_output=True, text=True, encoding='utf-8', timeout=120,
                                 stdin=subprocess.DEVNULL).stdout
            return [l.strip() for l in out.splitlines()[1:] if l.strip()]
        if provider == 'codex':
            return [m['slug'] for m in _codex_cache().get('models', []) if m.get('visibility', 'list') == 'list']
        if provider == 'claude' and shutil.which('claude'):
            return ['haiku', 'sonnet', 'opus']
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return []


def _codex_cache():
    try: return json.loads((Path.home() / '.codex' / 'models_cache.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


# ---------------------------------------------------------------- 价格
def codebuddy_prices():
    """从 CodeBuddy 本机缓存的模型配置里读官方倍率：{模型 ID: 倍率}。"""
    out = {}
    d = Path.home() / '.codebuddy' / 'local_storage'
    for f in sorted(d.glob('*.info'), key=lambda p: p.stat().st_mtime) if d.exists() else []:
        try:
            t = f.read_text(encoding='utf-8', errors='replace')
            obj, _ = json.JSONDecoder().raw_decode(t[t.index('{'):])
        except (ValueError, OSError):
            continue
        for m in ((obj.get('data') or {}).get('models') or []) if isinstance(obj, dict) else []:
            c = re.fullmatch(r'x?\s*([0-9.]+)', str(m.get('credits', '')).strip())
            if m.get('id') and c: out[m['id']] = float(c.group(1))   # 较新的文件覆盖较旧的
    return out


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; hyperthymesia)'})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode('utf-8', 'replace')


def qoder_doc_prices(ids):
    """Qoder 官方文档里的模型倍率：表格行“| 模型名 | 说明 | 0.1× |”，有划线的旧价时取最后一个（当前价）。"""
    try: md = _fetch(QODER_PRICING)
    except Exception: return {}
    low = {i.lower(): i for i in ids}; out = {}
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 2: continue
        name = re.sub(r'[*\\~]|\(.*?\)', '', cells[0]).strip().lower()
        nums = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*[×x]', ' '.join(cells[1:]))
        if name in low and nums: out[low[name]] = float(nums[-1])
    return out


def claude_prices(ids):
    """Anthropic 官方价格表：每个别名（haiku/sonnet/opus）取版本号最高的那一行的输入、输出价（美元/百万 token）。"""
    try: md = _fetch(CLAUDE_PRICING)
    except Exception: return {}
    best = {}
    for line in md.splitlines():
        m = re.search(r'Claude (Haiku|Sonnet|Opus) ([0-9.]+)', line)
        nums = re.findall(r'\$([0-9.]+)\s*(?:USD\s*)?/\s*MTok', line)
        if not m or len(nums) < 2: continue
        alias, ver = m.group(1).lower(), float(m.group(2).rstrip('.'))
        # 页面里同一模型出现在多张表中，第一次出现的是基础价格表；同一档取版本号最高的
        if alias in ids and (alias not in best or ver > best[alias][0]):
            best[alias] = (ver, float(nums[0]) * 0.9 + float(nums[-1]) * 0.1)   # 写入以输入为主：按 9:1 加权
    return {a: v[1] for a, v in best.items()}


def measure(provider, model):
    """极短请求的实际消耗（宿主报告的 credit 或美元）；失败返回 None。"""
    from . import providers
    old = os.environ.get('HYPERTHYMESIA_MODEL'); os.environ['HYPERTHYMESIA_MODEL'] = model
    try: return providers.call(paths.home(), PROBE_SYSTEM, TINY_PROMPT).usage.get('cost')
    except Exception: return None
    finally:
        if old is None: os.environ.pop('HYPERTHYMESIA_MODEL', None)
        else: os.environ['HYPERTHYMESIA_MODEL'] = old


def codex_prices(ids):
    """读取 OpenAI 官方价格页，请便宜模型整理出这些模型的价格（美元/百万 token：输入、输出）；失败返回 {}。"""
    from . import providers, writer
    try:
        html = _fetch(OPENAI_PRICING)
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'(?s)<(script|style)[^>]*>.*?</\1>', ' ', html)))
        # 页面很大：只截取各模型名附近的文字交给模型整理
        text = ' … '.join(text[max(0, m.start() - 80):m.end() + 300] for i in ids for m in list(re.finditer(re.escape(i), text))[:3])[:40000]
        if not text: return {}
        # 整理价格这一次调用用 Codex 自己的默认模型，避免“选模型需要先有模型”的循环
        os.environ.setdefault('HYPERTHYMESIA_MODEL', providers.DEFAULT_MODEL.get('codex', ''))
        rep = providers.call(paths.home(), PROBE_SYSTEM, '下面是 OpenAI 官方价格页的文字。只针对这些模型：' + '、'.join(ids) +
                             '，回复 {"prices":{"模型ID":[输入价, 输出价]}}（美元/百万 token），页面里没有的模型不要列。\n' + text)
        got = writer.parse(rep.text).get('prices', {}) or {}
        # 写入时输入远多于输出：按 9:1 加权折成一个可比较的单价
        return {k: float(v[0]) * 0.9 + float(v[1]) * 0.1 for k, v in got.items() if k in ids and isinstance(v, list) and len(v) == 2}
    except Exception:
        return {}
    finally:
        if os.environ.get('HYPERTHYMESIA_MODEL') == providers.DEFAULT_MODEL.get('codex', ''): os.environ.pop('HYPERTHYMESIA_MODEL', None)


def codex_affordable(ids):
    """价格页读不到时的退路：Codex 模型说明里标为 affordable / 低价的模型排前面。"""
    desc = {m['slug']: (m.get('description') or '').lower() for m in _codex_cache().get('models', [])}
    return sorted(ids, key=lambda i: (not re.search(r'affordable|cheap|low[- ]cost|easier', desc.get(i, '')), ids.index(i)))


def prices(provider, ids, old):
    """返回 ({模型: 价格}, 依据)；Qoder / Claude 只给缓存里没有的新模型补测，其余沿用缓存。"""
    if provider == 'codebuddy':
        return codebuddy_prices(), '宿主本机缓存的官方倍率'
    if provider == 'qoder':
        p = qoder_doc_prices(ids)
        if p: return p, 'Qoder 官方文档倍率'
    if provider == 'claude':
        p = claude_prices(ids)
        return p, ('Anthropic 官方价格页' if p else '价格页读取失败')
    if provider == 'qoder':
        got = {k: v for k, v in (old or {}).items() if k in ids}
        for m in ids:
            if m not in got:
                c = measure(provider, m)
                if c is not None: got[m] = c
        return got, '短请求实测（官方文档读取失败时的退路）'
    if provider == 'codex':
        p = codex_prices(ids)
        return p, ('OpenAI 官方价格页' if p else '价格页读取失败，按模型说明')
    return {}, '无'


# ---------------------------------------------------------------- 能力试探与选择
def _probe(provider, model):
    from . import providers, writer
    old = os.environ.get('HYPERTHYMESIA_MODEL'); os.environ['HYPERTHYMESIA_MODEL'] = model
    try:
        rep = providers.call(paths.home(), PROBE_SYSTEM, PROBE_PROMPT)
        got = {f.get('key'): str(f.get('value')) for f in writer.parse(rep.text).get('facts', [])}
        return '50' in got.get('page_size', '') and 'marco' in got.get('reviewer', '').lower()
    except Exception:
        return False
    finally:
        if old is None: os.environ.pop('HYPERTHYMESIA_MODEL', None)
        else: os.environ['HYPERTHYMESIA_MODEL'] = old


def choose(provider, refresh=False):
    """该提供方当前最便宜且够用的模型；识别不出时返回空串（由调用方用宿主默认模型）。"""
    cache = _load(); c = cache.get(provider) or {}
    ids = [i for i in list_models(provider) if not SKIP.match(i)]
    if c and not refresh and time.time() - c.get('at', 0) < TTL and c.get('ids') == ids and c.get('model'): return c['model']
    price, source = prices(provider, ids, c.get('prices'))
    order = sorted([i for i in ids if i in price], key=lambda i: price[i]) + \
            (codex_affordable([i for i in ids if i not in price]) if provider == 'codex' else [])
    chosen = ''; checked = []
    for m in order:
        ok = _probe(provider, m); checked.append({'model': m, 'ok': ok})
        if ok: chosen = m; break
    cache[provider] = {'model': chosen, 'at': time.time(), 'ids': ids, 'prices': price, 'source': source, 'checked': checked}
    _save(cache)
    return chosen


def explain(provider):
    """给 doctor 用：选中的模型与依据。"""
    c = _load().get(provider) or {}
    if not c: return '尚未识别（第一次写入时自动识别）'
    p = c.get('prices', {}).get(c.get('model'))
    return '%s（依据：%s%s）' % (c.get('model') or '无可用模型', c.get('source', ''), '，价格 %s' % p if p is not None else '')


def forget(provider):
    cache = _load(); cache.pop(provider, None); _save(cache)
