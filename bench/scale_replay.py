"""回归测试：用原型的 240 轮规模场景（9 主题、60 属性）从空库重放写入，对比原型指标（设计 23.49–23.57）。
场景数据在 agent-memtest 测试目录里，不进本仓库。个人话题（家人、猫、健身、自家装修、旅行、车）应进个人库，
门店/总部/网店是用户的生意，同样属于个人生活。聊天场景没有工作区，默认不开项目库（NO_PROJECT=1），全部进个人库；
设 NO_PROJECT=0 可测作用域划分。评分按两个库合并后的有效事实计算。

用法：python3 bench/scale_replay.py <输出目录>     （AGENT_MEMORY_PROVIDER / AGENT_MEMORY_MODEL 选择写入模型）
输出：<输出目录>/rows.json（每批）、score.json（评分）"""
import json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_memory import writer
from agent_memory.store import Store, state

SC = Path(os.environ.get('SCALE_SCENARIO', str(Path.home() / 'Documents/projects/agent-memtest/codex_idx/scenario_scale')))
BATCH = int(os.environ.get('BATCH', '12'))
PERSONAL = {'朵朵', '林悦', '母亲', '父亲', '用户本人', '年糕', '健身', '自家装修', '日本旅行', '车'}
PRICES = {'codex': (0.2, 0.02, 1.2)}   # gpt-5.6-luna，美元/百万 token：输入、缓存命中、输出


def main():
    out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
    users = json.loads((SC / 'users.json').read_text()); reps = json.loads((SC / 'replies.json').read_text())
    plan = json.loads((SC / 'plan.json').read_text())
    u = Store(out / 'personal.db', 'u'); st = state(out)
    p = None if os.environ.get('NO_PROJECT', '1') == '1' else Store(out / 'project.db', 'p')
    rows_p = out / 'rows.json'; rows = json.loads(rows_p.read_text()) if rows_p.exists() else []
    n = len(plan['rounds'])
    for b, start in enumerate(range(1, n + 1, BATCH), 1):
        if any(r['batch'] == b for r in rows): continue
        turns = [{'session': 'scale', 'turn': i, 'user': users[str(i)], 'assistant': reps[str(i)], 'at': ''} for i in range(start, min(start + BATCH, n + 1))]
        r = writer.write_batch(out, {'u': u, 'p': p}, turns, st)
        r.update(batch=b, personal_facts=len(u.facts()), project_facts=len(p.facts()) if p else 0)
        rows.append(r); rows_p.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(json.dumps({k: r[k] for k in ('batch', 'calls', 'new_facts', 'personal_facts', 'project_facts', 'usage')}, ensure_ascii=False), flush=True)
    score(out, plan, u, p, rows)


KEY = {'美团和饿了么都上': ['饿了么'], '只上美团': ['只上美团'], '淘宝和抖音': ['抖音'], '只在淘宝': ['只在淘宝'],
       '只喝茶，最近改喝白茶': ['白茶'], '只喝茶，最爱凤凰单丛': ['单丛'], '京都、大阪和东京': ['东京'], '京都和大阪': ['京都', '大阪'],
       '氨氯地平早晚各一片': ['早晚'], '氨氯地平每天早上一片': ['早上一片'], '每周二四六早上7点': ['二', '四', '六'], '每周一三五早上7点': ['一', '三', '五'],
       '周日上午': ['周日'], '周六上午': ['周六上午'], '岗位空缺': ['空缺'], '5名员工': ['5'], '6名员工': ['6'], '8名员工': ['8'], '10名员工': ['10'],
       '3袋': ['3袋'], '5袋': ['5袋'], '3个月': ['3个月'], '4个月': ['4个月'], '二甲双胍每天两次': ['二甲双胍', '两次']}
EXTRA_KW = {('车', '保险到期'): ['车险', '到期'], ('日本旅行', '出发日期'): ['日本', '旅行']}


def toks(v):
    if v in KEY: return KEY[v]
    nums = re.findall(r'\d+(?:\.\d+)?', v); return nums or [v]


def score(out, plan, u, p, rows):
    both = [x for x in (('u', u), ('p', p)) if x[1]]
    act = [(sc, f) for sc, s in both for f in s.facts() if not f['advice_status']]
    names = {sc: {o['id']: o['name'] for o in s.objects()} for sc, s in both}
    res = []
    for e in plan['expect']:
        if (e['entity'], e['attribute']) == ('日本旅行', '天数'): continue
        ak = e['attr_kw'] + EXTRA_KW.get((e['entity'], e['attribute']), [])
        has = lambda t, v: all(k in t for k in toks(v))
        ent = [(sc, names[sc].get(f['object'], '') + ' ' + f['text'], f) for sc, f in act if any(k in names[sc].get(f['object'], '') + f['text'] for k in e['entity_kw'])]
        cur = [(sc, t) for sc, t, f in ent if has(t, e['final']) and any(k in t for k in ak + [e['attribute']])]
        row = {'id': e['id'], 'entity': e['entity'], 'attribute': e['attribute'], 'current': bool(cur),
               'scope_ok': bool(cur) and (p is None or all(sc == ('u' if e['entity'] in PERSONAL else 'p') for sc, _ in cur[:1]))}
        if len(e['stale']):
            left = [t for sc, t, f in ent if f['source_role'] != 'assistant' and any(k in t for k in ak) and any(has(t, o) for o in e['stale'])
                    and not has(t, e['final']) and not re.search(r'原[为是来]|此前|以前|之前|调整|改[为成到]|由.*[改调涨降提]', t)]
            row['stale_user'] = len(left)
        res.append(row)
    pr = PRICES.get(os.environ.get('AGENT_MEMORY_PROVIDER', 'codex'))
    usd = sum(((r['usage']['input_tokens'] - r['usage']['cached_input_tokens']) * pr[0] + r['usage']['cached_input_tokens'] * pr[1] + r['usage']['output_tokens'] * pr[2]) / 1e6 for r in rows) if pr else None
    summ = {'attrs': len(res), 'current_ok': sum(r['current'] for r in res), 'scope_ok': sum(r['scope_ok'] for r in res),
            'changed': sum(1 for r in res if 'stale_user' in r), 'changed_clean': sum(1 for r in res if 'stale_user' in r and r['current'] and not r['stale_user']),
            'stale_user_attrs': sum(1 for r in res if r.get('stale_user')), 'calls': sum(r['calls'] for r in rows), 'usd': round(usd, 3) if usd is not None else None,
            'personal_facts': len(u.facts()), 'project_facts': len(p.facts()) if p else 0,
            'missing': [(r['entity'], r['attribute']) for r in res if not r['current']],
            'wrong_scope': [(r['entity'], r['attribute']) for r in res if r['current'] and not r['scope_ok']]}
    (out / 'score.json').write_text(json.dumps({'summary': summ, 'rows': res}, ensure_ascii=False, indent=1))
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
