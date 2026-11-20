"""GitHub issue #6 第三轮（v0.2.8 Windows 实测）回归测试：临时目录、假模型，不调用真实模型。"""
import io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import models, paths, providers, writecmd
from hyperthymesia.store import close_all, state


class ThirdRoundTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOME': str(self.root / 'home'), 'HYPERTHYMESIA_PROVIDER': 'fake'})
        self.env.start(); paths.home().mkdir(parents=True, exist_ok=True)

    def tearDown(self): self.env.stop(); close_all(); self.tmp.cleanup()

    def test_auth_hint_gives_concrete_config_steps(self):
        # P0-A：鉴权失败提示必须给出配置文件位置、字段和验证命令，而不只是方向。
        hint = providers._failure_hint('Authentication required')
        for part in ('config.toml', 'provider = "openai"', 'base_url', 'api_key_env', 'setx', 'hyperthymesia doctor'):
            self.assertIn(part, hint)

    def test_cli_slot_serializes_same_cli_across_writers(self):
        # P1-B：同一宿主CLI同一时刻只允许一个写入器调用；第二个拿不到时等待，超时报错不调用。
        with providers.cli_slot(paths.home(), 'codebuddy'):
            with mock.patch('time.sleep'), self.assertRaises(providers.ProviderError) as cm:
                with providers.cli_slot(paths.home(), 'codebuddy', wait=-1): pass
        self.assertIn('占用', str(cm.exception))
        with providers.cli_slot(paths.home(), 'codebuddy'): pass   # 释放后可再拿到

    def test_eaddrinuse_retried_once(self):
        calls = []
        def fake_run(cmd, **kw):
            calls.append(1)
            if len(calls) == 1: return subprocess.CompletedProcess(cmd, 1, '', 'Error: listen EADDRINUSE: address already in use')
            return subprocess.CompletedProcess(cmd, 0, json.dumps({'type': 'result', 'result': '{}', 'session_id': 's'}), '')
        log = []
        with mock.patch.object(providers, 'codebuddy_cmd', return_value=['cb']), mock.patch.object(providers, 'model', return_value='m'), \
             mock.patch.object(providers, '_run_cli', side_effect=fake_run), mock.patch('time.sleep'):
            rep = providers._codebuddy(paths.home(), 'sys', 'p', None, log)
        self.assertEqual(len(calls), 2); self.assertEqual(rep.text, '{}')
        self.assertIn({'step': 'cli_port_busy_retry'}, log)

    def test_models_cache_not_rewritten_when_unchanged(self):
        # P2-D：内容不变不刷新文件。
        models._save({'x': 1}); p = models._cache_path(); os.utime(p, (1, 1))
        models._save({'x': 1}); self.assertEqual(p.stat().st_mtime, 1)
        models._save({'x': 2}); self.assertNotEqual(p.stat().st_mtime, 1)

    def test_doctor_does_not_touch_models_cache(self):
        from hyperthymesia.__main__ import _doctor
        models._save({'codebuddy': {'model': '', 'checked': [{'model': 'glm-5.1'}]}}); p = models._cache_path(); os.utime(p, (1, 1))
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_PROVIDER': 'codebuddy'}), mock.patch('sys.stdout', new_callable=io.StringIO):
            _doctor([])
        self.assertEqual(p.stat().st_mtime, 1)

    def test_explain_points_to_real_location(self):
        # P2-E：没有判定理由时不再说“参见logs/models.log”，而是给出质量问题/错误或models.json位置。
        models._save({'codebuddy': {'model': '', 'checked': [{'model': 'a', 'quality_issues': ['漏了价格']}, {'model': 'b'}]}})
        text = models.explain('codebuddy')
        self.assertIn('漏了价格', text); self.assertIn('models.json', text); self.assertNotIn('参见logs/models.log', text)

    def test_zero_turns_says_why(self):
        # P2-F：写入0轮时说明是无待写、已写过还是未完成。
        st = state(paths.home())
        st.execute("INSERT INTO backlog(session,turn,project,user_text,assistant_text,started_at,completed_at,written) VALUES('s',1,'/p','u','a','2026-11-20','2026-11-20',1)")
        st.execute("INSERT INTO backlog(session,turn,project,user_text,assistant_text,started_at,completed_at,written) VALUES('s',2,'/p','u','a','2026-11-20',NULL,0)")
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            writecmd.run(['--project', '/p'])
        text = out.getvalue()
        self.assertIn('写入 0 轮', text); self.assertIn('此前已写入1轮', text); self.assertIn('1轮尚未完成', text)


if __name__ == '__main__':
    unittest.main()
