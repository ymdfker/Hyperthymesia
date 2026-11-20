"""钩子入口与宿主适配（设计 25.5、27.2）。各家 agent 的钩子把一段 JSON 写到标准输入，这里统一处理：

  prompt-submit  轮次开始：开始本轮改动快照；登记用户原话；输出本轮要注入的记忆。
  stop           轮次结束：结束改动快照；从会话记录里取助手最终回复；积压达到阈值时在后台启动写入。
  pre-compact    宿主即将压缩上下文：强制写入全部积压；清空本会话的注入记录（压缩后重新注入全文）。
  session-start  会话开始：补写之前没写完的积压；若是压缩后的重开，清空本会话的注入记录。
  session-end    会话结束：写入剩余积压。

钩子绝不能打断宿主的这一轮：任何异常只写日志，输出空结果。
宿主差异（字段名、会话记录格式、输出格式）由 ADAPTERS 处理。"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

from . import changes, paths, reader
from .store import state, tx
from .execution import internal_env, is_internal, is_writer_workdir

ALWAYS_FULL = {'trae'}   # 钩子不给会话记录路径的宿主：无法检查注入是否还在上文
THRESHOLD = int(os.environ.get('HYPERTHYMESIA_BACKLOG_TOKENS', '16000'))   # 积压估算 token 达到此值触发写入（设计 25.5）


# ---------------------------------------------------------------- 会话记录：取助手本轮最终回复
def _claude_final(transcript):
    """Claude Code 会话记录（JSONL）：最后一条真实用户消息之后，助手所有文字块拼起来。"""
    rows = []
    for l in Path(transcript).read_text(encoding='utf-8-sig', errors='replace').splitlines():
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
    for l in Path(transcript).read_text(encoding='utf-8-sig', errors='replace').splitlines():
        try: e = json.loads(l)
        except ValueError: continue
        p = e.get('payload') or {}
        if e.get('type') == 'event_msg' and p.get('type') == 'task_complete' and p.get('last_agent_message'): last = p['last_agent_message']
        if e.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'assistant':
            msg = '\n'.join(c.get('text', '') for c in p.get('content') or [] if isinstance(c, dict))
    return last or msg


def _codebuddy_final(transcript):
    """CodeBuddy（WorkBuddy 内置）会话记录：type=message、role=assistant 的 output_text；Stop 输入里通常已带 last_assistant_message。"""
    last = ''
    for l in Path(transcript).read_text(encoding='utf-8-sig', errors='replace').splitlines():
        try: e = json.loads(l)
        except ValueError: continue
        if e.get('type') == 'message' and e.get('role') == 'assistant':
            t = '\n'.join(c.get('text', '') for c in e.get('content') or [] if isinstance(c, dict) and c.get('type') == 'output_text')
            if t.strip(): last = t
    return last


_UNZSTD_JS = r"""const z=require('zlib'),fs=require('fs');const b=fs.readFileSync(process.argv[1]);const M=Buffer.from([0x28,0xb5,0x2f,0xfd]);
const p=[];let i=b.indexOf(M);while(i>=0){p.push(i);i=b.indexOf(M,i+1)}p.push(b.length);const o=[];
for(let k=0;k<p.length-1;k++){try{o.push(z.zstdDecompressSync(b.subarray(p[k],p[k+1])))}catch(e){}}process.stdout.write(Buffer.concat(o));"""


_NODE = []


def dsh_node():
    """能解压 zstd 的 node（Node 22.15+）。dsh 可能是软链接或自写的启动脚本，系统默认 node 也可能是旧版本，
    所以依次试：dsh 旁边与其真实安装前缀里的 node、PATH 上的 node、nvm / fnm 装的各版本（新的优先），取第一个带 zstd 的。"""
    if _NODE: return _NODE[0]
    cands = []
    exe = shutil.which('dsh')
    if exe:
        real = Path(exe).resolve()
        for d in [Path(exe).parent, real.parent] + [q.parent.parent for q in real.parents if q.name == 'node_modules']:
            cands += [d / 'bin' / 'node', d / 'node', d / 'node.exe']
    if shutil.which('node'): cands.append(Path(shutil.which('node')))
    home = Path(os.environ.get('HOME') or Path.home())
    for pat in ('.nvm/versions/node/*/bin/node', 'Library/Application Support/fnm/node-versions/*/installation/bin/node',
                '.local/share/fnm/node-versions/*/installation/bin/node'):
        cands += sorted(home.glob(pat), reverse=True)
    for n in cands:
        if not n.is_file(): continue
        try:
            r = subprocess.run([str(n), '-e', "process.exit(require('zlib').zstdDecompressSync?0:1)"], capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError): continue
        if r.returncode == 0: _NODE.append(str(n)); return str(n)
    return None


def dsh_read(transcript):
    """dsh 会话记录 session.jsonl.zstd：多个 zstd 帧拼接（Node 一次只解第一帧），逐帧解压；Python 3.12 标准库没有 zstd，借 dsh 的 node。"""
    node = dsh_node()
    if not node: return ''
    r = subprocess.run([node, '-e', _UNZSTD_JS, str(transcript)], capture_output=True, timeout=60)
    return r.stdout.decode('utf-8', 'replace')


def dsh_turns(text):
    """[(时间, 用户原话, 最终回复)], 工作目录。用户原话是 source.kind=user 的 user/message；钩子注入的上下文 kind=plugin，不算。"""
    turns = []; cwd = None; cur = None
    for l in text.splitlines():
        try: e = json.loads(l)
        except ValueError: continue
        t = e.get('type'); d = e.get('data') or {}
        if t == 'session': cwd = e.get('cwd')
        elif t == 'user/message' and (d.get('source') or {}).get('kind') == 'user':
            u = '\n'.join(c.get('text', '') for c in d.get('content') or [] if isinstance(c, dict) and c.get('type') == 'text').strip()
            if u: cur = [time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(e.get('time', 0) / 1000)), u, '']; turns.append(cur)
        elif t == 'assistant/message' and cur is not None:
            a = '\n'.join(c.get('text', '') for c in (d.get('message') or {}).get('content') or [] if isinstance(c, dict) and c.get('type') == 'text').strip()
            if a: cur[2] = a                                 # 一轮里最后一段文字即最终回复
    return turns, cwd


def _dsh_final(transcript):
    turns, _ = dsh_turns(dsh_read(transcript))
    return turns[-1][2] if turns else ''


ADAPTERS = {
    # 宿主名: (取最终回复的函数, 注入输出格式)
    'claude': (_claude_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    'codebuddy': (_codebuddy_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    # Qoder 桌面 agent：会话记录格式与 Claude Code 相同，Stop 输入也直接带 last_assistant_message
    'qoder': (_claude_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    # Trae：钩子输入不带会话记录路径，Stop 直接带 last_assistant_message
    'trae': (lambda tp: '', lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    # DeepSeek Harness：官方桥接插件按 Claude Code 格式调用钩子；Stop 不带最终回复，会话记录是 zstd 压缩的
    'dsh': (_dsh_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
    'codex': (_codex_final, lambda event, ctx: {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': ctx}} if ctx else {}),
}


def est_tokens(text):
    """不下载分词器的 token 估算：中日韩字符约 1 个/token，其余约 4 字符/token。"""
    cjk = sum(1 for ch in text if '　' <= ch <= '鿿' or '＀' <= ch <= '￯')
    return int(cjk + (len(text) - cjk) / 4)


# ---------------------------------------------------------------- 事件处理
def _st(): return state(paths.home())


# 没有“压缩前”钩子的宿主（Codex、dsh）：压缩后旧的注入文字仍留在会话记录里，但已不在模型上文中。
# 只看最后一次压缩之后的部分（Codex 的 compacted 行自带保留下来的历史，所以从该行算起）。
COMPACT_MARKS = ('"type":"compacted"', '"type": "compacted"', '"type":"compaction/end"', '"type": "compaction/end"')


def after_compaction(text):
    cut = max(text.rfind(m) for m in COMPACT_MARKS)
    if cut < 0: return text
    return text[text.rfind('\n', 0, cut) + 1:]


def _snapshot(home, root):
    try: return changes.snapshot(home, root)
    except (OSError, subprocess.SubprocessError) as exc:
        _log('snapshot_failed', str(exc)[:200]); return ''


def on_prompt(d, agent):
    sid = d.get('session_id') or 'unknown'; cwd = d.get('cwd') or os.getcwd(); st = _st()
    pdb, root = paths.project_db(cwd)
    tree = _snapshot(paths.home(), root) if root else ''
    host_turn_id = str(d['turn_id']) if d.get('turn_id') is not None else None
    # Allocation and insert share a write transaction. Never replace an earlier user turn.
    with tx(st):
        old = st.execute('SELECT turn FROM backlog_capture WHERE session=? AND host_turn_id=?', (sid, host_turn_id)).fetchone() if host_turn_id else None
        if old: n = old['turn']
        else:
            n = (st.execute('SELECT MAX(turn) FROM backlog WHERE session=?', (sid,)).fetchone()[0] or 0) + 1
            st.execute('INSERT INTO backlog(session, turn, project, user_text, started_at, diff, numstat, written) VALUES(?,?,?,?,?,?,?,0)',
                       (sid, n, str(root or ''), d.get('prompt') or '', time.strftime('%Y-%m-%dT%H:%M:%S'), 'tree:' + tree, ''))
            st.execute('INSERT INTO backlog_capture VALUES(?,?,?,?,?)', (sid, n, d.get('transcript_path'), agent, host_turn_id))
        st.execute('INSERT OR REPLACE INTO backlog_agent VALUES(?,?)', (sid, agent))
    # 有的宿主（如 CodeBuddy）不把钩子注入的内容存进会话记录，续接会话后之前注入的记忆就不在上文了：
    # 会话记录里找不到我们注入过的标记时，按“上文没有记忆”处理，重新注入全文
    tp = d.get('transcript_path')
    if tp and Path(tp).exists():
        try:
            text = dsh_read(tp) if agent == 'dsh' else Path(tp).read_text(encoding='utf-8-sig', errors='replace')
            if '长期记忆' not in after_compaction(text): reader.reset_session(st, sid)
        except (OSError, subprocess.SubprocessError): pass
    elif agent in ALWAYS_FULL:
        reader.reset_session(st, sid)   # 无法确认上文是否还留着之前注入的记忆：每轮注入全文
    from .mcp_server import open_stores
    ctx = reader.context(open_stores(cwd), st, sid)
    if os.environ.get('HYPERTHYMESIA_TRACE'):   # 兼容测试用：记录每轮注入了多少（不记内容）
        with open(os.environ['HYPERTHYMESIA_TRACE'], 'a', encoding='utf-8') as f:
            f.write(json.dumps({'session': sid, 'turn': n, 'agent': agent, 'chars': len(ctx or ''), 'full': '长期记忆全文' in (ctx or ''),
                                'keys': sorted(d), 'tp': d.get('transcript_path')}) + '\n')
    return ADAPTERS[agent][1]('prompt-submit', ctx)


def on_stop(d, agent):
    sid = d.get('session_id') or 'unknown'; st = _st()
    if d.get('turn_id') is not None:
        r = st.execute('SELECT b.* FROM backlog b JOIN backlog_capture c ON c.session=b.session AND c.turn=b.turn WHERE b.session=? AND c.host_turn_id=?', (sid, str(d['turn_id']))).fetchone()
    else:
        r = st.execute('SELECT * FROM backlog WHERE session=? ORDER BY turn DESC LIMIT 1', (sid,)).fetchone()
    if not r or r['completed_at']: return {}          # 同一轮的重复 Stop，或没有登记开始
    diff = numstat = ''
    if r['project'] and (r['diff'] or '').startswith('tree:') and r['diff'][5:]:
        end = _snapshot(paths.home(), r['project'])
        if end:
            try: diff, numstat = changes.diff(paths.home(), r['project'], r['diff'][5:], end)
            except (OSError, subprocess.SubprocessError) as exc: _log('snapshot_diff_failed', str(exc)[:200])
    final = d.get('last_assistant_message') or ''   # 宿主直接给了最终回复（CodeBuddy 等）就不必解析会话记录
    tp = d.get('transcript_path')
    if not final and tp and Path(tp).exists():
        try: final = ADAPTERS[agent][0](tp)
        except Exception as exc: _log('final_reply_failed', str(exc))
    st.execute('UPDATE backlog SET assistant_text=?, completed_at=?, diff=?, numstat=? WHERE session=? AND turn=?',
               (final, time.strftime('%Y-%m-%dT%H:%M:%S'), diff, numstat, sid, r['turn']))
    if backlog_tokens(st, r['project']) >= THRESHOLD: spawn_writer(r['project'], agent)
    return {}


def on_pre_compact(d, agent):
    sid = d.get('session_id') or 'unknown'; st = _st()
    reader.reset_session(st, sid)
    pdb, root = paths.project_db(d.get('cwd') or os.getcwd())
    spawn_writer(str(root or ''), agent)
    return {}


def on_session_start(d, agent):
    _log('lifecycle', json.dumps({'event': 'session-start', 'agent': agent, 'session': d.get('session_id')}, ensure_ascii=False))
    st = _st()
    if d.get('source') in ('compact', 'clear'): reader.reset_session(st, d.get('session_id'))
    from .capture import recover_pending
    recover_pending(st, d, agent, _log)
    # 补写上次没整理的积压（Codex、dsh 没有会话结束钩子，靠这里兜底）；用那段对话所属 agent 的模型，不用当前 agent 的
    rows = st.execute('SELECT b.project, a.agent FROM backlog b LEFT JOIN backlog_agent a ON a.session=b.session '
                      'WHERE b.written=0 AND b.completed_at IS NOT NULL ORDER BY b.completed_at').fetchall()
    host = {}
    for p, a in rows: host[p] = a or agent                    # 同一项目取最近一轮所属的 agent
    for p, a in host.items(): spawn_writer(p, a)
    return {}


def on_session_end(d, agent):
    _log('lifecycle', json.dumps({'event': 'session-end', 'agent': agent, 'session': d.get('session_id')}, ensure_ascii=False))
    pdb, root = paths.project_db(d.get('cwd') or os.getcwd())
    spawn_writer(str(root or ''), agent)
    return {}


EVENTS = {'prompt-submit': on_prompt, 'stop': on_stop, 'pre-compact': on_pre_compact, 'session-start': on_session_start, 'session-end': on_session_end}


def backlog_tokens(st, project):
    tot = 0
    for r in st.execute('SELECT user_text, assistant_text, diff, numstat FROM backlog WHERE project=? AND written=0 AND completed_at IS NOT NULL', (project,)):
        tot += est_tokens(r['user_text'] or '') + est_tokens(r['assistant_text'] or '') + est_tokens(changes.change_block(r['diff'] or '', r['numstat'] or ''))
    return tot


def self_cmd():
    """调用自身的命令行：打包后是可执行文件本身，源码运行时是 python -m hyperthymesia。"""
    if os.environ.get('HYPERTHYMESIA_SELF'): return [os.environ['HYPERTHYMESIA_SELF']]   # 源码调试：指定一个包装脚本
    return [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'hyperthymesia']


def spawn_writer(project, agent=''):
    """在后台启动写入，立即返回，不让宿主等待；写入用宿主 agent 自己的便宜模型。"""
    kw = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt': kw['creationflags'] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else: kw['start_new_session'] = True
    env = internal_env(); env.pop('CLAUDECODE', None)
    # 打包版：钩子进程很快退出并删除自己的 _MEI 解包目录；子进程若继承该目录会缺 _socket/base_library.zip。
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    try:
        child = subprocess.Popen(self_cmd() + ['write', '--project', project] + (['--agent', agent] if agent else []), env=env, **kw)
    except OSError as exc:
        _log('writer_start_failed', json.dumps({'project': project, 'agent': agent, 'error': str(exc)}, ensure_ascii=False))
        raise
    _log('writer_started', json.dumps({'project': project, 'agent': agent, 'pid': child.pid if isinstance(child.pid, int) else None}, ensure_ascii=False))


def _log(kind, msg):
    try:
        d = paths.home() / 'logs'; d.mkdir(exist_ok=True)
        with open(d / 'hooks.log', 'a', encoding='utf-8') as f: f.write('%s %s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S'), kind, msg))
    except OSError: pass


def dsh_header_is_sub(text):
    """dsh 会话记录首行 session 头：子 agent 会话带 parentSession / origin=subagent / delegationDepth>0。"""
    try: h = json.loads(text.split('\n', 1)[0] or '{}')
    except ValueError: return False
    return bool(h.get('parentSession')) or h.get('origin') == 'subagent' or (h.get('delegationDepth') or 0) > 0


def is_subagent(d, agent):
    """子 agent 的任务不是用户原话，钩子跳过（兼容实测 S8）。
    Codex：子 agent 与父会话共用 session_id，钩子输入也没有区分字段；只有它自己的会话记录首行 session_meta 带 parent_thread_id。
    dsh：子 agent 有自己的会话，其会话记录首行带 parentSession / delegationDepth>0。"""
    tp = d.get('transcript_path')
    if not tp or not Path(tp).exists(): return False
    if agent == 'codex':
        try:
            with open(tp, encoding='utf-8', errors='replace') as f: m = (json.loads(f.readline()).get('payload') or {})
        except (OSError, ValueError): return False
        return bool(m.get('parent_thread_id')) or m.get('thread_source') == 'subagent'
    if agent == 'dsh':
        try: return dsh_header_is_sub(dsh_read(tp))
        except (OSError, subprocess.SubprocessError): return False
    return False


def run(argv):
    """hyperthymesia hook <事件> [--agent claude|codex]"""
    # 在读取会话、打开数据库和触发补写之前，排除内部任务的全部生命周期事件。
    if is_internal():
        sys.stdout.write('{}'); sys.stdout.flush()
        return 0
    event = argv[0] if argv else ''
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv else 'claude'
    out = {}
    try:
        d = json.loads(sys.stdin.read().lstrip('\ufeff').strip() or '{}')
        if is_writer_workdir(d.get('cwd') if isinstance(d, dict) else None):
            pass   # 写入器自身会话：不抓取、不注入、不触发补写
        elif not (event in ('prompt-submit', 'stop') and is_subagent(d, agent)):
            out = EVENTS[event](d, agent) or {}
    except Exception as exc:   # 钩子绝不能打断宿主
        _log('hook_error', '%s %s: %s' % (agent, event, exc))
    sys.stdout.write(json.dumps(out, ensure_ascii=False)); sys.stdout.flush()
    return 0
