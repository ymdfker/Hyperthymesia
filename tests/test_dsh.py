"""DeepSeek Harness 接入：会话记录解析、官方价格页解析、profile 补丁的安装与卸载。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import hooks, install, models
from hyperthymesia.store import close_all

PRICING_MD = """| 模型 | 模型 | 模型 | deepseek-flash(1) | deepseek-v4-pro |
| --- | --- | --- | --- | --- |
| 价格(2) | 百万tokens输入 / （缓存命中） | 高峰时段 | 0.04元 | 0.30元 |
| 价格(2) | 百万tokens输入 / （缓存未命中） | 空闲时段 | 1元 | 4.5元 |
| 价格(2) | 百万tokens输入 / （缓存未命中） | 高峰时段 | 2元 | 9.0元 |
| 价格(2) | 百万tokens输出 | 高峰时段 | 8元 | 27.0元 |
"""


class DshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.root), 'HYPERTHYMESIA_HOME': str(self.root / 'mem'),
                                                'DSH_HOME': str(self.root / '.dsh')}); self.env.start()

    def tearDown(self): self.env.stop(); close_all(); self.tmp.cleanup()

    def test_turns_only_user_source_and_last_text(self):
        rows = [{'type': 'session', 'cwd': '/w'},
                {'type': 'user/message', 'time': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '超时设为45秒'}]}},
                {'type': 'user/message', 'time': 2, 'data': {'source': {'kind': 'plugin', 'plugin': 'hooks-claude-code'}, 'content': [{'type': 'text', 'text': '长期记忆…'}]}},
                {'type': 'assistant/message', 'data': {'message': {'content': [{'type': 'reasoning', 'text': '想'}, {'type': 'tool-call'}]}}},
                {'type': 'assistant/message', 'data': {'message': {'content': [{'type': 'text', 'text': '好的'}]}}}]
        turns, cwd = hooks.dsh_turns('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
        self.assertEqual(cwd, '/w'); self.assertEqual([(t[1], t[2]) for t in turns], [('超时设为45秒', '好的')])

    def test_marker_check_ignores_text_before_compaction(self):
        before = '{"type":"user/message","data":"长期记忆…"}\n'
        self.assertIn('长期记忆', hooks.after_compaction(before))
        for comp in ('{"type":"compaction/end","seq":9}', '{"type":"compacted","payload":{"replacement_history":[]}}'):
            self.assertNotIn('长期记忆', hooks.after_compaction(before + comp + '\n{"type":"user/message"}'))
        kept = '{"type":"compacted","payload":{"replacement_history":["长期记忆…"]}}'   # Codex 压缩保留了注入内容：仍算在上文
        self.assertIn('长期记忆', hooks.after_compaction(before + kept))

    def test_official_price_page(self):
        with mock.patch.object(models, '_fetch', return_value=PRICING_MD):
            p = models.deepseek_prices()
        self.assertAlmostEqual(p['deepseek-flash'], 2 * 0.9 + 8 * 0.1)   # 高峰时段、缓存未命中输入与输出 9:1
        self.assertLess(p['deepseek-flash'], p['deepseek-v4-pro'])

    def test_install_patch_roundtrip(self):
        prof = self.root / '.dsh/profiles/web'; (prof / 'node_modules').mkdir(parents=True)
        (prof / 'package.json').write_text('{}'); (self.root / '.dsh/profiles/headless').mkdir()
        for k in install.DSH_PKGS: (prof / 'node_modules' / k).mkdir(parents=True)
        orig = '# 用户注释\n[]\n'; (prof / 'cordis.patch.yml').write_text(orig, encoding='utf-8')
        install.dsh()
        t = (prof / 'cordis.patch.yml').read_text(encoding='utf-8')
        self.assertNotIn('\n[]', t); self.assertIn('isolate:', t); self.assertIn('dsh-mcp-client', t)
        self.assertFalse((self.root / '.dsh/profiles/headless/cordis.patch.yml').exists())   # 写入器用的 headless 不装钩子
        install.dsh()                                                                         # 重复安装不重复追加
        self.assertEqual((prof / 'cordis.patch.yml').read_text(encoding='utf-8').count('id: hyperthymesia\n'), 1)
        install.dsh(remove=True)
        self.assertEqual((prof / 'cordis.patch.yml').read_text(encoding='utf-8').strip(), orig.strip())


if __name__ == '__main__':
    unittest.main()


class ExplicitRetryTest(unittest.TestCase):
    """便宜模型偶发漏写：用户明确要求记住的轮次，这一批没写出新记忆时，逐轮单独重写一次。"""
    def test_retry_explicit_turn_once(self):
        from hyperthymesia import writecmd
        from hyperthymesia.store import state
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOME': d}):
            st = state(Path(d))
            for i, u in enumerate(['记住：每周四发布', '你好'], 1):
                st.execute("INSERT INTO backlog(session, turn, project, user_text, assistant_text, started_at, completed_at, diff, numstat, written) "
                           "VALUES('s', ?, '', ?, '好', ?, ?, '', '', 0)", (i, u, 't%d' % i, 't%d' % i))
            calls = []
            def fake(home, stores, turns, st, project):
                calls.append([t['user'] for t in turns]); return {'new_facts': 0 if len(calls) == 1 else 1, 'calls': 1, 'usage': {}, 'log': []}
            with mock.patch.object(writecmd.writer, 'write_batch', side_effect=fake):
                writecmd.write_project('')
            close_all()
        self.assertEqual(calls, [['记住：每周四发布', '你好'], ['记住：每周四发布']])


class CodexSubagentTest(unittest.TestCase):
    def test_subagent_rollout_detected(self):
        with tempfile.TemporaryDirectory() as d:
            child, parent = Path(d) / 'c.jsonl', Path(d) / 'p.jsonl'
            child.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'b', 'parent_thread_id': 'a', 'thread_source': 'subagent'}}) + '\n', encoding='utf-8')
            parent.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'a', 'thread_source': 'user'}}) + '\n', encoding='utf-8')
            self.assertTrue(hooks.is_subagent({'transcript_path': str(child)}, 'codex'))
            self.assertFalse(hooks.is_subagent({'transcript_path': str(parent)}, 'codex'))
            self.assertFalse(hooks.is_subagent({'transcript_path': str(child)}, 'claude'))
