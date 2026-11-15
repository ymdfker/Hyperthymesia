"""hyperthymesia import：把接入之前已经存在的 agent 会话导入记忆（用户要求：不需要确认；可以只导入选中的会话）。

  hyperthymesia import --list [--agent X]                  列出本机各 agent 的会话（编号、项目目录、轮数、最后时间）
  hyperthymesia import --agent X --session ID [ID ...]     只导入选中的会话
  hyperthymesia import --agent X --all [--days N]          导入该 agent 的全部会话（可限最近 N 天）

各家会话记录都在本机：Claude Code ~/.claude/projects/、Codex ~/.codex/sessions/、WorkBuddy ~/.codebuddy/projects/、
Qoder ~/.qoder/projects/*/transcript/、DeepSeek Harness ~/.dsh/sessions/*/*/session.jsonl.zstd。只取用户原话和助手每轮的最终回复（与平时写入同一口径）；
历史轮次的代码改动无法补回（影子仓库只在接入之后拍快照）。导入的轮次进入积压表，随后按项目分批写入，
写入用该 agent 自己最便宜的模型。同一会话里接入之后由钩子记过的轮次不会重复导入。"""
import glob, json, os, time
from pathlib import Path

from . import paths
from .store import state

HOME = lambda: Path(os.environ.get('HOME') or Path.home())


def _rows(p):
    for l in Path(p).read_text(encoding='utf-8', errors='replace').splitlines():
        try: yield json.loads(l)
        except ValueError: pass


def _text(content, kinds=('text', 'input_text', 'output_text')):
    if isinstance(content, str): return content
    return '\n'.join(c.get('text', '') for c in content or [] if isinstance(c, dict) and c.get('type') in kinds)


# ---------------------------------------------------------------- 各家会话记录 -> [(时间, 用户原话, 最终回复)], 工作目录
def _claude_like(path):
    """Claude Code 与 Qoder：type=user/assistant，message.content；工具结果也以 user 身份出现，要跳过。"""
    turns = []; cwd = None; cur = None
    for e in _rows(path):
        cwd = cwd or e.get('cwd')
        m = e.get('message') or {}
        if e.get('type') == 'user' and not e.get('isMeta'):
            c = m.get('content')
            if isinstance(c, list) and any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in c): continue
            t = _text(c).strip()
            if not t or t.startswith('<'): continue          # 斜杠命令、系统注入等不是用户原话
            cur = [e.get('timestamp', ''), t, '']; turns.append(cur)
        elif e.get('type') == 'assistant' and cur is not None:
            t = _text(m.get('content'), ('text',)).strip()
            if t: cur[2] = t                                 # 一轮里最后一段文字即最终回复
    return turns, cwd


def _codebuddy(path):
    turns = []; cwd = None; cur = None
    for e in _rows(path):
        cwd = cwd or e.get('cwd')
        if e.get('type') != 'message': continue
        t = _text(e.get('content')).strip()
        if e.get('role') == 'user' and t: cur = [str(e.get('timestamp', '')), t, '']; turns.append(cur)
        elif e.get('role') == 'assistant' and cur is not None and t: cur[2] = t
    return turns, cwd


def _codex(path):
    turns = []; cwd = None; cur = None
    for e in _rows(path):
        p = e.get('payload') or {}
        if e.get('type') == 'session_meta': cwd = p.get('cwd')
        if e.get('type') == 'turn_context': cwd = cwd or p.get('cwd')
        if e.get('type') == 'event_msg' and p.get('type') == 'user_message' and p.get('message', '').strip():
            cur = [e.get('timestamp', ''), p['message'].strip(), '']; turns.append(cur)
        elif e.get('type') == 'event_msg' and p.get('type') == 'task_complete' and cur is not None and p.get('last_agent_message'):
            cur[2] = p['last_agent_message']
    return turns, cwd


def _dsh(path):
    from .hooks import dsh_read, dsh_turns, dsh_header_is_sub
    text = dsh_read(path)
    if dsh_header_is_sub(text): return [], None                 # 子 agent 的会话：任务不是用户原话
    turns, cwd = dsh_turns(text)
    if cwd and Path(cwd).name == 'writer_work': return [], cwd   # 本框架写入器自己的无头会话，不是用户对话
    return turns, cwd


SOURCES = {
    'claude': (lambda: glob.glob(str(HOME() / '.claude/projects/*/*.jsonl')), _claude_like),
    'codex': (lambda: glob.glob(str(HOME() / '.codex/sessions/**/rollout-*.jsonl'), recursive=True), _codex),
    'codebuddy': (lambda: glob.glob(str(HOME() / '.codebuddy/projects/*/*.jsonl')), _codebuddy),
    'qoder': (lambda: glob.glob(str(HOME() / '.qoder/projects/*/transcript/*.jsonl')), _claude_like),
    'dsh': (lambda: glob.glob(str(HOME() / '.dsh/sessions/*/*/session.jsonl.zstd')), _dsh),
}
SOURCES['workbuddy'] = SOURCES['codebuddy']


def sessions(agent):
    """[{id, path, cwd, turns, last}]，按最后修改时间从新到旧。"""
    files, parse = SOURCES[agent]
    out = []
    for f in files():
        sid = Path(f).parent.name if agent == 'dsh' else Path(f).stem   # dsh：每个会话一个目录，目录名即会话编号
        if agent == 'codex': sid = sid.split('-', 6)[-1] if sid.count('-') >= 6 else sid   # rollout-日期时间-会话编号
        out.append({'id': sid, 'path': f, 'mtime': os.path.getmtime(f)})
    return sorted(out, key=lambda s: -s['mtime'])


def import_sessions(agent, picked, write=True):
    """把选中的会话导入积压表，再按项目写入；返回 {会话: 导入轮数}。"""
    st = state(paths.home()); parse = SOURCES[agent][1]; done = {}; projects = set()
    host = 'codebuddy' if agent == 'workbuddy' else agent
    for s in picked:
        turns, cwd = parse(s['path'])
        turns = [t for t in turns if t[1] and t[2]]          # 只要完整的轮次（有原话也有最终回复）
        _, root = paths.project_db(cwd) if cwd else (None, None)
        project = str(root or '')
        first = st.execute('SELECT MIN(started_at) FROM backlog WHERE session=?', (s['id'],)).fetchone()[0]
        n0 = st.execute('SELECT MAX(turn) FROM backlog WHERE session=?', (s['id'] + ':import',)).fetchone()[0] or 0
        added = 0
        for i, (at, u, a) in enumerate(turns, 1):
            if i <= n0: continue                              # 之前已导入过的轮次
            if first and at and str(at) >= first: continue    # 接入之后由钩子记过的轮次不重复导入
            st.execute('INSERT OR IGNORE INTO backlog(session, turn, project, user_text, assistant_text, started_at, completed_at, diff, numstat, written) '
                       'VALUES(?,?,?,?,?,?,?,?,?,0)', (s['id'] + ':import', i, project, u, a, str(at), str(at), '', ''))
            added += 1
        st.execute('INSERT OR REPLACE INTO backlog_agent VALUES(?,?)', (s['id'] + ':import', host))
        done[s['id']] = added; projects.add(project)
    if write:
        from . import writecmd
        os.environ['HYPERTHYMESIA_HOST_AGENT'] = host
        for p in projects: writecmd.write_project(p)
    return done


def run(argv):
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv else None
    if '--list' in argv:
        for a in ([agent] if agent else ['claude', 'codex', 'codebuddy', 'qoder', 'dsh']):
            ss = sessions(a)
            print('== %s（%d 个会话）' % (a, len(ss)))
            for s in ss[:30]:
                turns, cwd = SOURCES[a][1](s['path'])
                print('  %s  %s  %d 轮  %s' % (s['id'], time.strftime('%Y-%m-%d %H:%M', time.localtime(s['mtime'])), len(turns), cwd or ''))
        return 0
    if agent not in SOURCES:
        print('用法：hyperthymesia import --list [--agent X] | --agent X --session ID [ID ...] | --agent X --all [--days N]'); return 2
    ss = sessions(agent)
    if '--all' in argv:
        days = float(argv[argv.index('--days') + 1]) if '--days' in argv else None
        picked = [s for s in ss if days is None or time.time() - s['mtime'] <= days * 86400]
    else:
        ids = []
        if '--session' in argv:
            for x in argv[argv.index('--session') + 1:]:
                if x.startswith('--'): break
                ids.append(x)
        picked = [s for s in ss if s['id'] in ids or any(s['id'].startswith(i) for i in ids)]
        if not picked: print('没有找到这些会话：%s（用 --list 查看会话编号）' % ' '.join(ids)); return 1
    res = import_sessions(agent, picked, write='--no-write' not in argv)
    print('已导入 %d 个会话，共 %d 轮，并已写入记忆。' % (len(res), sum(res.values())))
    return 0
