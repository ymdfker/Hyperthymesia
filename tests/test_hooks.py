"""钩子流程、会话记录解析、后台写入命令、安装/卸载（全部在临时目录，不碰真实配置，不调用模型）。"""
import io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from agent_memory import hooks, install, paths, providers, writecmd
from agent_memory.store import Store, state


class HookFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'AGENT_MEMORY_HOME': str(self.root / 'home'), 'AGENT_MEMORY_PROVIDER': 'fake',
                                                'AGENT_MEMORY_BACKLOG_TOKENS': '100000'}); self.env.start()
        self.proj = self.root / 'proj'; self.proj.mkdir(); (self.proj / 'config.py').write_text('PAGE = 10\n')
        providers.FAKE_REPLIES.clear()
        self.spawn = mock.patch.object(hooks, 'spawn_writer'); self.spawned = self.spawn.start()   # 测试里不真的拉起后台写入

    def tearDown(self): self.spawn.stop(); self.env.stop(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

    def call(self, event, d, agent='claude'):
        with mock.patch('sys.stdin', io.StringIO(json.dumps(d))), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            hooks.run([event, '--agent', agent])
        return json.loads(out.getvalue() or '{}')

    def transcript(self, prompt, reply):
        p = self.root / 'tr.jsonl'
        rows = [{'type': 'user', 'message': {'role': 'user', 'content': prompt}},
                {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Edit'}]}},
                {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}},
                {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': reply}]}}]
        p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)); return str(p)

    def test_turn_backlog_changes_and_write(self):
        d = {'session_id': 's1', 'cwd': str(self.proj), 'prompt': '默认分页改成20，你直接改。'}
        self.assertEqual(self.call('prompt-submit', d), {})                     # 库还是空的：不注入
        (self.proj / 'config.py').write_text('PAGE = 20\n')
        self.call('stop', {'session_id': 's1', 'cwd': str(self.proj), 'transcript_path': self.transcript(d['prompt'], 'done')})
        self.call('stop', {'session_id': 's1', 'cwd': str(self.proj)})          # 重复 Stop 不重复记
        st = state(paths.home()); r = st.execute('SELECT * FROM backlog').fetchall()
        self.assertEqual(len(r), 1); self.assertEqual(r[0]['assistant_text'], 'done'); self.assertIn('+PAGE = 20', r[0]['diff'])
        providers.FAKE_REPLIES.append(json.dumps({'objects': [{'key': 'k', 'name': '分页配置', 'scope': 'project', 'parents': []}],
                                                  'memories': [{'title': '分页', 'text': '默认分页大小为20', 'kind': 'fact', 'about': ['k'],
                                                                'evidence': ['PAGE = 20'], 'invalidates': []}]}, ensure_ascii=False))
        providers.FAKE_REPLIES.append(json.dumps({}))                           # 缺口补写（用户原话没被用户事实引用）
        providers.FAKE_REPLIES.append(json.dumps({'replacements': []}))
        self.assertEqual(writecmd.write_project(str(paths.project_root(self.proj))), 1)
        self.assertEqual(st.execute('SELECT written FROM backlog').fetchone()[0], 1)
        pdb, _ = paths.project_db(self.proj); facts = Store(pdb, 'p').facts()
        self.assertEqual([f['text'] for f in facts], ['默认分页大小为20'])
        ctx = self.call('prompt-submit', {'session_id': 's1', 'cwd': str(self.proj), 'prompt': '分页多少？'})
        self.assertIn('默认分页大小为20', ctx['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.call('prompt-submit', {'session_id': 's1', 'cwd': str(self.proj), 'prompt': '再问一次'}), {})   # 没变化不重复注入
        self.call('pre-compact', {'session_id': 's1', 'cwd': str(self.proj)})
        self.assertTrue(self.spawned.called)                                    # 压缩前强制写入
        ctx = self.call('prompt-submit', {'session_id': 's1', 'cwd': str(self.proj), 'prompt': '压缩之后'})
        self.assertIn('（长期记忆全文）', ctx['hookSpecificOutput']['additionalContext'])

    def test_hook_never_breaks_host(self):
        with mock.patch('sys.stdin', io.StringIO('not json')), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(hooks.run(['stop']), 0)
        self.assertEqual(out.getvalue(), '{}')
        self.assertIn('hook_error', (paths.home() / 'logs' / 'hooks.log').read_text())

    def test_codex_final_reply(self):
        p = self.root / 'rollout.jsonl'
        rows = [{'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '我先看看文件'}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'done'}}]
        p.write_text('\n'.join(json.dumps(r) for r in rows))
        self.assertEqual(hooks._codex_final(str(p)), 'done')

    def test_writer_lock(self):
        with writecmd.Lock('x') as a:
            self.assertTrue(a.ok)
            with writecmd.Lock('x') as b: self.assertFalse(b.ok)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)}); self.env.start()

    def tearDown(self): self.env.stop(); self.tmp.cleanup()

    def test_claude_install_keeps_user_config_and_uninstall_restores(self):
        sp = self.home / '.claude' / 'settings.json'; sp.parent.mkdir()
        mine = {'model': 'opus', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'my-own-hook'}]}]}}
        sp.write_text(json.dumps(mine)); (self.home / '.claude.json').write_text(json.dumps({'mcpServers': {'other': {'command': 'x'}}}))
        install.claude(); install.claude()                                   # 重复安装不重复添加
        s = json.loads(sp.read_text()); m = json.loads((self.home / '.claude.json').read_text())
        self.assertEqual(s['model'], 'opus'); self.assertEqual(len(s['hooks']['Stop']), 2)
        self.assertIn('hook stop --agent claude', json.dumps(s, ensure_ascii=False)); self.assertIn('hyperthymesia', m['mcpServers']); self.assertIn('other', m['mcpServers'])
        self.assertTrue((self.home / '.claude' / 'settings.json.hyperthymesia.bak').exists())
        install.claude(remove=True)
        self.assertEqual(json.loads(sp.read_text()), mine)
        self.assertEqual(json.loads((self.home / '.claude.json').read_text()), {'mcpServers': {'other': {'command': 'x'}}})

    def test_codex_block_append_and_remove(self):
        cp = self.home / '.codex' / 'config.toml'; cp.parent.mkdir(); cp.write_text('model = "gpt-5.6-sol"\n')
        install.codex(); install.codex()
        t = cp.read_text(); self.assertEqual(t.count(install.MARK_BEGIN), 1); self.assertIn('[mcp_servers.hyperthymesia]', t); self.assertIn('[[hooks.Stop]]', t)
        install.codex(remove=True)
        self.assertEqual(cp.read_text(), 'model = "gpt-5.6-sol"\n')


if __name__ == '__main__':
    unittest.main()
