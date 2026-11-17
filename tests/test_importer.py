"""导入历史会话：三种会话记录格式的解析、去重、钩子已记过的轮次不重复导入。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import importer, paths
from hyperthymesia.store import close_all, state


def W(p, rows): p.parent.mkdir(parents=True, exist_ok=True); p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.root), 'HYPERTHYMESIA_HOME': str(self.root / 'mem')}); self.env.start()

    def tearDown(self): self.env.stop(); close_all(); self.tmp.cleanup()

    def test_claude_like_parse_skips_tool_results(self):
        p = self.root / '.claude/projects/x/s1.jsonl'
        W(p, [{'type': 'user', 'cwd': '/w', 'timestamp': 't1', 'message': {'content': '分页改成50'}},
              {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}},
              {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}},
              {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '改好了'}]}},
              {'type': 'user', 'timestamp': 't2', 'message': {'content': '<command-name>/clear</command-name>'}}])
        self.assertEqual(importer._claude_like(p), ([['t1', '分页改成50', '改好了']], '/w'))

    def test_codex_and_codebuddy_parse(self):
        c = self.root / 'c.jsonl'
        W(c, [{'type': 'session_meta', 'payload': {'cwd': '/w'}},
              {'type': 'event_msg', 'timestamp': 't1', 'payload': {'type': 'user_message', 'message': '加个 remove 命令'}},
              {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'done'}}])
        self.assertEqual(importer._codex(c), ([['t1', '加个 remove 命令', 'done']], '/w'))
        b = self.root / 'b.jsonl'
        W(b, [{'type': 'message', 'role': 'user', 'cwd': '/w', 'timestamp': 1, 'content': [{'type': 'input_text', 'text': '问'}]},
              {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '答'}]}])
        self.assertEqual(importer._codebuddy(b), ([['1', '问', '答']], '/w'))

    def test_import_dedupes_and_skips_hooked_turns(self):
        proj = self.root / 'proj'; proj.mkdir()
        p = self.root / '.claude/projects/x/s1.jsonl'
        W(p, [{'type': 'user', 'cwd': str(proj), 'timestamp': '2026-01-01T00:00:01', 'message': {'content': '第一轮'}},
              {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '一'}]}},
              {'type': 'user', 'timestamp': '2026-01-01T00:00:09', 'message': {'content': '第二轮（接入之后）'}},
              {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '二'}]}}])
        st = state(paths.home())
        st.execute("INSERT INTO backlog(session, turn, started_at) VALUES('s1', 1, '2026-01-01T00:00:05')")   # 钩子从这之后开始记
        ss = importer.sessions('claude')
        self.assertEqual(importer.import_sessions('claude', ss, write=False), {'s1': 1})
        self.assertEqual(importer.import_sessions('claude', ss, write=False), {'s1': 0})   # 再导一次不重复
        self.assertEqual(st.execute("SELECT user_text FROM backlog WHERE session='s1:import'").fetchall()[0][0], '第一轮')

    def test_codex_desktop_messages_pair_by_turn_and_exclude_injection(self):
        p = self.root / 'desktop.jsonl'
        def message(text, tid, kind):
            return {'type': 'response_item', 'timestamp': '2026-11-16', 'payload': {'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': text}],
                'internal_chat_message_metadata_passthrough': {'turn_id': tid, 'content_item_kinds': [kind]}}}
        W(p, [message('系统环境', 'a', 'environments.environment_context'), message('第一轮真实问题', 'a', 'user.text'),
              message('第二轮真实问题', 'b', 'user.text'),
              {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'a', 'last_agent_message': '第一轮最终回复'}},
              {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'b', 'last_agent_message': '第二轮最终回复'}}])
        rows, _ = importer._codex(p)
        self.assertEqual([r[1:] for r in rows], [['第一轮真实问题', '第一轮最终回复'], ['第二轮真实问题', '第二轮最终回复']])


if __name__ == '__main__':
    unittest.main()
