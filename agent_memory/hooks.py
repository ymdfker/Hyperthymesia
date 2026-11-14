"""钩子入口与宿主适配（设计 25.5、27.2）。各家 agent 的钩子把一段 JSON 写到标准输入，这里统一处理：

  prompt-submit  轮次开始：开始本轮改动快照；登记用户原话；输出本轮要注入的记忆。
  stop           轮次结束：结束改动快照；从会话记录里取助手最终回复；积压达到阈值时在后台启动写入。
  pre-compact    宿主即将压缩上下文：强制写入全部积压；清空本会话的注入记录（压缩后重新注入全文）。
  session-start  会话开始：补写之前没写完的积压；若是压缩后的重开，清空本会话的注入记录。
  session-end    会话结束：写入剩余积压。

钩子绝不能打断宿主的这一轮：任何异常只写日志，输出空结果。
宿主差异（字段名、会话记录格式、输出格式）由 ADAPTERS 处理。"""
import json, os, subprocess, sys, time
from pathlib import Path

from . import changes, paths, reader
from .store import state

THRESHOLD = int(os.environ.get('AGENT_MEMORY_BACKLOG_TOKENS', '16000'))   # 积压估算 token 达到此值触发写入（设计 25.5）


# ---------------------------------------------------------------- 会话记录：取助手本轮最终回复
def _claude_final(transcript):
    """Claude Code 会话记录（JSONL）：最后一条真实用户消息之后，助手所有文字块拼起来。"""
    rows = []
    for l in Path(transcript).read_text(encoding='utf-8', errors='replace').splitlines():
        try: rows.append(json.loads(l))
        except ValueError: pass
    start = 0
    for i, e in enumerate(rows):
        if e.get('type') == 'user':
            c = (e.get('message') or {}).get('content')
            if isinstance(c, str) or (isinstance(c, list) and any(x.get('type') == 'text' for x in c if isinstance(x, dict))): start = i
    out = []
    for e in rows[start + 1:]:
        if e.get('type') == 'assistant':
            for x in (e.get('message') or {}).get('content') or []:
                if isinstance(x, dict) and x.get('type') == 'text' and x.get('text', '').strip(): out.append(x['text'])
    return out[-1] if out else ''


def _codex_final(transcript):
    """Codex 会话记录：最后一个 task_complete 事件里的 last_agent_message；没有时取最后一条助手消息。"""
    last = ''; msg = ''
    for l in Path(transcript).read_text(encoding='utf-8', errors='replace').splitlines():
        try: e = json.loads(l)
        except ValueError: continue
        p = e.get('payload') or {}
        if e.get('type') == 'event_msg' and p.get('type') == 'task_complete' and p.get('last_agent_message'): last = p['last_agent_message']
        if e.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'assistant':
            msg = '\n'.join(c.get('text', '') for c in p.get('content') or [] if isinstance(c, dict))
    return last or msg


ADAPTERS = {
    # 宿主名: (取最终回复的函数, 注入输出格式)
    'claude': (_claude_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    'codex': (_codex_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
}


def est_tokens(text):
    """不下载分词器的 token 估算：中日韩字符约 1 个/token，其余约 4 字符/token。"""
    cjk = sum(1 for ch in text if '　' <= ch <= '鿿' or '＀' <= ch <= '￯')
    return int(cjk + (len(text) - cjk) / 4)


# ---------------------------------------------------------------- 事件处理
def _st(): return state(paths.home())


def on_prompt(d, agent):
    sid = d.get('session_id') or 'unknown'; cwd = d.get('cwd') or os.getcwd(); st = _st()
    pdb, root = paths.project_db(cwd)
    n = (st.execute('SELECT MAX(turn) FROM backlog WHERE session=?', (sid,)).fetchone()[0] or 0) + 1
    tree = changes.snapshot(paths.home(), root) if root else ''
    st.execute('INSERT OR REPLACE INTO backlog(session, turn, project, user_text, started_at, diff, numstat, written) VALUES(?,?,?,?,?,?,?,0)',
               (sid, n, str(root or ''), d.get('prompt') or '', time.strftime('%Y-%m-%dT%H:%M:%S'), 'tree:' + tree, ''))
    from .mcp_server import open_stores
    return ADAPTERS[agent][1]('prompt-submit', reader.context(open_stores(cwd), st, sid))


def on_stop(d, agent):
    sid = d.get('session_id') or 'unknown'; st = _st()
    r = st.execute('SELECT * FROM backlog WHERE session=? ORDER BY turn DESC LIMIT 1', (sid,)).fetchone()
    if not r or r['completed_at']: return {}          # 同一轮的重复 Stop，或没有登记开始
    diff = numstat = ''
    if r['project'] and (r['diff'] or '').startswith('tree:') and r['diff'][5:]:
        end = changes.snapshot(paths.home(), r['project']); diff, numstat = changes.diff(paths.home(), r['project'], r['diff'][5:], end)
    final = ''
    tp = d.get('transcript_path')
    if tp and Path(tp).exists():
        try: final = ADAPTERS[agent][0](tp)
        except Exception as exc: _log('final_reply_failed', str(exc))
    final = final or d.get('last_assistant_message') or ''
    st.execute('UPDATE backlog SET assistant_text=?, completed_at=?, diff=?, numstat=? WHERE session=? AND turn=?',
               (final, time.strftime('%Y-%m-%dT%H:%M:%S'), diff, numstat, sid, r['turn']))
    if backlog_tokens(st, r['project']) >= THRESHOLD: spawn_writer(r['project'])
    return {}


def on_pre_compact(d, agent):
    sid = d.get('session_id') or 'unknown'; st = _st()
    reader.reset_session(st, sid)
    pdb, root = paths.project_db(d.get('cwd') or os.getcwd())
    spawn_writer(str(root or ''))
    return {}


def on_session_start(d, agent):
    st = _st()
    if d.get('source') in ('compact', 'clear'): reader.reset_session(st, d.get('session_id'))
    projects = [r[0] for r in st.execute('SELECT DISTINCT project FROM backlog WHERE written=0 AND completed_at IS NOT NULL')]
    for p in projects: spawn_writer(p)
    return {}


def on_session_end(d, agent):
    pdb, root = paths.project_db(d.get('cwd') or os.getcwd())
    spawn_writer(str(root or ''))
    return {}


EVENTS = {'prompt-submit': on_prompt, 'stop': on_stop, 'pre-compact': on_pre_compact, 'session-start': on_session_start, 'session-end': on_session_end}


def backlog_tokens(st, project):
    tot = 0
    for r in st.execute('SELECT user_text, assistant_text, diff, numstat FROM backlog WHERE project=? AND written=0 AND completed_at IS NOT NULL', (project,)):
        tot += est_tokens(r['user_text'] or '') + est_tokens(r['assistant_text'] or '') + est_tokens(changes.change_block(r['diff'] or '', r['numstat'] or ''))
    return tot


def self_cmd():
    """调用自身的命令行：打包后是可执行文件本身，源码运行时是 python -m agent_memory。"""
    return [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'agent_memory']


def spawn_writer(project):
    """在后台启动写入，立即返回，不让宿主等待。"""
    kw = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt': kw['creationflags'] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else: kw['start_new_session'] = True
    env = dict(os.environ); env.pop('CLAUDECODE', None)
    subprocess.Popen(self_cmd() + ['write', '--project', project], env=env, **kw)


def _log(kind, msg):
    try:
        d = paths.home() / 'logs'; d.mkdir(exist_ok=True)
        with open(d / 'hooks.log', 'a', encoding='utf-8') as f: f.write('%s %s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S'), kind, msg))
    except OSError: pass


def run(argv):
    """agent-memory hook <事件> [--agent claude|codex]"""
    event = argv[0] if argv else ''
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv else 'claude'
    out = {}
    try:
        d = json.loads(sys.stdin.read() or '{}')
        out = EVENTS[event](d, agent) or {}
    except Exception as exc:   # 钩子绝不能打断宿主
        _log('hook_error', '%s %s: %s' % (agent, event, exc))
    sys.stdout.write(json.dumps(out, ensure_ascii=False)); sys.stdout.flush()
    return 0
