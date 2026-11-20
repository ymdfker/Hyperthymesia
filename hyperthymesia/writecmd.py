"""hyperthymesia write：把积压的已完成轮次写入记忆（通常由钩子在后台拉起，也可手动执行）。

同一项目同时只允许一个写入进程（锁文件，跨平台）；按开始时间顺序、每批约 BATCH_TOKENS 估算 token 分批写入；
写成功的轮次标记为已写，失败的保留在积压里，下次再写。"""
import json, os, re, time
from pathlib import Path

from . import changes, paths, writer
from .hooks import est_tokens
from .store import Store, state, tx

BATCH_TOKENS = int(os.environ.get('HYPERTHYMESIA_BATCH_TOKENS', '16000'))
EXPLICIT = re.compile(r'记住|记一下|记一条|记下|别忘|remember|keep in mind|note that', re.I)   # 用户明确要求记住
def _pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return ctypes.get_last_error() != 87  # access denied is not proof of death
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)): return True
            return code.value == 259
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


class Lock:
    """Native OS lock: process death releases ownership, regardless of lock-file age.
    Keep the inode/path in place so waiting writers cannot acquire different files.
    """
    def __init__(self, project, home=None, blocking=False):
        import hashlib
        d = Path(home if home is not None else paths.home()) / 'locks'; d.mkdir(parents=True, exist_ok=True)
        self.p = d / (hashlib.sha1(project.encode()).hexdigest()[:16] + '.lock')
        self.ok = False; self.handle = None; self.blocking = blocking; self.holder = None
    def __enter__(self):
        import errno
        fd = os.open(str(self.p), os.O_RDWR | os.O_CREAT, 0o600)
        self.handle = os.fdopen(fd, 'r+b')
        try:
            legacy = self.handle.read().decode('ascii', errors='ignore').strip()
            if legacy.isdigit() and int(legacy) > 0 and _pid_alive(int(legacy)):
                self.handle.close(); self.handle = None; self.holder = int(legacy); return self
            if not self.p.stat().st_size: self.handle.write(b' '); self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except OSError as exc:
            self.handle.close(); self.handle = None
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                self.holder = self._holder(); return self
            raise
        self.ok = True
        self.handle.seek(0); self.handle.truncate()
        self.handle.write(json.dumps({'pid': os.getpid(), 'acquired_at': time.time()}).encode())
        self.handle.flush()
        return self
    def _holder(self):
        # 只用于报错说明：读出持锁进程号；Windows 下被锁字节可能读不到，读不到就不显示。
        try: return json.loads(self.p.read_text(encoding='ascii', errors='ignore') or '{}').get('pid')
        except (OSError, ValueError, AttributeError): return None
    def __exit__(self, *args):
        if self.handle: self.handle.close(); self.handle = None
        self.ok = False


def _log(rec):
    d = paths.home() / 'logs'; d.mkdir(exist_ok=True)
    with open(d / 'writer.log', 'a', encoding='utf-8') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def write_project(project):
    """写入某个项目（空串表示没有项目，只有个人库）的全部积压；返回写入的轮次数，被锁时返回 None。
    写入期间新完成的轮次（其他会话结束时拉起的写入进程因锁而退出）在本进程写完一批后接着写，不留到下次；失败过的不在本次重试。"""
    with Lock(project) as lk:
        if not lk.ok:
            write_project.holder = lk.holder; return None
        st = state(paths.home()); total = 0; tried = set(); failures = []
        while True:
            rows = [dict(r) for r in st.execute('SELECT * FROM backlog WHERE project=? AND written=0 AND completed_at IS NOT NULL ORDER BY started_at, session, turn', (project,))]
            rows = [r for r in rows if (r['session'], r['turn']) not in tried]
            if not rows:
                if failures: raise RuntimeError('部分写入失败，原材料仍在积压；请查看logs/writer.log。' + failures[-1])
                return total
            tried |= {(r['session'], r['turn']) for r in rows}
            # 失败批次沿用原分组，不能因为新增积压或阈值变化丢失续接位置。
            remaining = {(r['session'], r['turn']): r for r in rows}
            for checkpoint in st.execute('SELECT payload FROM writer_progress WHERE project=? ORDER BY updated_at', (project,)).fetchall():
                keys = [tuple(k) for k in json.loads(checkpoint[0]).get('turn_keys', [])]
                if keys and all(k in remaining for k in keys):
                    total += _write_rows(project, st, [remaining.pop(k) for k in keys], failures, fixed_batch=True)
            rows = [r for r in rows if (r['session'], r['turn']) in remaining]
            total += _write_rows(project, st, rows, failures)


def _write_rows(project, st, rows, failures=None, fixed_batch=False):
    if not rows: return 0
    if failures is None: failures = []
    stores = {'u': Store(paths.personal_db(), 'u'), 'p': Store(paths.project_db(project)[0], 'p') if project else None}
    done = 0; batch = []; size = 0
    def flush(batch, retrying=False):
        turns = [{'session': r['session'], 'turn': r['turn'], 'user': r['user_text'] or '', 'assistant': r['assistant_text'] or '',
                  'changes': changes.change_block(r['diff'] or '', r['numstat'] or ''), 'at': r['started_at']} for r in batch]
        t0 = time.time()
        before = {r[0]: len(json.loads(r[1]).get('attempts', [])) for r in st.execute('SELECT batch,payload FROM writer_progress WHERE project=?', (project,))}
        try:
            res = writer.write_batch(paths.home(), stores, turns, st, project)
        except Exception as exc:
            message = str(exc)[:300]
            pending = []; usage = {}; calls = 0; replies = []
            keys = {(r['session'], r['turn']) for r in batch}
            for row in st.execute('SELECT batch,payload FROM writer_progress WHERE project=?', (project,)):
                data = json.loads(row[1])
                if {tuple(k) for k in data.get('turn_keys', [])} != keys: continue
                pending.append({'batch': row[0], 'completed_stages': data.get('done', [])})
                attempts = data.get('attempts', [])[before.get(row[0], 0):]; calls += len(attempts)
                for attempt in attempts:
                    replies.append(attempt.get('reply', ''))
                    for k, v in attempt['usage'].items():
                        if isinstance(v, (int, float)): usage[k] = usage.get(k, 0) + v
            _log({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'project': project, 'turns': len(batch), 'status': 'failed',
                  'error': message, 'pending': pending, 'calls': calls, 'usage': usage, 'answers': replies, 'secs': round(time.time() - t0, 1)})
            if failures is not None: failures.append(message)
            return 0
        # 程序兜底（便宜模型偶发漏写，兼容实测 28.14）：用户明确要求记住的轮次，这一批却没写出任何新记忆 → 逐轮单独重写一次
        if not res['new_facts'] and not retrying:
            errors_before = len(failures)
            for r in [r for r in batch if EXPLICIT.search(r['user_text'] or '')]: flush([r], True)
            if len(failures) != errors_before: return 0
        with tx(st):
            st.executemany('UPDATE backlog SET written=1 WHERE session=? AND turn=?', [(r['session'], r['turn']) for r in batch])
        _log({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'project': project, 'turns': len(batch), 'calls': res['calls'], 'usage': res['usage'],
              'new_facts': res['new_facts'], 'secs': round(time.time() - t0, 1), 'steps': [x.get('step') for x in res['log']],
              'batch': res.get('batch'), 'answers': [a.get('reply', '') for a in res.get('attempts', [])] or res.get('answers', [])})
        if res.get('batch'):
            st.execute('DELETE FROM writer_progress WHERE batch=?', (res['batch'],))
        return len(batch)
    if fixed_batch: return flush(rows)
    for r in rows:
        n = est_tokens((r['user_text'] or '') + (r['assistant_text'] or '')) + est_tokens(changes.change_block(r['diff'] or '', r['numstat'] or ''))
        if batch and size + n > BATCH_TOKENS: done += flush(batch); batch = []; size = 0
        batch.append(r); size += n
    if batch: done += flush(batch)
    return done


def run(argv):
    """hyperthymesia write [--project 目录] [--agent 宿主]；不带参数时写入全部有积压的项目。
    --agent 指明宿主，写入用该宿主自己的便宜模型；不给时按积压记录里登记的宿主。"""
    if '--project' in argv:
        projects = [argv[argv.index('--project') + 1]]
    else:
        projects = [r[0] for r in state(paths.home()).execute('SELECT DISTINCT project FROM backlog WHERE written=0 AND completed_at IS NOT NULL')]
    agent = argv[argv.index('--agent') + 1] if '--agent' in argv else ''
    if not agent:
        r = state(paths.home()).execute("SELECT a.agent FROM backlog b JOIN backlog_agent a ON a.session=b.session WHERE b.written=0 ORDER BY b.started_at DESC LIMIT 1").fetchone()
        agent = r[0] if r else ''
    if agent: os.environ['HYPERTHYMESIA_HOST_AGENT'] = agent
    failed = False
    from .execution import is_writer_workdir
    for p in projects:
        if p and is_writer_workdir(p):
            # 旧版本自我循环抓回的写入器会话，不是用户对话；不写入、不删除，留给用户自行清理。
            print('%s：写入器自身工作目录的积压（旧版本自我循环产物），跳过，不写入记忆。' % p); continue
        write_project.holder = None
        try: n = write_project(p)
        except Exception as exc:
            print('%s：写入失败，材料保留。%s' % (p or '（个人）', exc)); failed = True; continue
        if n is None:
            who = write_project.holder
            msg = '批次被另一个写入进程占用%s，本次跳过；若该进程已卡住（例如升级前的旧版本），结束它后重试。' % ('（pid=%s）' % who if who else '')
        else:
            msg = '写入 %d 轮' % n
            if n == 0:
                st = state(paths.home())
                open_rows = st.execute('SELECT COUNT(*) FROM backlog WHERE project=? AND written=0 AND completed_at IS NULL', (p,)).fetchone()[0]
                if open_rows: msg += '（另有%d轮尚未完成，会话结束后才会写入）' % open_rows
        print('%s：%s' % (p or '（个人）', msg))
    return 1 if failed else 0
