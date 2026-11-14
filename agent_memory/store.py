"""SQLite memory store (design 27.3). One file per scope: personal.db, projects/<key>.db. Transactions replace the
prototype's file locks; WAL mode lets the reader (MCP server) and the background writer work at the same time.

Model
- objects: things facts are about (a person, a store, a config area). Multiple parents; aliases in the source language.
- facts: one atomic, independently correctable statement. kind fact|suggestion; source_role user|assistant|mixed.
  A correction never edits a row: it adds a new fact and marks the old one superseded (history stays).
- fact_objects: every object a fact is about (the first is its home object).
- evidence: verbatim quotes binding a fact to the source turn it came from.
- sources: the full text of every written turn (user, assistant, workspace change), kept so a fact can be checked
  against what was actually said and so lost details can be searched later.

Operational state (backlog of unwritten turns, per-turn workspace changes, writer sessions, per-session read
delivery) lives in state.db, not in the scoped stores."""
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
"""
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog(session TEXT NOT NULL, turn INTEGER NOT NULL, project TEXT, user_text TEXT, assistant_text TEXT,
  started_at TEXT, completed_at TEXT, diff TEXT DEFAULT '', numstat TEXT DEFAULT '', written INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(session, turn));
CREATE TABLE IF NOT EXISTS writer_sessions(store TEXT PRIMARY KEY, provider TEXT, sid TEXT, last_input INTEGER);
CREATE TABLE IF NOT EXISTS delivered(session TEXT NOT NULL, store TEXT NOT NULL, fact INTEGER NOT NULL, digest TEXT,
  PRIMARY KEY(session, store, fact));
"""


def connect(path, schema=SCHEMA):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)   # explicit BEGIN/COMMIT via tx()
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA foreign_keys=ON')
    db.executescript(schema)
    return db


class tx:
    """with tx(db): ...  -> one IMMEDIATE transaction (a second writer waits instead of interleaving)."""
    def __init__(self, db): self.db = db
    def __enter__(self): self.db.execute('BEGIN IMMEDIATE'); return self.db
    def __exit__(self, et, ev, tb):
        self.db.execute('COMMIT' if et is None else 'ROLLBACK'); return False


class Store:
    """One scoped store. `scope` is 'u' (personal) or 'p' (project); it prefixes every id shown to a model, so the
    writer can address objects and records of both stores in one answer (u7 / p7, ru41 / rp41)."""

    def __init__(self, path, scope):
        self.path = Path(path); self.scope = scope; self.db = connect(path)

    # ---- ids as the model sees them
    def oid(self, n): return '%s%d' % (self.scope, n)
    def rid(self, n): return 'r%s%d' % (self.scope, n)

    # ---- objects
    def add_object(self, name, purpose='', parents=(), aliases=()):
        with tx(self.db) as d:
            n = d.execute('INSERT INTO objects(name, purpose, created_at) VALUES(?,?,?)', (name, purpose, time.time())).lastrowid
            for p in parents: d.execute('INSERT OR IGNORE INTO object_parents VALUES(?,?)', (n, p))
            for a in aliases: d.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)', (n, a))
        return n

    def objects(self):
        """[{id, name, purpose, parents, aliases, facts}] with active fact counts (the writer's object index)."""
        d = self.db
        cnt = dict(d.execute('SELECT object, COUNT(*) FROM facts WHERE active=1 GROUP BY object').fetchall())
        par = {}; al = {}
        for c, p in d.execute('SELECT child, parent FROM object_parents'): par.setdefault(c, []).append(p)
        for o, a in d.execute('SELECT object, alias FROM aliases'): al.setdefault(o, []).append(a)
        return [{'id': r['id'], 'name': r['name'], 'purpose': r['purpose'], 'parents': par.get(r['id'], []),
                 'aliases': al.get(r['id'], []), 'facts': cnt.get(r['id'], 0)} for r in d.execute('SELECT * FROM objects ORDER BY id')]

    # ---- sources
    def add_source(self, sid, session, turn, role, at, text):
        with tx(self.db) as d:
            d.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?)', (sid, session, turn, role, at, text))

    # ---- facts
    def add_fact(self, about, text, kind='fact', source_role='user', title='', evidence=(), supersedes=()):
        """about: [object ids], first = home object. evidence: [(source id, quote)]. supersedes: fact ids this one
        replaces (they become inactive and point here). Returns the new fact id."""
        now = time.time()
        with tx(self.db) as d:
            n = d.execute('INSERT INTO facts(object, kind, source_role, title, text, created_at, updated_at) VALUES(?,?,?,?,?,?,?)',
                          (about[0], kind, source_role, title, text, now, now)).lastrowid
            for o in dict.fromkeys(about): d.execute('INSERT OR IGNORE INTO fact_objects VALUES(?,?)', (n, o))
            for s, q in evidence: d.execute('INSERT INTO evidence VALUES(?,?,?)', (n, s, q))
            for old in supersedes:
                d.execute('UPDATE facts SET active=0, superseded_by=?, updated_at=? WHERE id=? AND active=1', (n, now, old))
        return n

    def set_advice_status(self, fact, effect, reason):
        with tx(self.db) as d:
            d.execute('UPDATE facts SET advice_status=?, updated_at=? WHERE id=?',
                      (json.dumps({'effect': effect, 'reason': reason, 'at': time.time()}, ensure_ascii=False), time.time(), fact))

    def move_fact(self, fact, obj):
        with tx(self.db) as d:
            d.execute('UPDATE facts SET object=?, updated_at=? WHERE id=?', (obj, time.time(), fact))
            d.execute('INSERT OR IGNORE INTO fact_objects VALUES(?,?)', (fact, obj))

    def facts(self, objects=None, active=True):
        """active facts (optionally only those about the given objects), each with its about list."""
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
        """source ids cited by active user/mixed facts (the coverage check of gap filling)."""
        return {r[0] for r in self.db.execute(
            "SELECT e.source FROM evidence e JOIN facts f ON f.id=e.fact WHERE f.active=1 AND f.source_role IN ('user','mixed')")}

    def text_size(self):
        return self.db.execute('SELECT COALESCE(SUM(LENGTH(text)),0) FROM facts WHERE active=1').fetchone()[0]


def state(home):
    return connect(Path(home) / 'state.db', STATE_SCHEMA)
