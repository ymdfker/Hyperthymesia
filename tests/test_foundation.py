"""第 1 步基础模块：路径与作用域、SQLite 存储、脱敏、工作区改动采集（有 git 与无 git）。"""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from agent_memory import changes, paths
from agent_memory.redact import redact
from agent_memory.store import Store, state


class TmpHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'AGENT_MEMORY_HOME': str(self.root / 'home')}); self.env.start()
    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()


class PathsTest(TmpHome):
    def test_personal_and_project_are_separate(self):
        a = self.root / 'projA'; b = self.root / 'projB'; a.mkdir(); b.mkdir()
        pa, ra = paths.project_db(a); pb, rb = paths.project_db(b)
        self.assertNotEqual(pa, pb); self.assertNotEqual(pa, paths.personal_db())
        self.assertEqual(ra, a.resolve())

    def test_subdirectory_of_git_repo_maps_to_repo_root(self):
        if not changes.has_git(): self.skipTest('git not installed')
        r = self.root / 'repo'; (r / 'src' / 'deep').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(r)], check=True)
        self.assertEqual(paths.project_db(r / 'src' / 'deep')[0], paths.project_db(r)[0])

    def test_no_cwd_means_no_project(self):
        self.assertEqual(paths.project_db(None), (None, None))

    def test_same_folder_name_different_paths(self):
        a = self.root / 'x' / 'app'; b = self.root / 'y' / 'app'; a.mkdir(parents=True); b.mkdir(parents=True)
        self.assertNotEqual(paths.project_db(a)[0], paths.project_db(b)[0])


class StoreTest(TmpHome):
    def test_facts_corrections_history(self):
        s = Store(self.root / 'p.db', 'p')
        shop = s.add_object('文三路店', 'store', aliases=['老店'])
        mgr = s.add_object('陈晓', 'person', parents=[shop])
        f1 = s.add_fact([shop], '文三路店每周三闭店', evidence=[('t1u', '每周三闭店')])
        f2 = s.add_fact([shop, mgr], '店长是陈晓')
        f3 = s.add_fact([shop], '文三路店每周四闭店', supersedes=[f1])
        act = {f['id'] for f in s.facts()}
        self.assertEqual(act, {f2, f3})
        self.assertEqual(s.fact(f1)['superseded_by'], f3)
        self.assertEqual({f['id'] for f in s.facts(objects=[mgr])}, {f2})
        self.assertEqual(len(s.facts(active=False)), 3)
        obj = {o['id']: o for o in s.objects()}
        self.assertEqual(obj[mgr]['parents'], [shop]); self.assertEqual(obj[shop]['aliases'], ['老店']); self.assertEqual(obj[shop]['facts'], 2)
        self.assertEqual((s.oid(shop), s.rid(f2)), ('p%d' % shop, 'rp%d' % f2))

    def test_advice_status_and_evidence_turns(self):
        s = Store(self.root / 'u.db', 'u'); o = s.add_object('健身')
        a = s.add_fact([o], '助手建议周一三五训练', kind='suggestion', source_role='assistant', evidence=[('t3a', '周一三五')])
        u = s.add_fact([o], '用户改为周二四六训练', evidence=[('t5u', '周二四六')])
        s.set_advice_status(a, 'basis_changed', '训练日已改')
        self.assertIn('basis_changed', s.fact(a)['advice_status'])
        self.assertEqual(s.evidence_turns(), {'t5u'})   # 只有助手证据不算覆盖该轮

    def test_state_db_tables(self):
        st = state(self.root / 'home')
        st.execute("INSERT INTO backlog(session, turn, user_text) VALUES('s', 1, 'hi')")
        self.assertEqual(st.execute('SELECT COUNT(*) FROM backlog').fetchone()[0], 1)


class RedactTest(unittest.TestCase):
    def test_masks_secrets_keeps_facts(self):
        cases = [('+OPENAI_API_KEY = "sk-proj-abcdefghijklmnopqrstuvwx1234"', True),
                 ('+DB_URL = "postgres://admin:hunter2pass@db.local:5432/inv"', True),
                 ('我的数据库密码是 Qw3rty!9，帮我写连接配置', True),
                 ('+GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123', True),
                 ('Authorization: Bearer abcdefghijklmnop1234567890', True),
                 ('+SECRET_KEY = os.environ["SECRET_KEY"]', False), ('+MAX_TOKENS = 4096', False),
                 ('+API_KEY = ""', False), ('+password = "${DB_PASSWORD}"', False),
                 ('token 有效期 30 天，刷新接口是 /auth/refresh', False), ('+AUTH_URL = "https://auth.example.com/login"', False)]
        for text, secret in cases:
            with self.subTest(text=text): self.assertEqual(bool(redact(text)[1]), secret)
        self.assertNotIn('hunter2pass', redact(cases[1][0])[0]); self.assertIn('db.local:5432', redact(cases[1][0])[0])


class ChangesTest(TmpHome):
    def _turn(self, ws, edit):
        home = self.root / 'home'; a = changes.snapshot(home, ws); edit(); b = changes.snapshot(home, ws)
        d, ns = changes.diff(home, ws, a, b); return changes.change_block(d, ns)

    def _edit(self, ws):
        def go():
            (ws / 'config.py').write_text('TIMEOUT = 30\nDB_URL = "postgres://admin:hunter2pass@db.local/inv"\n')
            (ws / '.env').write_text('OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx1234\n')
            (ws / 'app.log').write_text('noise\n'); (ws / 'node_modules').mkdir(); (ws / 'node_modules' / 'x.js').write_text('y\n')
            (ws / 'notes.md').write_text('new\n')
        return go

    def _check(self, block):
        self.assertIn('+TIMEOUT = 30', block); self.assertIn('-TIMEOUT = 10', block); self.assertIn('[notes.md]', block)
        for bad in ('hunter2pass', 'sk-proj', 'noise', 'x.js', '.env]'):
            self.assertNotIn(bad, block)

    def test_git_shadow_mode_leaves_user_repo_alone(self):
        if not changes.has_git(): self.skipTest('git not installed')
        ws = self.root / 'ws'; ws.mkdir(); (ws / 'config.py').write_text('TIMEOUT = 10\n')
        subprocess.run(['git', 'init', '-q', str(ws)], check=True)
        subprocess.run(['git', '-C', str(ws), 'add', 'config.py'], check=True)
        before = subprocess.run(['git', '-C', str(ws), 'status', '--porcelain'], capture_output=True, text=True).stdout
        block = self._turn(ws, self._edit(ws)); self._check(block)
        (ws / 'config.py').write_text('TIMEOUT = 10\n')
        for p in ('notes.md', 'app.log', '.env'): (ws / p).unlink()
        import shutil; shutil.rmtree(ws / 'node_modules')
        after = subprocess.run(['git', '-C', str(ws), 'status', '--porcelain'], capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_file_snapshot_mode_without_git(self):
        ws = self.root / 'ws2'; ws.mkdir(); (ws / 'config.py').write_text('TIMEOUT = 10\n')
        with mock.patch.object(changes, 'has_git', return_value=False):
            self._check(self._turn(ws, self._edit(ws)))

    def test_no_change_gives_empty_block(self):
        ws = self.root / 'ws3'; ws.mkdir(); (ws / 'a.py').write_text('x = 1\n')
        self.assertEqual(self._turn(ws, lambda: None), '')


if __name__ == '__main__':
    unittest.main()
