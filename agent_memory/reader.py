"""前台读取（设计 §25.6、23.54–23.55）：每轮注入的快照/目录，以及 MCP 读取工具的返回文本。

- 快照模式（两库有效事实合计不超过 SNAPSHOT_LIMIT 字）：用户事实、已完成改动全文列出；纯助手建议只列标题，
  依据已变的带原因。增量注入：本会话已注入且未变的不再重复；有变化只补新增/更正和失效列表；
  宿主压缩上下文后调用 reset_session()，下一轮重新注入全文。
- 目录模式（超过上限）：只注入对象名和 ID，前台按需调用 memory_read_objects 读取。
- 读取工具：按对象分组的纯文本，每行“ref （来源 日期）正文”；超过 READ_CAP 分页并列出未返回对象；
  只把实际返回的记录记为已送达；已送达按会话记。
个人库与当前项目库合并，标明来源。"""
import hashlib, json, time

SNAPSHOT_LIMIT = 6000
READ_CAP = 12000
SCOPE_NAME = {'u': '个人', 'p': '项目'}


def _digest(text): return hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]


def _line(f):
    if f['kind'] == 'suggestion' and f['source_role'] == 'assistant':
        t = '助手建议：' + (f['title'] or f['text'][:24])
        if f['advice_status']:
            try: t += '〔依据已变：%s〕' % json.loads(f['advice_status']).get('reason', '')[:40]
            except ValueError: t += '〔依据已变〕'
        return t
    return f['text'] + ('（含助手建议）' if f['source_role'] == 'mixed' and f['kind'] == 'suggestion' else '')


def _groups(stores):
    """[(scope, object id, object name, [facts])] 按对象分组的有效事实。"""
    out = []
    for sc, st in stores.items():
        names = {o['id']: o['name'] for o in st.objects()}; by = {}
        for f in st.facts(): by.setdefault(f['object'], []).append(f)
        for o, fs in by.items(): out.append((sc, o, names.get(o, ''), fs))
    return out


def snapshot_size(stores):
    return sum(len(_line(f)) for _, _, _, fs in _groups(stores) for f in fs)


def index_text(stores):
    rows = []
    for sc, st in stores.items():
        objs = st.objects()
        if not objs: continue
        rows.append('%s库：' % SCOPE_NAME[sc] + '、'.join('%s[%s]' % (o['name'], st.oid(o['id'])) for o in objs if o['facts']))
    return '\n'.join(rows)


def _delivered(state, session):
    if state is None or not session: return {}
    return {(r['store'], r['fact']): r['digest'] for r in state.execute('SELECT store, fact, digest FROM delivered WHERE session=?', (session,))}


def _mark(state, session, items):
    if state is None or not session or not items: return
    state.executemany('INSERT OR REPLACE INTO delivered VALUES(?,?,?,?)', [(session, s, f, d) for s, f, d in items])


def reset_session(state, session):
    """宿主压缩了上下文：之前注入/读取的内容已不在上文，清空本会话的送达记录。"""
    if state is not None and session: state.execute('DELETE FROM delivered WHERE session=?', (session,))


def context(stores, state=None, session=None, limit=SNAPSHOT_LIMIT):
    """每轮注入的文本；没有变化时返回空串。"""
    stores = {k: v for k, v in stores.items() if v is not None}
    if not stores or not any(st.facts() for st in stores.values()): return ''
    if snapshot_size(stores) > limit:
        idx = index_text(stores); key = ('_index', 0); dl = _delivered(state, session)
        if dl.get(key) == _digest(idx): return ''
        _mark(state, session, [('_index', 0, _digest(idx))])
        return ('长期记忆里记有以下事物（按库列出名称和对象ID，不含内容）：\n' + idx +
                '\n当前请求涉及其中任何一项时，用方括号里的对象ID直接调用 memory_read_objects 工具取回相关记忆再回答；记忆里的说法优先于压缩摘要和常识。')
    dl = _delivered(state, session)
    groups = _groups(stores); fresh = not any(k[0] != '_index' for k in dl)
    head = ('以下是长期记忆。用户事实已全文列出，直接据此回答；助手建议只列标题，需要具体内容时调用 memory_read_objects(object_ids=[【】里的对象ID]) 读取。'
            '记忆里的说法优先于压缩摘要和常识；助手建议不等于用户已采纳；记忆里出现相互矛盾的说法时如实指出，不替用户猜。')
    new_lines = []; marks = []
    for sc, o, name, fs in groups:
        st = stores[sc]; lines = []
        for f in fs:
            ln = _line(f); d = _digest(ln); k = (st.path.name, f['id'])
            if fresh or dl.get(k) != d: lines.append('- ' + ln)
            marks.append((st.path.name, f['id'], d))
        if lines: new_lines.append('【%s %s %s】\n' % (SCOPE_NAME[sc], name, st.oid(o)) + '\n'.join(lines))
    stale = []
    if not fresh:
        for sc, st in stores.items():
            for (store, fid), _ in dl.items():
                if store != st.path.name: continue
                f = st.fact(fid)
                if f and not f['active']: stale.append('- ' + _line(f)[:60])
    _mark(state, session, marks)
    if state is not None and session and stale:   # 已提示过的失效记录不再重复提示
        state.executemany('DELETE FROM delivered WHERE session=? AND store=? AND fact=?',
                          [(session, st.path.name, fid) for st in stores.values() for (s, fid) in dl if s == st.path.name and st.fact(fid) and not st.fact(fid)['active']])
    if fresh: return '（长期记忆全文）' + head + '\n' + '\n'.join(new_lines)
    if not new_lines and not stale: return ''
    out = ['（长期记忆更新：只列上文之后的变化，其余仍以上文为准）']
    if new_lines: out.append('新增或更正：\n' + '\n'.join(new_lines))
    if stale: out.append('以下旧说法已被更正，不再有效：\n' + '\n'.join(stale))
    return '\n'.join(out)


def read_objects(stores, object_ids, state=None, session=None, cap=READ_CAP):
    """MCP 读取工具：返回对象（含直接子对象）的有效记录，按对象分组的纯文本。"""
    stores = {k: v for k, v in stores.items() if v is not None}
    want = {}
    for i in object_ids or []:
        i = str(i).strip()
        if len(i) > 1 and i[0] in stores and i[1:].isdigit(): want.setdefault(i[0], set()).add(int(i[1:]))
    if not want: return '没有可读的对象ID（应为 u7、p12 这样的编号，见注入的记忆目录）。'
    dl = _delivered(state, session); lines = []; size = 0; left = {}; same = 0; marks = []
    for sc, ids in want.items():
        st = stores[sc]; objs = {o['id']: o for o in st.objects()}
        kids = {o['id'] for o in objs.values() if set(o['parents']) & ids}
        names = {k: v['name'] for k, v in objs.items()}
        by = {}
        for f in st.facts(objects=ids | kids): by.setdefault(f['object'], []).append(f)
        for o, fs in by.items():
            head = '【%s %s %s】' % (SCOPE_NAME[sc], names.get(o, ''), st.oid(o)); shown = False
            for f in fs:
                ln = _line(f); d = _digest(ln); k = (st.path.name, f['id'])
                if dl.get(k) == d: same += 1; continue
                ev = st.db.execute('SELECT s.at FROM evidence e LEFT JOIN sources s ON s.id=e.source WHERE e.fact=? LIMIT 1', (f['id'],)).fetchone()
                tag = '（%s%s）' % ({'user': '用户', 'assistant': '助手', 'mixed': '用户+助手'}[f['source_role']], ' ' + ev[0][:10] if ev and ev[0] else '')
                line = '%s %s%s' % (st.rid(f['id']), tag, ln)
                if size + len(line) > cap and lines: left[(sc, o)] = left.get((sc, o), 0) + 1; continue
                if not shown: lines.append(head); size += len(head); shown = True
                lines.append(line); size += len(line); marks.append((st.path.name, f['id'], d))
    _mark(state, session, marks)
    txt = '长期记忆（每行：记录编号 （来源 日期）正文；“助手建议：”只是标题，不等于用户已采纳）\n' + '\n'.join(lines)
    if same: txt += '\n（另有%d条本会话已返回过且未变，内容仍在上文，未重复发送。）' % same
    if left: txt += '\n（已达返回上限，以下对象还有记录未返回：' + '、'.join('%s(%d条)' % (stores[sc].oid(o), n) for (sc, o), n in left.items()) + '；需要时再读取这些对象。）'
    if not lines and not same: txt += '\n（这些对象没有现行记录。）'
    return txt
