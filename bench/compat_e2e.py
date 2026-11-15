"""兼容矩阵实测（设计 28.14）：用各家命令行跑同一组场景，逐格判定。

  python3 bench/compat_e2e.py <agent> <测试目录>      agent：claude | codebuddy | qoder | dsh

全在一个临时测试项目里：install --project 只改该项目自己的配置；记忆库放在 <测试目录>/home（HYPERTHYMESIA_HOME），
不碰用户自己的记忆和配置（dsh 没有项目级配置，用一个只供测试的 profile：hytest）。
场景：S2 记录一轮、S10 代码改动、S4 续接、S5 压缩后重新注入、S6 下次启动补写积压、S1 新会话答对、S7 并发、S8 子 agent、S12 卸载复原。
结果写到 <测试目录>/result.json，同时打印。每轮都用短提示，控制额度。"""
import json, os, shutil, sqlite3, subprocess, sys, threading, time, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT, OUT = sys.argv[1], Path(sys.argv[2]).resolve()
HOME, PROJ, TRACE = OUT / 'home', OUT / 'proj', OUT / 'trace.jsonl'
WB = '/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy'
WRAP = OUT / 'hy'                      # 钩子与 MCP 调用的命令：用源码运行，便于测未发布的修复
R = {}; COST = []


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'MCP_', 'ANTHROPIC_CLAUDE_DESKTOP'))}
    e.update(HYPERTHYMESIA_HOME=str(HOME), HYPERTHYMESIA_TRACE=str(TRACE), HYPERTHYMESIA_SELF=str(WRAP),
             HYPERTHYMESIA_BACKLOG_TOKENS='1000000')   # 只靠会话开始/结束触发写入，便于测 S6
    return e


# ---------------------------------------------------------------- 各家驱动：run(提示, 会话, 续接?) -> (会话编号, 回复)
def _json_last(out):
    for l in reversed([l for l in out.splitlines() if l.strip().startswith(('{', '['))]):
        try: return json.loads(l)
        except ValueError: pass
    try: return json.loads(out)
    except ValueError: return {}


def run(prompt, sid=None, resume=False):
    if AGENT == 'claude':
        cmd = ['claude', '-p', prompt, '--model', 'claude-haiku-5-5', '--output-format', 'json', '--setting-sources', 'project,local',
               '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Edit,Write,Glob,Grep,Task,mcp__hyperthymesia__memory_read_objects']
        sid = sid or str(uuid.uuid4()); cmd += ['--resume', sid] if resume else ['--session-id', sid]
    elif AGENT == 'codebuddy':
        cmd = [WB, '-p', prompt, '--output-format', 'json', '--permission-mode', 'acceptEdits', '--strict-mcp-config', '--mcp-config',
               str(PROJ / '.mcp.json'), '--allowedTools', 'Read,Edit,Write,Glob,Grep,Task,mcp__hyperthymesia__memory_read_objects']
        sid = sid or str(uuid.uuid4()); cmd += ['--resume', sid] if resume else ['--session-id', sid]
    elif AGENT == 'qoder':
        from hyperthymesia.providers import qodercli_cmd
        cmd = qodercli_cmd() + ['-p', prompt, '-o', 'json', '--yolo'] + (['--resume', sid] if resume else [])
    elif AGENT == 'codex':
        base = ['codex', 'exec'] + (['resume', sid] if resume else []) + [prompt, '--json', '-m', 'gpt-5.6-luna',
                '-c', 'model_reasoning_effort="low"'] + ([] if resume else ['-s', 'workspace-write'])
        r = subprocess.run(base, cwd=PROJ, env=dict(env(), HTTPS_PROXY='http://127.0.0.1:7897', HTTP_PROXY='http://127.0.0.1:7897',
                           ALL_PROXY='socks5://127.0.0.1:7897'), capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        msg = ''
        for l in r.stdout.splitlines():
            try: e = json.loads(l)
            except ValueError: continue
            if e.get('type') == 'thread.started': sid = e.get('thread_id')
            it = e.get('item') or {}
            if e.get('type') == 'item.completed' and it.get('type') == 'agent_message': msg = it.get('text', '')
        if not msg: print('  !! codex 无回复：', (r.stderr or r.stdout)[-300:])
        return sid, msg.strip()
    elif AGENT == 'dsh':
        cmd = ['dsh', '--profile', 'hytest', prompt]                       # 无头模式：一次性，不支持续接
    t0 = time.time()
    r = subprocess.run(cmd, cwd=PROJ, env=env(), capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    if AGENT == 'dsh': return sid, r.stdout.strip()
    o = _json_last(r.stdout)
    if isinstance(o, list):
        COST.append(sum(((x.get('providerData') or {}).get('rawUsage') or {}).get('credit') or 0 for x in o if isinstance(x, dict)))
        o = next((x for x in reversed(o) if isinstance(x, dict) and x.get('type') == 'result'), {})
    COST.append(o.get('total_cost_usd') or o.get('total_credits') or 0)
    if not o: print('  !! 输出无法解析：', (r.stderr or r.stdout)[-300:])
    return o.get('session_id') or sid, (o.get('result') or '').strip()


PROF = Path.home() / '.dsh/profiles/hytest'


def dsh_profile(remove):
    """dsh 没有项目级配置：建一个只供测试的 profile（headless + 本框架补丁），只对它安装/卸载，不碰用户的 web profile。"""
    if not remove:
        PROF.mkdir(parents=True, exist_ok=True)
        web = Path.home() / '.dsh/profiles/web'
        pkg = json.loads((web / 'package.json').read_text()); pkg['name'] = 'dsh-profile-hytest'
        pkg['dsh']['profile']['bundles'] = ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-headless']
        (PROF / 'package.json').write_text(json.dumps(pkg, indent=2))
        for f in ('pnpm-workspace.yaml', 'cordis.yml'):
            if (web / f).exists() and not (PROF / f).exists(): shutil.copy(web / f, PROF / f)
        (PROF / 'cordis.patch.yml').write_text('[]\n')
    os.environ.update(env())
    from hyperthymesia import install
    install._dsh_profiles = lambda: [PROF]
    install.dsh(remove=remove)
    if remove: shutil.rmtree(PROF)


def db(q, *a):
    p = HOME / 'state.db'
    if not p.exists(): return []
    c = sqlite3.connect(p); c.row_factory = sqlite3.Row
    try: return [dict(x) for x in c.execute(q, a)]
    finally: c.close()


def trace(): return [json.loads(l) for l in TRACE.read_text().splitlines()] if TRACE.exists() else []


def mark(k, ok, note=''):
    R[k] = {'ok': bool(ok), 'note': note}; print(('  ✓ ' if ok else '  ✗ ') + k, note)


def wait_written(current, timeout=600):
    """之前会话的积压都已写入（当前会话自己这一轮要等下次才写，不算）。"""
    t = time.time()
    while time.time() - t < timeout:
        if not db('SELECT 1 FROM backlog WHERE written=0 AND completed_at IS NOT NULL AND session<>?', current) and db('SELECT 1 FROM backlog WHERE written=1'): return True
        time.sleep(5)
    return False


def main():
    # Codex 的新钩子必须由用户在 Codex 里 /hooks 批准：第一次只建项目并安装，等用户批准后带 --approved 再跑
    if AGENT == 'codex' and '--approved' in sys.argv:
        before = set(json.loads((OUT / 'before.json').read_text()))
    else:
        if OUT.exists(): shutil.rmtree(OUT)
        PROJ.mkdir(parents=True); subprocess.run(['git', 'init', '-q', str(PROJ)], check=True)
        WRAP.write_text('#!/bin/sh\nPYTHONPATH=%s exec %s -m hyperthymesia "$@"\n' % (REPO, sys.executable)); WRAP.chmod(0o755)
        before = {p.name for p in PROJ.rglob('*') if '.git' not in p.parts}
        (OUT / 'before.json').write_text(json.dumps(sorted(before)))
    inst = AGENT
    if AGENT == 'dsh': dsh_profile(False)
    elif not (AGENT == 'codex' and '--approved' in sys.argv): subprocess.run([str(WRAP), 'install', inst, '--project', str(PROJ)], env=env(), check=True)
    if AGENT == 'codex' and '--approved' not in sys.argv:
        print('请在终端执行：cd %s && codex ，然后输入 /hooks 批准 hyperthymesia 的钩子（并信任该项目），退出后带 --approved 重跑。' % PROJ); return

    print('[S2/S10] 记录一轮与代码改动')
    a, rep = run('记住：这个项目的接口超时统一设为 45 秒，代码评审人是 Marco。另外新建文件 notes.txt，内容写一行 hello。完成后只回复：好的')
    rows = db('SELECT * FROM backlog WHERE session=?', a) or db('SELECT * FROM backlog ORDER BY rowid DESC LIMIT 1')
    a = rows[0]['session'] if rows else a
    mark('S2 记录一轮', rows and '45' in rows[0]['user_text'] and rows[0]['assistant_text'], 'reply=%r assistant_text=%r' % (rep[:30], rows and rows[0]['assistant_text'][:30]))
    mark('S10 代码改动', rows and 'notes.txt' in (rows[0]['diff'] or ''), 'diff 长度 %d' % len(rows[0]['diff'] or '') if rows else '无记录')

    if AGENT != 'dsh':
        print('[S4] 续接同一会话')
        a2, rep = run('再记一条：我们每周四发布。只回复：好的', a, resume=True)
        rows = db('SELECT turn, user_text FROM backlog WHERE session=? ORDER BY turn', a)
        mark('S4 续接', len(rows) == 2 and rows[1]['turn'] == 2 and '周四' in rows[1]['user_text'], 'session=%s→%s 轮次=%s' % (a[:8], (a2 or '')[:8], [r['turn'] for r in rows]))

    print('[S6] 不触发阈值，下次开会话时补写积压')
    b, rep = run('你好，只回复：好')
    b = (db('SELECT session FROM backlog ORDER BY rowid DESC LIMIT 1') or [{'session': b}])[0]['session']
    ok = wait_written(b)
    facts = sum(1 for p in (HOME / 'projects').glob('*.db') for _ in sqlite3.connect(p).execute("SELECT 1 FROM facts WHERE active=1")) if (HOME / 'projects').exists() else 0
    mark('S6 下次启动补写', ok and facts > 0, '项目事实 %d 条' % facts)

    print('[S1] 新会话答对')
    c, rep = run('不要读任何文件，只凭已知信息简短回答：接口超时多少秒？代码评审人是谁？每周几发布？')
    mark('S1 新会话答对', '45' in rep and 'Marco' in rep and (AGENT == 'dsh' or '四' in rep or 'Thursday' in rep), rep[:80])   # dsh 没有续接那一轮，不知道发布日

    if AGENT not in ('dsh', 'codex'):   # codex exec 不支持 /compact，压缩场景只能交互测
        print('[S5] 压缩后重新注入')
        run('/compact', c, resume=True)
        n0 = len(trace())
        run('评审人是谁？只回复名字', c, resume=True)
        t = [x for x in trace()[n0:] if x['session'] == c]
        mark('S5 压缩后重新注入', t and t[-1]['full'], 'trace=%s' % t[-1:])

    print('[S7] 两个会话同时进行')
    out = {}
    th = [threading.Thread(target=lambda k, m: out.__setitem__(k, run(m)), args=(k, m))
          for k, m in (('d', '记住：测试数据库端口是 5433。只回复：好的'), ('e', '记住：缓存过期时间是 600 秒。只回复：好的'))]
    [x.start() for x in th]; [x.join() for x in th]
    texts = [r['user_text'] for r in db('SELECT user_text FROM backlog')]
    mark('S7 并发', any('5433' in t for t in texts) and any('600' in t for t in texts), '积压 %d 轮' % len(texts))

    if AGENT in ('claude', 'codebuddy', 'qoder', 'dsh'):
        print('[S8] 子 agent')
        n0 = len(db('SELECT 1 FROM backlog'))
        s8, rep = run('请务必使用子 agent（Task 工具）去读取 notes.txt 的内容，然后把内容告诉我。')
        new = db('SELECT user_text FROM backlog ORDER BY rowid DESC LIMIT ?', len(db('SELECT 1 FROM backlog')) - n0)
        mark('S8 子 agent 不混入', len(new) == 1 and '子 agent' in new[0]['user_text'], '新增 %d 轮：%s' % (len(new), [x['user_text'][:20] for x in new]))

    print('[S12] 卸载复原')
    if AGENT == 'dsh': dsh_profile(True); PROF.joinpath('cordis.patch.yml').exists() and print('  hytest 补丁：', PROF.joinpath('cordis.patch.yml').read_text().strip()[-40:])
    else: subprocess.run([str(WRAP), 'uninstall', inst, '--project', str(PROJ)], env=env(), check=True)
    left = {p.name for p in PROJ.rglob('*') if '.git' not in p.parts and not p.name.endswith('.bak')} - before - {'notes.txt'}
    leftover = [n for n in left if (PROJ / n).is_file() and 'hyperthymesia' in (PROJ / n).read_text(errors='ignore')] if left else []
    mark('S12 卸载复原', not leftover, '残留 %s' % leftover)

    R['_cost'] = sum(COST); (OUT / 'result.json').write_text(json.dumps(R, ensure_ascii=False, indent=1))
    print('额度消耗（宿主报告）：', R['_cost'])


if __name__ == '__main__':
    sys.path.insert(0, str(REPO)); main()
