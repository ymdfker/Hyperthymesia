"""hyperthymesia write：把积压的已完成轮次写入记忆（通常由钩子在后台拉起，也可手动执行）。

同一项目同时只允许一个写入进程（锁文件，跨平台）；按开始时间顺序、每批约 BATCH_TOKENS 估算 token 分批写入；
写成功的轮次标记为已写，失败的保留在积压里，下次再写。"""
import json, os, re, time
from pathlib import Path

from . import changes, paths, writer
from .hooks import est_tokens
from .store import Store, state

BATCH_TOKENS = int(os.environ.get('HYPERTHYMESIA_BATCH_TOKENS', '16000'))
EXPLICIT = re.compile(r'记住|记一下|记一条|记下|别忘|remember|keep in mind|note that', re.I)   # 用户明确要求记住
LOCK_STALE = 1800   # 锁超过 30 分钟视为上次写入进程已异常退出


class Lock:
    def __init__(self, project):
        import hashlib
        d = paths.home() / 'locks'; d.mkdir(exist_ok=True)
        self.p = d / (hashlib.sha1(project.encode()).hexdigest()[:16] + '.lock'); self.ok = False
    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(str(self.p), os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.write(fd, str(os.getpid()).encode()); os.close(fd)
                self.ok = True; return self
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > LOCK_STALE: self.p.unlink(); continue
                except OSError: pass
                return self
        return self
    def __exit__(self, *a):
        if self.ok:
            try: self.p.unlink()
            except OSError: pass


def _log(rec):
    d = paths.home() / 'logs'; d.mkdir(exist_ok=True)
    with open(d / 'writer.log', 'a', encoding='utf-8') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def write_project(project):
    """写入某个项目（空串表示没有项目，只有个人库）的全部积压；返回写入的轮次数，被锁时返回 None。
    写入期间新完成的轮次（其他会话结束时拉起的写入进程因锁而退出）在本进程写完一批后接着写，不留到下次；失败过的不在本次重试。"""
    with Lock(project) as lk:
        if not lk.ok: return None
        st = state(paths.home()); total = 0; tried = set()
        while True:
            rows = [dict(r) for r in st.execute('SELECT * FROM backlog WHERE project=? AND written=0 AND completed_at IS NOT NULL ORDER BY started_at, session, turn', (project,))]
            rows = [r for r in rows if (r['session'], r['turn']) not in tried]
            if not rows: return total
            tried |= {(r['session'], r['turn']) for r in rows}
            total += _write_rows(project, st, rows)


def _write_rows(project, st, rows):
    if not rows: return 0
    stores = {'u': Store(paths.personal_db(), 'u'), 'p': Store(paths.project_db(project)[0], 'p') if project else None}
    done = 0; batch = []; size = 0
    def flush(batch, retrying=False):
        turns = [{'session': r['session'], 'turn': r['turn'], 'user': r['user_text'] or '', 'assistant': r['assistant_text'] or '',
                  'changes': changes.change_block(r['diff'] or '', r['numstat'] or ''), 'at': r['started_at']} for r in batch]
        t0 = time.time()
        try:
            res = writer.write_batch(paths.home(), stores, turns, st, project)
        except Exception as exc:
            _log({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'project': project, 'turns': len(batch), 'error': str(exc)[:300]}); return 0
        # 程序兜底（便宜模型偶发漏写，兼容实测 28.14）：用户明确要求记住的轮次，这一批却没写出任何新记忆 → 逐轮单独重写一次
        if not res['new_facts'] and not retrying:
            for r in [r for r in batch if EXPLICIT.search(r['user_text'] or '')]: flush([r], True)
        st.executemany('UPDATE backlog SET written=1 WHERE session=? AND turn=?', [(r['session'], r['turn']) for r in batch])
        _log({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'project': project, 'turns': len(batch), 'calls': res['calls'], 'usage': res['usage'],
              'new_facts': res['new_facts'], 'secs': round(time.time() - t0, 1), 'steps': [x.get('step') for x in res['log']]})
        return len(batch)
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
    for p in projects:
        n = write_project(p)
        print('%s：%s' % (p or '（个人）', '已有写入进程在运行，跳过' if n is None else '写入 %d 轮' % n))
    return 0
