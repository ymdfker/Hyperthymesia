"""SQLite 记忆库（设计 27.3）。每个作用域一个文件：personal.db、projects/<key>.db。
用事务代替原型里的文件锁；WAL 模式让读取方（MCP 服务）和后台写入可以同时工作。

数据模型
- objects：事实所关于的事物（人、门店、某个配置方面）。可多父对象；别名含原文语言的写法。
- facts：一条可独立更正的原子事实。kind 为 fact|suggestion；source_role 为 user|assistant|mixed。
  更正从不修改旧行：新增一条事实，并把旧事实标为被取代（历史保留）。
- fact_objects：事实涉及的全部对象（第一个是它的归属对象）。
- evidence：把事实绑定到来源轮次的逐字引用。
- sources：每个已写入轮次的全文（用户、助手、工作区改动），用于核对事实与原话，以及日后检索丢失的细节。

运行状态（未写入的积压轮次、每轮工作区改动、写入会话、按会话的读取去重）放在 state.db，不放在作用域库里。"""
import json, sqlite3, time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS objects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, purpose TEXT DEFAULT '', created_at REAL);
CREATE TABLE IF NOT EXISTS object_parents(child INTEGER NOT NULL, parent INTEGER NOT NULL, PRIMARY KEY(child, parent));
CREATE TABLE IF NOT EXISTS aliases(object INTEGER NOT NULL, alias TEXT NOT NULL, PRIMARY KEY(object, alias));
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY, object INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'fact', source_role TEXT NOT NULL DEFAULT 'user',
  title TEXT DEFAULT '', text TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, superseded_by INTEGER,
  advice_status TEXT, created_at REAL, updated_at REAL);
CREATE INDEX IF NOT EXISTS facts_object ON facts(object, active);
CREATE TABLE IF NOT EXISTS fact_objects(fact INTEGER NOT NULL, object INTEGER NOT NULL, PRIMARY KEY(fact, object));
CREATE TABLE IF NOT EXISTS evidence(fact INTEGER NOT NULL, source TEXT NOT NULL, quote TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, session TEXT, turn INTEGER, role TEXT, at TEXT, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS writer_operations(operation TEXT PRIMARY KEY, fact INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS writer_object_operations(operation TEXT PRIMARY KEY, object INTEGER NOT NULL);
"""
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog(session TEXT NOT NULL, turn INTEGER NOT NULL, project TEXT, user_text TEXT, assistant_text TEXT,
  started_at TEXT, completed_at TEXT, diff TEXT DEFAULT '', numstat TEXT DEFAULT '', written INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(session, turn));
CREATE TABLE IF NOT EXISTS backlog_capture(session TEXT NOT NULL, turn INTEGER NOT NULL, transcript TEXT,
  agent TEXT, host_turn_id TEXT, PRIMARY KEY(session, turn));
CREATE TABLE IF NOT EXISTS backlog_agent(session TEXT PRIMARY KEY, agent TEXT);
CREATE TABLE IF NOT EXISTS writer_sessions(store TEXT PRIMARY KEY, provider TEXT, sid TEXT, last_input INTEGER);
CREATE TABLE IF NOT EXISTS delivered(session TEXT NOT NULL, store TEXT NOT NULL, fact INTEGER NOT NULL, digest TEXT,
  PRIMARY KEY(session, store, fact));
CREATE TABLE IF NOT EXISTS writer_progress(batch TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL);
"""


_OPEN = []   # 本进程打开的连接；测试结束时 close_all() 关闭（Windows 上未关闭的数据库文件无法删除）


def close_all():
    while _OPEN:
        try: _OPEN.pop().close()
        except Exception: pass


def connect(path, schema=SCHEMA):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)   # 由 tx() 显式 BEGIN/COMMIT
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA foreign_keys=ON')
    db.executescript(schema)
    _OPEN.append(db)
    return db


class tx:
    """with tx(db): ... -> 一个 IMMEDIATE 事务（第二个写入方会等待，而不是交错写入）。"""
    def __init__(self, db): self.db = db
    def __enter__(self): self.db.execute('BEGIN IMMEDIATE'); return self.db
    def __exit__(self, et, ev, tb):
        self.db.execute('COMMIT' if et is None else 'ROLLBACK'); return False


class Store:
    """一个作用域库。scope 为 'u'（个人）或 'p'（项目），作为给模型看的编号前缀，
    写入器在一次回答里就能同时引用两个库的对象和记录（u7 / p7，ru41 / rp41）。"""

    def __init__(self, path, scope):
        self.path = Path(path); self.scope = scope; self.db = connect(path)

    # ---- 模型看到的编号
    def oid(self, n): return '%s%d' % (self.scope, n)
    def rid(self, n): return 'r%s%d' % (self.scope, n)

    # ---- 对象
    def add_object(self, name, purpose='', parents=(), aliases=(), operation=None):
        with tx(self.db) as d:
            if operation:
                previous = d.execute('SELECT object FROM writer_object_operations WHERE operation=?', (operation,)).fetchone()
                if previous: return previous[0]
            n = d.execute('INSERT INTO objects(name, purpose, created_at) VALUES(?,?,?)', (name, purpose, time.time())).lastrowid
            for p in parents: d.execute('INSERT OR IGNORE INTO object_parents VALUES(?,?)', (n, p))
            for a in aliases: d.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)', (n, a))
            if operation: d.execute('INSERT INTO writer_object_operations VALUES(?,?)', (operation, n))
        return n

    def objects(self):
        """返回 [{id, name, purpose, parents, aliases, facts}]，facts 为有效事实数（写入器的对象索引）。"""
        d = self.db
        cnt = dict(d.execute('SELECT object, COUNT(*) FROM facts WHERE active=1 GROUP BY object').fetchall())
        par = {}; al = {}
        for c, p in d.execute('SELECT child, parent FROM object_parents'): par.setdefault(c, []).append(p)
        for o, a in d.execute('SELECT object, alias FROM aliases'): al.setdefault(o, []).append(a)
        return [{'id': r['id'], 'name': r['name'], 'purpose': r['purpose'], 'parents': par.get(r['id'], []),
                 'aliases': al.get(r['id'], []), 'facts': cnt.get(r['id'], 0)} for r in d.execute('SELECT * FROM objects ORDER BY id')]

    # ---- 原文
    def add_source(self, sid, session, turn, role, at, text):
        with tx(self.db) as d:
            d.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?)', (sid, session, turn, role, at, text))

    # ---- 事实
    def add_fact(self, about, text, kind='fact', source_role='user', title='', evidence=(), supersedes=(), operation=None, historical_of=None):
        """about：对象 id 列表，第一个为归属对象。evidence：[(来源 id, 引用)]。supersedes：被本条取代的事实 id
        （它们失效并指向本条）。返回新事实 id。"""
        now = time.time()
        with tx(self.db) as d:
            if operation:
                previous = d.execute('SELECT fact FROM writer_operations WHERE operation=?', (operation,)).fetchone()
                if previous: return previous[0]
            n = d.execute('INSERT INTO facts(object, kind, source_role, title, text, created_at, updated_at) VALUES(?,?,?,?,?,?,?)',
                          (about[0], kind, source_role, title, text, now, now)).lastrowid
            for o in dict.fromkeys(about): d.execute('INSERT OR IGNORE INTO fact_objects VALUES(?,?)', (n, o))
            for s, q in evidence: d.execute('INSERT INTO evidence VALUES(?,?,?)', (n, s, q))
            for old in supersedes:
                d.execute('UPDATE facts SET active=0, superseded_by=?, updated_at=? WHERE id=? AND active=1', (n, now, old))
            if historical_of is not None:
                d.execute('UPDATE facts SET active=0, superseded_by=? WHERE id=?', (historical_of, n))
            if operation: d.execute('INSERT INTO writer_operations VALUES(?,?)', (operation, n))
        return n

    def set_advice_status(self, fact, effect, reason):
        current = self.fact(fact)
        if current and current['advice_status']:
            previous = json.loads(current['advice_status'])
            if previous.get('effect') == effect and previous.get('reason') == reason: return
        with tx(self.db) as d:
            d.execute('UPDATE facts SET advice_status=?, updated_at=? WHERE id=?',
                      (json.dumps({'effect': effect, 'reason': reason, 'at': time.time()}, ensure_ascii=False), time.time(), fact))

    def move_fact(self, fact, obj):
        current = self.fact(fact)
        if current and current['object'] == obj: return
        with tx(self.db) as d:
            d.execute('UPDATE facts SET object=?, updated_at=? WHERE id=?', (obj, time.time(), fact))
            d.execute('INSERT OR IGNORE INTO fact_objects VALUES(?,?)', (fact, obj))

    def facts(self, objects=None, active=True):
        """有效事实（可只取涉及指定对象的），每条带 about 列表。"""
        d = self.db
        rows = [dict(r) for r in d.execute('SELECT * FROM facts WHERE active=1 ORDER BY id' if active else 'SELECT * FROM facts ORDER BY id')]
        about = {}
        for f, o in d.execute('SELECT fact, object FROM fact_objects'): about.setdefault(f, []).append(o)
        out = []
        for r in rows:
            r['about'] = about.get(r['id'], [r['object']])
            if objects is None or set(r['about']) & set(objects): out.append(r)
        return out

    def fact(self, n):
        r = self.db.execute('SELECT * FROM facts WHERE id=?', (n,)).fetchone()
        return dict(r) if r else None

    def evidence_turns(self):
        """被有效的用户/混合来源事实引用过的来源 id（缺口补写的覆盖检查用）。"""
        return {r[0] for r in self.db.execute(
            "SELECT e.source FROM evidence e JOIN facts f ON f.id=e.fact WHERE f.source_role IN ('user','mixed')")}

    def text_size(self):
        return self.db.execute('SELECT COALESCE(SUM(LENGTH(text)),0) FROM facts WHERE active=1').fetchone()[0]


def state(home):
    return connect(Path(home) / 'state.db', STATE_SCHEMA)
