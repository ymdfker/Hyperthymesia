"""钩子流程、会话记录解析、后台写入命令、安装/卸载（全部在临时目录，不碰真实配置，不调用模型）。"""
import io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import hooks, install, paths, providers, writecmd
from hyperthymesia.store import close_all, Store, state


class HookFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOME': str(self.root / 'home'), 'HYPERTHYMESIA_PROVIDER': 'fake',
                                                'HYPERTHYMESIA_BACKLOG_TOKENS': '100000'}); self.env.start()
        self.proj = self.root / 'proj'; self.proj.mkdir(); (self.proj / 'config.py').write_text('PAGE = 10\n', encoding='utf-8')
        providers.FAKE_REPLIES.clear()
        self.spawn = mock.patch.object(hooks, 'spawn_writer'); self.spawned = self.spawn.start()   # 测试里不真的拉起后台写入

    def tearDown(self): self.spawn.stop(); self.env.stop(); close_all(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

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
        p.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8'); return str(p)

    def test_turn_backlog_changes_and_write(self):
        d = {'session_id': 's1', 'cwd': str(self.proj), 'prompt': '默认分页改成20，你直接改。'}
        self.assertEqual(self.call('prompt-submit', d), {})                     # 库还是空的：不注入
        (self.proj / 'config.py').write_text('PAGE = 20\n', encoding='utf-8')
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

    def test_reinject_when_host_does_not_keep_injected_context(self):
        pdb, _ = paths.project_db(self.proj); st = Store(pdb, 'p'); o = st.add_object('配置'); st.add_fact([o], '默认分页大小为50')
        tr = self.root / 'host.jsonl'; tr.write_text(json.dumps({'type': 'message', 'role': 'user', 'content': '问'}), encoding='utf-8')
        d = {'session_id': 'r1', 'cwd': str(self.proj), 'prompt': '分页？', 'transcript_path': str(tr)}
        self.assertIn('默认分页大小为50', self.call('prompt-submit', d)['hookSpecificOutput']['additionalContext'])
        # 会话记录里没有存下注入内容（CodeBuddy 的情况）：下一轮仍注入全文
        self.assertIn('默认分页大小为50', self.call('prompt-submit', dict(d, prompt='再问'))['hookSpecificOutput']['additionalContext'])
        # 会话记录里有注入内容（Claude Code 的情况）：没有变化就不重复注入
        tr.write_text(tr.read_text(encoding='utf-8') + '\n' + json.dumps({'attachment': '（长期记忆全文）……'}, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(self.call('prompt-submit', dict(d, prompt='第三问')), {})

    def test_hook_never_breaks_host(self):
        with mock.patch('sys.stdin', io.StringIO('not json')), mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(hooks.run(['stop']), 0)
        self.assertEqual(out.getvalue(), '{}')
        self.assertIn('hook_error', (paths.home() / 'logs' / 'hooks.log').read_text(encoding='utf-8'))

    def test_codex_final_reply(self):
        p = self.root / 'rollout.jsonl'
        rows = [{'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '我先看看文件'}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'done'}}]
        p.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        self.assertEqual(hooks._codex_final(str(p)), 'done')

    def test_codebuddy_stop_uses_last_assistant_message(self):
        d = {'session_id': 'c1', 'cwd': str(self.proj), 'prompt': '分页改成30'}
        self.call('prompt-submit', d, agent='codebuddy')
        self.call('stop', {'session_id': 'c1', 'cwd': str(self.proj), 'last_assistant_message': '已改为30', 'transcript_path': '/不存在'}, agent='codebuddy')
        r = state(paths.home()).execute("SELECT assistant_text FROM backlog WHERE session='c1'").fetchone()
        self.assertEqual(r[0], '已改为30')
        p = self.root / 'cb.jsonl'
        p.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in [
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '问'}]},
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '答'}]}]), encoding='utf-8')
        self.assertEqual(hooks._codebuddy_final(str(p)), '答')

    def test_writer_lock(self):
        with writecmd.Lock('x') as a:
            self.assertTrue(a.ok)
            with writecmd.Lock('x') as b: self.assertFalse(b.ok)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)}); self.env.start()

    def tearDown(self): self.env.stop(); close_all(); self.tmp.cleanup()

    def test_claude_install_keeps_user_config_and_uninstall_restores(self):
        sp = self.home / '.claude' / 'settings.json'; sp.parent.mkdir()
        mine = {'model': 'opus', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'my-own-hook'}]}]}}
        sp.write_text(json.dumps(mine), encoding='utf-8'); (self.home / '.claude.json').write_text(json.dumps({'mcpServers': {'other': {'command': 'x'}}}), encoding='utf-8')
        install.claude(); install.claude()                                   # 重复安装不重复添加
        s = json.loads(sp.read_text(encoding='utf-8')); m = json.loads((self.home / '.claude.json').read_text(encoding='utf-8'))
        self.assertEqual(s['model'], 'opus'); self.assertEqual(len(s['hooks']['Stop']), 2)
        self.assertIn('hook stop --agent claude', json.dumps(s, ensure_ascii=False)); self.assertIn('hyperthymesia', m['mcpServers']); self.assertIn('other', m['mcpServers'])
        self.assertTrue((self.home / '.claude' / 'settings.json.hyperthymesia.bak').exists())
        install.claude(remove=True)
        self.assertEqual(json.loads(sp.read_text(encoding='utf-8')), mine)
        self.assertEqual(json.loads((self.home / '.claude.json').read_text(encoding='utf-8')), {'mcpServers': {'other': {'command': 'x'}}})

    def test_codebuddy_project_install(self):
        proj = self.home / 'p'; proj.mkdir()
        install.codebuddy(str(proj))
        s = json.loads((proj / '.codebuddy' / 'settings.local.json').read_text(encoding='utf-8'))
        self.assertIn('--agent codebuddy', json.dumps(s)); self.assertIn('hyperthymesia', json.loads((proj / '.mcp.json').read_text(encoding='utf-8'))['mcpServers'])
        install.codebuddy(str(proj), remove=True)
        self.assertEqual(json.loads((proj / '.codebuddy' / 'settings.local.json').read_text(encoding='utf-8')), {})

    def test_qoder_install_and_restore(self):
        sp = self.home / '.qoder' / 'settings.json'; sp.parent.mkdir()
        mine = {'enabledPlugins': {'x': True}}; sp.write_text(json.dumps(mine), encoding='utf-8')
        (self.home / '.qoder' / 'mcp.json').write_text(json.dumps({'mcpServers': {}}), encoding='utf-8')
        install.qoder()
        self.assertIn('--agent qoder', json.dumps(json.loads(sp.read_text(encoding='utf-8'))))
        self.assertIn('hyperthymesia', json.loads((self.home / '.qoder' / 'mcp.json').read_text(encoding='utf-8'))['mcpServers'])
        install.qoder(remove=True)
        self.assertEqual(json.loads(sp.read_text(encoding='utf-8')), mine)

    def test_codex_block_append_and_remove(self):
        cp = self.home / '.codex' / 'config.toml'; cp.parent.mkdir(); cp.write_text('model = "gpt-5.6-sol"\n', encoding='utf-8')
        install.codex(); install.codex()
        t = cp.read_text(encoding='utf-8'); self.assertEqual(t.count(install.MARK_BEGIN), 1); self.assertIn('[mcp_servers.hyperthymesia]', t); self.assertIn('[[hooks.Stop]]', t)
        install.codex(remove=True)
        self.assertEqual(cp.read_text(encoding='utf-8'), 'model = "gpt-5.6-sol"\n')


if __name__ == '__main__':
    unittest.main()
