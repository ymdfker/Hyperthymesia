"""GitHub issue #5/#6（v0.2.7 Windows 实测反馈）的回归测试：全部临时目录、假模型，不调用真实模型。"""
import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import hooks, install, paths, providers, writecmd, writer
from hyperthymesia.store import close_all, Store, state
os.environ.setdefault('HYPERTHYMESIA_WRITER_MODE', 'single')   # 这些用例按一次调用流程预设回答；两阶段流程见 test_staged.py


class WindowsFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOME': str(self.root / 'home'), 'HYPERTHYMESIA_PROVIDER': 'fake'})
        self.env.start(); providers.FAKE_REPLIES.clear()

    def tearDown(self): self.env.stop(); close_all(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

    def hook(self, event, d):
        with mock.patch('sys.stdin', io.StringIO(json.dumps(d))), mock.patch('sys.stdout', new_callable=io.StringIO) as out, \
             mock.patch.object(hooks, 'spawn_writer') as spawned:
            hooks.run([event, '--agent', 'qoder'])
        return out.getvalue(), spawned

    def test_writer_workdir_session_is_not_captured_even_without_internal_env(self):
        work = paths.home() / 'writer_work'; work.mkdir(parents=True, exist_ok=True)
        os.environ.pop('HYPERTHYMESIA_INTERNAL_CALL', None)
        out, spawned = self.hook('prompt-submit', {'session_id': 'w1', 'cwd': str(work), 'prompt': '整理记忆'})
        self.assertEqual(out, '{}')
        self.hook('stop', {'session_id': 'w1', 'cwd': str(work)})
        self.assertEqual(state(paths.home()).execute('SELECT COUNT(*) FROM backlog').fetchone()[0], 0)
        self.assertFalse(list((paths.home() / 'projects').glob('writer_work*')) if (paths.home() / 'projects').exists() else [])

    def test_old_self_loop_backlog_is_skipped_not_written(self):
        work = str(paths.home() / 'writer_work'); (paths.home() / 'writer_work').mkdir(parents=True, exist_ok=True)
        st = state(paths.home())
        st.execute("INSERT INTO backlog(session,turn,project,user_text,assistant_text,started_at,completed_at,written) VALUES('w',1,?,'u','a','2026-11-20','2026-11-20',0)", (work,))
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(writecmd.run(['--project', work]), 0)
        self.assertIn('跳过', out.getvalue())
        self.assertEqual(st.execute('SELECT written FROM backlog').fetchone()[0], 0)   # 不删除、不冒充已写

    def test_spawned_writer_does_not_reuse_parent_pyinstaller_dir(self):
        with mock.patch('subprocess.Popen') as popen:
            popen.return_value.pid = 1
            hooks.spawn_writer('/p', 'qoder')
        env = popen.call_args.kwargs['env']
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(env['HYPERTHYMESIA_INTERNAL_CALL'], '1')

    def test_json_syntax_error_gets_one_format_only_fix(self):
        good = {'objects': [{'key': 'k', 'name': '配置', 'scope': 'project', 'parents': []}],
                'memories': [{'title': '超时', 'text': '超时60秒', 'kind': 'fact', 'about': ['k'], 'evidence': ['超时60秒'], 'invalidates': []}]}
        broken = json.dumps(good, ensure_ascii=False).replace('"title": "超时"', '"title": "他说"超时""')   # 未转义引号，本地修复不了
        self.assertRaises(ValueError, writer.parse, broken)
        seen = []
        def fix(prompt):
            seen.append(prompt); return json.dumps(good, ensure_ascii=False)
        providers.FAKE_REPLIES.extend([broken, fix, '{}', '{}', '{}'])
        stores = {'u': Store(self.root / 'u.db', 'u'), 'p': Store(self.root / 'p.db', 'p')}
        res = writer.write_batch(paths.home(), stores, [{'session': 's', 'turn': 1, 'user': '超时60秒', 'assistant': '好', 'at': '2026-11-20'}], state(paths.home()), '')
        self.assertIn('只修正JSON语法', seen[0]); self.assertIn(broken, seen[0])
        self.assertIn('format_fixed', [x.get('step') for x in res['log']])
        self.assertTrue(any(f['text'] == '超时60秒' for f in stores['p'].facts()))

    def test_json_syntax_error_twice_keeps_failure(self):
        providers.FAKE_REPLIES.extend(['{"memories": [{"text": "a" "b"}]}', '{"memories": [{"text": "a" "b"}]}'])
        stores = {'u': Store(self.root / 'u.db', 'u'), 'p': Store(self.root / 'p.db', 'p')}
        with self.assertRaises(providers.ProviderError) as cm:
            writer.write_batch(paths.home(), stores, [{'session': 's', 'turn': 1, 'user': 'x', 'assistant': 'y', 'at': '2026-11-20'}], state(paths.home()), '')
        self.assertIn('只修格式的重发仍无法解析', str(cm.exception))

    def test_install_from_versioned_exe_uses_stable_path(self):
        user = self.root / 'user'; user.mkdir()
        exe = self.root / ('hyperthymesia-v0.2.7.exe' if os.name == 'nt' else 'hyperthymesia-v0.2.7'); exe.write_bytes(b'bin')
        with mock.patch.dict(os.environ, {'HOME': str(user), 'USERPROFILE': str(user)}), mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, 'executable', str(exe)):
            os.environ.pop('HYPERTHYMESIA_SELF', None)
            msg = install.stable_binary()
            target = user / '.hyperthymesia' / 'bin' / ('hyperthymesia.exe' if os.name == 'nt' else 'hyperthymesia')
            self.assertTrue(target.is_file()); self.assertIn(str(target), msg)
            self.assertEqual(hooks.self_cmd(), [str(target)])
            os.environ.pop('HYPERTHYMESIA_SELF', None)

    def test_busy_lock_reports_holder(self):
        project = str(self.root / 'proj')
        with writecmd.Lock(project) as first:
            self.assertTrue(first.ok)
            with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                st = state(paths.home())
                st.execute("INSERT INTO backlog(session,turn,project,user_text,assistant_text,started_at,completed_at,written) VALUES('s',1,?,'u','a','t','t',0)", (project,))
                writecmd.run(['--project', project])
            self.assertIn('占用', out.getvalue())


if __name__ == '__main__': unittest.main()
