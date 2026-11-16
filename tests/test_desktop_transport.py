"""Regressions for reported Windows failures; generated fixtures, no live model or account."""
import io,json,os,pathlib,shutil,subprocess,sys,tempfile,unittest
from unittest import mock
from hyperthymesia import hooks,install,launch,paths,providers,writecmd,writer
from hyperthymesia.store import close_all,state

class DesktopTransportTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        env={k:v for k,v in os.environ.items() if not k.startswith('HYPERTHYMESIA_')}
        env.update(HYPERTHYMESIA_HOME=str(self.root/'memory'),HYPERTHYMESIA_PROVIDER='fake',HOME=str(self.root/'user'),USERPROFILE=str(self.root/'user'))
        (self.root/'user').mkdir();self.env=mock.patch.dict(os.environ,env,clear=True);self.env.start();providers.FAKE_REPLIES.clear()
    def tearDown(self):
        providers.FAKE_REPLIES.clear();close_all();self.env.stop();self.tmp.cleanup()
    def hook(self,event,data):
        with mock.patch('sys.stdin',io.StringIO('\ufeff'+json.dumps(data,ensure_ascii=False))),mock.patch('sys.stdout',new_callable=io.StringIO),mock.patch.object(hooks,'spawn_writer') as spawn:
            hooks.run([event,'--agent','codebuddy']);return spawn
    def test_qoder_mcp_migration_preserves_other_entries_and_bom(self):
        directory=self.root/'user/.qoder';directory.mkdir()
        settings={'custom':True,'mcpServers':{'other':{'command':'other'}}}
        old={'mcpServers':{'hyperthymesia':{'command':'old'},'legacy-other':{'command':'other'}}}
        (directory/'settings.json').write_text(json.dumps(settings),encoding='utf-8-sig');(directory/'mcp.json').write_text(json.dumps(old))
        install.qoder();now=json.loads((directory/'settings.json').read_text())
        self.assertIn('hyperthymesia',now['mcpServers']);self.assertIn('other',now['mcpServers'])
        self.assertNotIn('hyperthymesia',json.loads((directory/'mcp.json').read_text())['mcpServers'])
        self.assertEqual(json.loads((directory/'mcp.json.hyperthymesia.bak').read_text()),old)
        install.qoder(remove=True);self.assertEqual(json.loads((directory/'settings.json').read_text()),settings)
    def test_multiline_arguments_bypass_windows_shim(self):
        node=shutil.which('node')
        if not node:
            if sys.platform=='win32':self.fail('Windows transport regression requires Node.js')
            self.skipTest('Node not on PATH')
        prefix=self.root/'npm space 中文';package=prefix/'node_modules/@qoder-ai/qodercli';package.mkdir(parents=True)
        (package/'package.json').write_text(json.dumps({'bin':{'qodercli':'entry.js'}}))
        (package/'entry.js').write_text('console.log(JSON.stringify({args:process.argv.slice(2),internal:process.env.HYPERTHYMESIA_INTERNAL_CALL,sdk:process.env.QODER_AGENT_SDK_ENTRYPOINT}));')
        shim=prefix/'qodercli.CMD';shim.write_text('@echo off\r\n')
        with mock.patch.object(launch,'WINDOWS',True):cmd=launch.command(str(shim),'@qoder-ai/qodercli','qodercli')
        self.assertEqual(pathlib.Path(cmd[1]).resolve(),(package/'entry.js').resolve())
        args=['--system-prompt','第一段\n\n规则：只能返回JSON；不要执行 $(echo x) & echo y','--model','model-x','--resume','session-x']
        env=dict(os.environ,QODER_AGENT_SDK_ENTRYPOINT='1',QODER_AGENT_SDK_DAEMON='1')
        rep=providers._run_cli(cmd+args,agent='qoder',env=env,capture_output=True,text=True,encoding='utf-8',check=True)
        out=json.loads(rep.stdout);self.assertEqual(out['args'],args);self.assertEqual(out['internal'],'1');self.assertNotIn('sdk',out)
    def test_sdk_cleanup_preserves_auth_and_parent_environment(self):
        original={'PATH':'unchanged','QODER_AGENT_SDK_ENTRYPOINT':'1','QODER_AGENT_SDK_DAEMON':'1','QODER_AGENT_SDK_VERSION':'1','QODER_SDK_AUTH_PAYLOAD_FILE':'existing-auth-location'}
        cleaned=launch.environment('qoder',[],original)
        self.assertNotIn('QODER_AGENT_SDK_ENTRYPOINT',cleaned);self.assertEqual(cleaned['QODER_SDK_AUTH_PAYLOAD_FILE'],original['QODER_SDK_AUTH_PAYLOAD_FILE']);self.assertIn('QODER_AGENT_SDK_ENTRYPOINT',original)
    def test_workbuddy_nondefault_lite_install(self):
        base=self.root/'F drive WorkBuddy';entry=base/'resources/app.asar.unpacked/cli/bin/codebuddy';entry.parent.mkdir(parents=True);entry.write_text('#!/usr/bin/env node\n')
        dist=entry.parent.parent/'dist';dist.mkdir();(dist/'codebuddy-lite-wb.mjs').write_text('')
        with mock.patch.dict(os.environ,{'WORKBUDDY_INSTALL_DIR':str(base)}),mock.patch.object(launch,'WINDOWS',True),mock.patch.object(launch,'_windows_workbuddy_roots',return_value=[]):
            self.assertEqual(launch.find_codebuddy(),str(entry))
        self.assertEqual(launch.environment('codebuddy',[str(entry)],{})['CODEBUDDY_FORCE_LITE_WB_BUNDLE'],'1')
    def test_authentication_failure_with_zero_exit_code_is_failure(self):
        result=subprocess.CompletedProcess([],0,json.dumps({'result':'Authentication required. Please use /login command','is_error':False}),'')
        with self.assertRaisesRegex(providers.ProviderError,'鉴权'):providers._result_object(result,'codebuddy')
    def test_unknown_write_schema_does_not_acknowledge_batch(self):
        self.hook('prompt-submit',{'session_id':'s','prompt':'接口超时45秒'});self.hook('stop',{'session_id':'s','last_assistant_message':'好的'})
        providers.FAKE_REPLIES.append('{"objects":[],"records":[{"text":"接口超时45秒"}]}')
        project=state(paths.home()).execute('SELECT project FROM backlog').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError,'原材料|材料|积压'):writecmd.write_project(project)
        self.assertEqual(state(paths.home()).execute('SELECT written FROM backlog').fetchone()[0],0)
    def test_native_lock_released_after_process_kill(self):
        code='from hyperthymesia.writecmd import Lock\nimport sys\nwith Lock("dead-child") as lock:\n print("ready" if lock.ok else "blocked",flush=True)\n sys.stdin.read()\n'
        child=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            with writecmd.Lock('dead-child') as other:self.assertFalse(other.ok)
            child.kill();child.wait(timeout=10)
            with writecmd.Lock('dead-child') as other:self.assertTrue(other.ok)
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=10)
            for stream in (child.stdin,child.stdout,child.stderr):stream.close()
    def test_prompts_without_stop_remain_separate_and_host_id_is_idempotent(self):
        self.hook('prompt-submit',{'session_id':'s','prompt':'first','turn_id':'one'})
        self.hook('prompt-submit',{'session_id':'s','prompt':'second','turn_id':'two'})
        self.hook('prompt-submit',{'session_id':'s','prompt':'changed duplicate','turn_id':'one'})
        rows=state(paths.home()).execute('SELECT user_text,completed_at FROM backlog ORDER BY turn').fetchall()
        self.assertEqual([r[0] for r in rows],['first','second']);self.assertTrue(all(r[1] is None for r in rows))
    def test_concurrent_prompt_callbacks_never_replace_existing_turns(self):
        state(paths.home())  # initialize schema before concurrent callbacks
        processes=[]
        for i in range(3):
            proc=subprocess.Popen([sys.executable,'-m','hyperthymesia','hook','prompt-submit','--agent','codebuddy'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            proc.stdin.write(json.dumps({'session_id':'parallel','prompt':'message-'+str(i),'turn_id':str(i)}));proc.stdin.close();processes.append(proc)
        for proc in processes:
            proc.wait(timeout=20)
            self.assertEqual(proc.returncode,0)
            proc.stdout.close();proc.stderr.close()
        rows=state(paths.home()).execute("SELECT user_text FROM backlog WHERE session='parallel'").fetchall()
        self.assertEqual({r[0] for r in rows},{'message-0','message-1','message-2'})

    def test_restore_only_explicitly_completed_unique_transcript_turn(self):
        transcript=self.root/'transcript.jsonl';data={'session_id':'s','prompt':'接口超时45秒','transcript_path':str(transcript)}
        self.hook('prompt-submit',data)
        def record(status):
            transcript.write_text('\n'.join(json.dumps(e,ensure_ascii=False) for e in [{'type':'message','role':'user','content':'接口超时45秒'},{'type':'message','role':'assistant','status':status,'content':'已确认45秒'}]),encoding='utf-8-sig')
        record('running');self.hook('session-start',{'session_id':'s','transcript_path':str(transcript)})
        self.assertIsNone(state(paths.home()).execute('SELECT completed_at FROM backlog').fetchone()[0])
        record('completed');spawn=self.hook('session-start',{'session_id':'s','transcript_path':str(transcript)})
        self.assertEqual(state(paths.home()).execute('SELECT assistant_text FROM backlog').fetchone()[0],'已确认45秒');spawn.assert_called_once()
    def test_internal_hooks_skip_without_creating_store(self):
        with mock.patch.dict(os.environ,{'HYPERTHYMESIA_INTERNAL_CALL':'1'}):self.hook('prompt-submit',{'session_id':'internal','prompt':'must not record'})
        self.assertFalse((self.root/'memory/state.db').exists())
