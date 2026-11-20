"""自动选择写入模型：用户使用时识别当前可用的模型，按价格选最便宜且够用的一个；不写死模型，不维护价格表，不靠名字猜。

价格从哪里来（按宿主 agent）：
- CodeBuddy / WorkBuddy：它从服务器拉下来的模型配置缓存在本机 ~/.codebuddy/local_storage/，每个模型带官方倍率
  （如 "credits": "x0.08"），直接读取，不花任何额度。
- Qoder：读取官方文档的模型倍率表（docs.qoder.com 模型选择器页面的 Markdown 版，如 Qwen3.8-Flash 0.1×），不花额度。
  文档里没有的模型排在最后；文档读不到时复用已有价格，不额外调用模型测价。
- Claude Code：只有 haiku/sonnet/opus 三档别名（各自指向最新版）。读 Anthropic 官方价格页（Markdown 版），取每一档最新版的价格。
  （短请求实测不可用：提示缓存会让后测的模型显得更便宜，实测曾把 opus 误判为最便宜。）
- Codex：既不给价格也不报告消耗。读取 OpenAI 官方价格页（platform.openai.com/docs/pricing），
  直接解析明确价格表；读取失败时复用价格缓存或模型说明，不调用模型整理价格。
选择：先复用有来源的端到端验收，按质量、速度和实际token筛选，再比较价格；无合格记录时最多两次条件/更正/建议准入，失败不回退到未验收默认模型。
结果缓存在 ~/.hyperthymesia/models.json；模型列表变化、30 天到期或调用报“模型不可用”时重新识别。"""
import json, os, re, shutil, subprocess, time, urllib.request
from pathlib import Path

from . import paths

TTL = 30 * 86400
SKIP = re.compile(r'^(auto|custom-local:.*|codex-auto-review)$', re.I)
PROBE_SYSTEM = '你是信息抽取程序。只回复一个 JSON 对象，不要任何其他文字。'
TINY_PROMPT = '只回复 {"ok":true}'
OPENAI_PRICING = 'https://platform.openai.com/docs/pricing'   # openai.com/api/pricing 对脚本返回 403（已实测）
CLAUDE_PRICING = 'https://platform.claude.com/docs/en/about-claude/pricing.md'
QODER_PRICING = 'https://docs.qoder.com/user-guide/chat/model-tier-selector.md'


def _cache_path(): return paths.home() / 'models.json'


def _load():
    try: return json.loads(_cache_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _save(d):
    """内容未变不写（避免诊断或并发写入无谓刷新文件）；变了先写临时文件再替换，读者不会看到半截文件。"""
    text = json.dumps(d, ensure_ascii=False, indent=1); p = _cache_path()
    try:
        if p.read_text(encoding='utf-8') == text: return
    except OSError: pass
    tmp = p.with_name(p.name + '.%d.tmp' % os.getpid()); tmp.write_text(text, encoding='utf-8'); os.replace(str(tmp), str(p))


def _why(r):
    """准入未过的原因：优先判定理由，其次质量问题/错误；都没有时指向真实存放位置。"""
    return ','.join(r.get('reasons') or r.get('quality_issues') or ([r['error']] if r.get('error') else [])) or \
        '无记录原因，见%s中checked' % _cache_path()


# ---------------------------------------------------------------- 可用模型
def list_models(provider):
    from .install import codebuddy_exe
    from .providers import qodercli_cmd, codebuddy_cmd, _run_cli
    try:
        if provider == 'codebuddy' and codebuddy_exe():
            # CodeBuddy 没有列模型的子命令（“codebuddy models”会被当成一句提问交给 agent）；--help 里 --model 的说明列出了可用模型
            out = _run_cli(codebuddy_cmd() + ['--help'], agent='codebuddy', capture_output=True, text=True, encoding='utf-8', timeout=120).stdout
            m = re.search(r'Currently supported:\s*\(([^)]*)\)', out)
            return [i.strip() for i in m.group(1).split(',') if i.strip()] if m else []
        if provider == 'qoder' and qodercli_cmd():
            out = _run_cli(qodercli_cmd() + ['--list-models'], agent='qoder', capture_output=True, text=True, encoding='utf-8', timeout=120,
                                 stdin=subprocess.DEVNULL).stdout
            return [l.strip() for l in out.splitlines()[1:] if l.strip()]
        if provider == 'codex':
            return [m['slug'] for m in _codex_cache().get('models', []) if m.get('visibility', 'list') == 'list']
        if provider == 'dsh' and shutil.which('dsh'):
            return list(deepseek_prices())
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
    d = Path(os.environ.get('CODEBUDDY_CONFIG_DIR') or Path.home() / '.codebuddy') / 'local_storage'
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


DEEPSEEK_PRICING = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing.md'


def deepseek_prices():
    """DeepSeek 官方价格页（Markdown 版）：表头行列出模型名（如 deepseek-flash(1)），取高峰时段“缓存未命中输入”与“输出”单价（元/百万 token），
    按写入以输入为主 9:1 加权。dsh 的 deepseek-official 路由会把模型名原样传给官方接口，所以页面上的模型名就是可用模型。"""
    try: md = _fetch(DEEPSEEK_PRICING)
    except Exception: return {}
    names = []; inp = {}; outp = {}
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if not names and len(cells) > 1 and re.fullmatch(r'模型|MODEL', cells[0]):
            names = [re.sub(r'\(.*?\)', '', c).strip() for c in cells if re.match(r'deepseek', c, re.I)]
        if not names or '高峰' not in line: continue
        vals = [float(m) for m in re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*元', line)][-len(names):]
        if len(vals) != len(names): continue
        if '未命中' in line: inp = dict(zip(names, vals))
        elif '输出' in line: outp = dict(zip(names, vals))
    return {n: inp[n] * 0.9 + outp[n] * 0.1 for n in names if n in inp and n in outp}


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
    """只解析价格页里明确的三列价格表；不再调用模型整理价格。读不到时用已有价格/模型说明。"""
    try: text = _fetch(OPENAI_PRICING)
    except Exception: return {}
    out = {}
    for line in text.splitlines():
        if '|' not in line and '<tr' not in line: continue
        clean = re.sub(r'<[^>]+>', ' ', line)
        names = [m for m in ids if re.search(r'(?<![\w.-])' + re.escape(m) + r'(?![\w.-])', clean)]
        nums = re.findall(r'\$([0-9]+(?:\.[0-9]+)?)', clean)
        if len(names) == 1 and len(nums) == 3:
            out[names[0]] = float(nums[0]) * .9 + float(nums[2]) * .1
    return out


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
        return got, '官方文档不可读，仅复用已有价格；不额外调用模型测价'
    if provider == 'dsh':
        p = deepseek_prices()
        return p, ('DeepSeek 官方价格页' if p else '价格页读取失败')
    if provider == 'codex':
        p = codex_prices(ids)
        return p or {k:v for k,v in (old or {}).items() if k in ids}, ('OpenAI 官方价格页' if p else '已有价格或模型说明，无模型测价')
    return {}, '无'


# ---------------------------------------------------------------- 质量、速度和实际 token 准入
# 短批/准入材料的宽松上限，不截断正式写入、不改变批量阈值。
SELECTION_VERSION = 4
MAX_SCREEN_SECONDS = 120
MAX_OUTPUT_RATIO = 4
MAX_CANDIDATES = 4   # 准入最多试探4个最便宜的候选（Qoder反馈：2个太少，好用的模型轮不到）
PROBE_PROMPT = (
    '抽取以下三轮的当前事实和未确认建议，只回复JSON：{\"facts\":{\"timeout\":\"…\",\"condition\":\"…\",'
    '\"reviewer\":\"…\",\"release\":\"…\"},\"suggestions\":[\"…\"]}。数值带单位，条件不能省略，不保存客套。\n'
    '用户：批处理超时45秒，仅工作日启用。评审人Marco。\n'
    '助手：建议失败时先保留现场，再检查日志。我也可以帮你写通知。\n'
    '用户：超时改成60秒，仍仅工作日启用；评审改成Priya。\n'
    '助手：明白；保留现场、检查日志只是建议，还未获采纳。\n'
    '用户：每周四发布，其他不变。')


def _screen(row):
    reasons = []; warnings = []
    if row.get('quality_pass') is not True: reasons.append('质量或回复格式未通过')
    seconds = row.get('seconds')
    if not isinstance(seconds, (int, float)) or not 0 < seconds <= MAX_SCREEN_SECONDS:
        reasons.append('耗时未通过')
    inp, out = row.get('input_tokens'), row.get('output_tokens')
    known = (row.get('usage_status') != 'unknown' and isinstance(inp, (int, float)) and inp > 0
             and isinstance(out, (int, float)) and out > 0)
    if known:
        if out / inp > MAX_OUTPUT_RATIO: reasons.append('已知输出输入比例超限')
    else:
        warnings.append('token用量未知，未检查输出输入比例')
    return not reasons, reasons, warnings


def _acceptable(row): return _screen(row)[0]


def _probe_quality(got):
    """只评分这份固定准入题；不拿这些匹配规则审核用户真实记忆。"""
    if not isinstance(got, dict) or not isinstance(got.get('facts'), dict):
        return False, ['回复缺少facts对象']
    facts = got['facts']; issues = []; warnings = []
    timeout = re.sub(r'\s+', '', str(facts.get('timeout', ''))).casefold()
    if timeout not in ('60秒', '60s', '60seconds', '60second', '1分钟', '1min', '1minute'):
        issues.append('超时新值未完整保留')
    condition = re.sub(r'\s+', '', str(facts.get('condition', '')))
    if not re.fullmatch(r'(仅|只)(在)?工作日(才)?(启用|开启|运行|生效)', condition):
        issues.append('工作日限定未完整保留')
    if str(facts.get('reviewer', '')).strip().casefold() != 'priya': issues.append('评审人新值错误')
    release = re.sub(r'\s+', '', str(facts.get('release', '')))
    # 字段名 release 已表明是发布，值只写“每周四”也算完整。
    if not re.fullmatch(r'每(周|星期|礼拜)(四|4)(发布|上线)?', release): issues.append('每周四发布未完整保留')
    suggestions = got.get('suggestions')
    if not isinstance(suggestions, list) or not suggestions or not all(isinstance(x, str) for x in suggestions):
        issues.append('未确认建议格式错误')
    else:
        text = '\n'.join(suggestions)
        if not all(k in text for k in ('现场', '日志')): issues.append('具体建议遗漏')
        if '通知' in text: warnings.append('保存了写通知的客套提议')
    # 客套提议只记警告：事实与具体建议都对时，多存一句客套不应让整个模型不可用（Qoder 反馈）。
    return not issues, issues + warnings


def writer_parse(text):
    from . import writer
    return writer.parse(text)


def acceptance():
    """已有验收数据与本地准入结果；不发请求、不读取对话库。"""
    p = Path(__file__).parent / 'rules' / 'model_acceptance.json'
    try: return json.loads(p.read_text(encoding='utf-8')).get('observations', [])
    except (OSError, ValueError): return []


def _probe(provider, model):
    from . import providers, writer
    from .redact import redact
    old = os.environ.get('HYPERTHYMESIA_MODEL'); os.environ['HYPERTHYMESIA_MODEL'] = model
    started = time.monotonic()
    row = {'quality_pass': False, 'source': '条件、更正、建议准入题'}
    try:
        rep = providers.call(paths.home(), PROBE_SYSTEM, PROBE_PROMPT)
        row['reply'] = redact(rep.text)[0]
        # 先保存用量；格式错误也不能抹掉已发生的消耗。
        row.update(input_tokens=rep.usage.get('input_tokens', 0), output_tokens=rep.usage.get('output_tokens', 0),
                   cost=rep.usage.get('cost'), usage_status=rep.usage.get('usage_status'))
        good, issues = _probe_quality(writer.parse(rep.text)); row['quality_issues'] = issues
        row['quality_pass'] = good
    except Exception as exc:
        row['error'] = redact(str(exc))[0][:300]
    finally:
        row['seconds'] = max(0.001, round(time.monotonic() - started, 3))
        if old is None: os.environ.pop('HYPERTHYMESIA_MODEL', None)
        else: os.environ['HYPERTHYMESIA_MODEL'] = old
    row['ok'], row['reasons'], row['warnings'] = _screen(row)
    if row['warnings']: row['usage_status'] = 'unknown'
    else: row['usage_status'] = 'reported'
    directory = paths.home() / 'logs'; directory.mkdir(exist_ok=True)
    with (directory / 'models.log').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(row, provider=provider, model=model), ensure_ascii=False) + '\n')
    return row


def choose(provider, refresh=False):
    """先用已有验收筛质量/速度/token，再比较价格；只有无可用验收时才做有限准入。"""
    from .providers import ProviderError
    cache = _load(); c = cache.get(provider) or {}
    ids = [i for i in list_models(provider) if not SKIP.match(i)]
    evidence = [r for r in acceptance() if r.get('provider') == provider and r.get('model') in ids]
    import hashlib
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    if (not refresh and c.get('selection_version') == SELECTION_VERSION and c.get('evidence') == fingerprint
            and time.time() - c.get('at', 0) < TTL and c.get('ids') == ids and c.get('model')):
        return c['model']
    # 验收未过期时沿用；过期模型不靠旧小题结果继续放行。
    recent = {}
    for row in evidence:
        try: age = time.time() - __import__('datetime').datetime.fromisoformat(row['at']).timestamp()
        except (KeyError, ValueError): continue
        if 0 <= age < TTL: recent.setdefault(row['model'], []).append(row)
    # 同一模型任一已有质量/性能失败不能被另一次简单通过掩盖。
    # 旧自动结果中明确质量通过、仅缺token统计的记录可以重新判定，无需再次收费试探。
    if time.time() - c.get('at', 0) < TTL:
        for row in c.get('checked', []):
            if row.get('model') in ids and row.get('quality_pass') is not True and row.get('reply') and not row.get('error'):
                # 评分标准变了：用已保存的准入回复在本地重判，不重新请求模型。
                try: good, issues = _probe_quality(writer_parse(row['reply']))
                except ValueError: continue
                row['quality_pass'] = good; row['quality_issues'] = issues; row['rescored'] = True
            if row.get('model') in ids and row.get('quality_pass') is True and _acceptable(row):
                recent.setdefault(row['model'], []).append(row)
    qualified = [m for m, rows in recent.items() if all(_acceptable(r) for r in rows)]
    price, source = prices(provider, ids, c.get('prices'))
    preferred = codex_affordable(ids) if provider == 'codex' else ids
    order = sorted(preferred, key=lambda m: (m not in price, price.get(m, float('inf'))))
    checked = []
    for m, rows in recent.items():
        for r in rows:
            ok, reasons, warnings = _screen(r)
            checked.append(dict(r, model=m, ok=ok, reasons=reasons, warnings=warnings))
    chosen = next((m for m in order if m in qualified), '')
    if not chosen:
        # 旧缓存若没有新标准的数据，不算准入通过；不再遍历整张模型表。
        for m in [m for m in order if m not in recent][:MAX_CANDIDATES]:
            row = _probe(provider, m); checked.append(dict(row, model=m))
            if row['ok']: chosen = m; break
    cache[provider] = {'model': chosen, 'at': time.time(), 'ids': ids, 'prices': price,
                       'source': source, 'checked': checked, 'selection_version': SELECTION_VERSION, 'evidence': fingerprint}
    _save(cache)
    if not chosen:
        details = '; '.join('%s: %s' % (r.get('model'), _why(r)) for r in checked)
        raise ProviderError('未选到可用后台模型，积压保留。' + details +
                            '；试探原文见logs/models.log，判定见models.json。用户可明确指定本机支持的模型：在' + str(paths.home() / 'config.toml') +
                            '中设置 [writer] model = "实际支持的模型ID"。显式选择跳过自动准入，不代表已通过质量验收；不会自动改用其他宿主或付费API。')
    return chosen


def explain(provider):
    c = _load().get(provider) or {}
    if not c: return '尚未识别（首次写入优先复用已有验收；无记录时最多4次准入请求）'
    stale = c.get('selection_version') != SELECTION_VERSION
    selected = next((r for r in c.get('checked', []) if r.get('model') == c.get('model')), {})
    note = '旧版缓存待重新评估，不直接沿用' if stale else '已按质量与速度筛选'
    if c.get('model') and _screen(selected)[2]: note += '；token用量未知，未检查用量比例'
    if not c.get('model') and c.get('checked'):
        note += '；' + '; '.join('%s:%s' % (r.get('model'), _why(r)) for r in c['checked'])
    return '%s（%s；依据：%s）' % (c.get('model') or '无通过准入的模型', note, c.get('source', ''))


def forget(provider):
    cache = _load(); cache.pop(provider, None); _save(cache)
