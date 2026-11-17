"""写入器配置：TOML 子集解析、优先级、自动选择只挑命令行、key 只从指定环境变量读取。"""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import config, providers


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        clean = {k: v for k, v in os.environ.items() if not k.startswith('HYPERTHYMESIA_')}
        clean['HYPERTHYMESIA_HOME'] = str(self.home)
        self.env = mock.patch.dict(os.environ, clean, clear=True); self.env.start()

    def tearDown(self): self.env.stop(); self.tmp.cleanup()

    def cfg(self, text): (self.home / 'config.toml').write_text(text, encoding='utf-8')

    def test_parse_subset_without_tomllib(self):
        text = '# 注释\n[writer]\nprovider = "openai"   # 行尾注释\nmodel = "deepseek-chat"\nretries = 3\nstrict = true\n'
        with mock.patch.dict('sys.modules', {'tomllib': None}):
            d = config._parse_toml(text)
        self.assertEqual(d, {'writer': {'provider': 'openai', 'model': 'deepseek-chat', 'retries': 3, 'strict': True}})

    def test_env_overrides_file(self):
        self.cfg('[writer]\nprovider = "openai"\nmodel = "m1"\n')
        self.assertEqual(config.writer_settings()['provider'], 'openai')
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_PROVIDER': 'claude'}):
            s = config.writer_settings(); self.assertEqual((s['provider'], s['source']), ('claude', '环境变量'))

    def test_auto_select_only_cli_never_api(self):
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-x', 'DEEPSEEK_API_KEY': 'k'}), \
             mock.patch('shutil.which', side_effect=lambda n: '/bin/claude' if n == 'claude' else None), \
             mock.patch('hyperthymesia.install.codebuddy_exe', return_value=None):
            self.assertEqual(config.writer_settings()['provider'], 'claude')
        with mock.patch('shutil.which', return_value=None), mock.patch('hyperthymesia.install.codebuddy_exe', return_value=None):
            self.assertEqual(config.writer_settings()['provider'], '')

    def test_host_agent_selects_its_own_provider(self):
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOST_AGENT': 'codebuddy'}):
            s = config.writer_settings(); self.assertEqual((s['provider'], s['model']), ('codebuddy', ''))   # 模型不写死，留给自动识别
        self.cfg('[writer]\nprovider = "openai"\nmodel = "deepseek-chat"\n')    # 用户明确配置 API 时以配置为准
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOST_AGENT': 'codebuddy'}):
            self.assertEqual(config.writer_settings()['provider'], 'openai')

    def test_trae_host_never_borrows_other_agents(self):
        # Trae 暂不支持自身额度写入：即使本机装了别家命令行也不借用，只认用户配置的 API
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOST_AGENT': 'trae'}), mock.patch('shutil.which', return_value='/bin/x'):
            self.assertEqual(config.writer_settings()['provider'], '')
        self.cfg('[writer]\nprovider = "openai"\nmodel = "deepseek-chat"\n')
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOST_AGENT': 'trae'}):
            self.assertEqual(config.writer_settings()['provider'], 'openai')

    def test_model_choice_by_host_price(self):
        from hyperthymesia import models
        ids = ['auto', 'deepseek-v4-pro', 'glm-5.3', 'glm-5.3-flash', 'space-bunny', 'custom-local:x']
        price = {'deepseek-v4-pro': 0.6, 'glm-5.3': 0.69, 'glm-5.3-flash': 0.08, 'space-bunny': 0.06}
        probed = []
        def probe(p, m): probed.append(m); return {'ok': m != 'space-bunny'}          # 最便宜的没通过能力试探
        with mock.patch.object(models, 'acceptance', return_value=[]), mock.patch.object(models, 'list_models', return_value=ids), mock.patch.object(models, 'codebuddy_prices', return_value=price), \
             mock.patch.object(models, '_probe', side_effect=probe):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')    # 按价格依次试探，取第一个通过的
        self.assertEqual(probed, ['space-bunny', 'glm-5.3-flash'])            # 只试探到通过为止，不碰贵模型
        with mock.patch.object(models, 'acceptance', return_value=[]), mock.patch.object(models, 'list_models', return_value=ids), mock.patch.object(models, 'codebuddy_prices', side_effect=AssertionError('命中缓存')):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')
        with mock.patch.object(models, 'acceptance', return_value=[]), mock.patch.object(models, 'list_models', return_value=ids + ['new-model']), mock.patch.object(models, 'codebuddy_prices', return_value=dict(price, **{'new-model': 0.01})), \
             mock.patch.object(models, '_probe', return_value={'ok': True}):
            self.assertEqual(models.choose('codebuddy'), 'new-model')         # 模型列表变化：重新识别

    def test_missing_qoder_price_never_calls_model_to_measure(self):
        from hyperthymesia import models
        with mock.patch.object(models, 'qoder_doc_prices', return_value={}), mock.patch.object(models, 'measure', side_effect=AssertionError('不能自动耗额度测价')):
            got, source = models.prices('qoder', ['A', 'B'], {'A': .02, 'gone': 1})
        self.assertEqual(got, {'A': .02})

    def test_codebuddy_prices_from_local_cache(self):
        from hyperthymesia import models
        d = self.home / 'cb' / '.codebuddy' / 'local_storage'; d.mkdir(parents=True)
        (d / 'entry_x.info').write_text('{"data":{"models":[{"id":"hy4free","credits":"x0.00"},{"id":"glm-5.3-flash","credits":"x0.08"}]}}TRAILER', encoding='utf-8')
        with mock.patch('pathlib.Path.home', return_value=self.home / 'cb'):
            self.assertEqual(models.codebuddy_prices(), {'hy4free': 0.0, 'glm-5.3-flash': 0.08})

    def test_codebuddy_prices_follow_desktop_config_directory(self):
        from hyperthymesia import models
        directory = self.home / 'desktop'; (directory / 'local_storage').mkdir(parents=True)
        (directory / 'local_storage' / 'entry_x.info').write_text('{"data":{"models":[{"id":"desktop-model","credits":"x0.08"}]}}')
        with mock.patch.dict(os.environ, {'CODEBUDDY_CONFIG_DIR': str(directory)}):
            self.assertEqual(models.codebuddy_prices(), {'desktop-model': 0.08})

    def test_workbuddy_doctor_uses_desktop_model_directory(self):
        from hyperthymesia.__main__ import _doctor
        import io
        directory = self.home / 'desktop'
        def explain(provider):
            self.assertEqual(provider, 'codebuddy')
            self.assertEqual(os.environ['CODEBUDDY_CONFIG_DIR'], str(directory))
            return '本地配置检查'
        with mock.patch.dict(os.environ, {'WORKBUDDY_CONFIG_DIR': str(directory)}), mock.patch('hyperthymesia.models.explain', side_effect=explain), mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(_doctor(['--agent', 'workbuddy']), 0)

    def test_unknown_usage_does_not_fail_quality_passed_model(self):
        from hyperthymesia import models
        row = {'quality_pass': True, 'seconds': 19.984, 'input_tokens': 0, 'output_tokens': 0, 'cost': .0095}
        self.assertTrue(models._acceptable(row))
        self.assertIn('未知', models._screen(row)[2][0])
        self.assertFalse(models._acceptable(dict(row, quality_pass=False)))
        self.assertFalse(models._acceptable(dict(row, input_tokens=10, output_tokens=100)))
        self.assertFalse(models._acceptable(dict(row, seconds=121)))

    def test_probe_accepts_split_suggestions_and_equivalent_fixed_answers(self):
        from hyperthymesia import models
        got = {'facts': {'timeout': '60 s', 'condition': '只在工作日开启', 'reviewer': 'Priya', 'release': '每星期四发布'},
               'suggestions': ['失败先保留现场', '然后检查日志']}
        self.assertEqual(models._probe_quality(got), (True, []))
        got['suggestions'].append('可以帮忙写通知')
        self.assertFalse(models._probe_quality(got)[0])
        got['suggestions'].pop(); got['facts']['timeout'] = '45秒'
        self.assertFalse(models._probe_quality(got)[0])

    def test_probe_records_redacted_reply_and_unknown_usage(self):
        from hyperthymesia import models
        from types import SimpleNamespace
        import json
        secret = 'sk-proj-' + 'A' * 30
        text = json.dumps({'facts': {'timeout': '60秒', 'condition': '仅工作日启用', 'reviewer': 'Priya', 'release': '每周四发布'},
                           'suggestions': ['先保留现场', '再检查日志'], 'debug': secret}, ensure_ascii=False)
        reply = SimpleNamespace(text=text, usage={'input_tokens': 0, 'output_tokens': 0, 'cost': .0123})
        with mock.patch.object(providers, 'call', return_value=reply):
            row = models._probe('qoder', 'example-model')
        self.assertTrue(row['ok']); self.assertEqual(row['usage_status'], 'unknown')
        self.assertEqual(row['cost'], .0123)
        log = (self.home / 'logs/models.log').read_text(encoding='utf-8')
        self.assertNotIn(secret, log); self.assertIn('example-model', log)
        self.assertIn('reply', json.loads(log))

    def test_old_quality_pass_with_unknown_usage_reused_without_probe(self):
        from hyperthymesia import models
        import time
        models._save({'qoder': {'at': time.time(), 'selection_version': 2, 'model': '', 'checked': [
            {'model': 'Efficient', 'quality_pass': True, 'seconds': 19.984, 'input_tokens': 0, 'output_tokens': 0, 'ok': False}]}})
        with mock.patch.object(models, 'acceptance', return_value=[]), mock.patch.object(models, 'list_models', return_value=['Efficient']), \
             mock.patch.object(models, 'prices', return_value=({'Efficient': .1}, 'local')), \
             mock.patch.object(models, '_probe', side_effect=AssertionError('不应再次收费准入')):
            self.assertEqual(models.choose('qoder'), 'Efficient')
        self.assertIn('token用量未知', models.explain('qoder'))

    def test_doctor_check_cli_never_probes_or_mutates_model_cache(self):
        from hyperthymesia import models
        from hyperthymesia.__main__ import _doctor
        import io, subprocess
        self.cfg('[writer]\nprovider="qoder"\n')
        models._save({'qoder': {'model': 'existing', 'selection_version': models.SELECTION_VERSION}})
        before = (self.home / 'models.json').read_bytes()
        with mock.patch.object(providers, 'qodercli_cmd', return_value=['node', 'qoder.js']), \
             mock.patch.object(providers, '_run_cli', return_value=subprocess.CompletedProcess([], 0, stdout='1.1.80', stderr='')) as cli, \
             mock.patch.object(providers, 'call', side_effect=AssertionError('doctor不能调用模型')), \
             mock.patch.object(models, 'choose', side_effect=AssertionError('doctor不能选模')), \
             mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(_doctor(['--agent', 'workbuddy', '--check-cli']), 0)
        self.assertEqual(cli.call_args.args[0], ['node', 'qoder.js', '--version'])
        self.assertEqual((self.home / 'models.json').read_bytes(), before)

    def test_api_key_from_named_env_only(self):
        self.cfg('[writer]\nprovider = "openai"\nmodel = "deepseek-chat"\nbase_url = "https://api.deepseek.com/v1"\napi_key_env = "DEEPSEEK_API_KEY"\n')
        s = config.writer_settings()
        self.assertEqual(config.api_key(s), (None, 'DEEPSEEK_API_KEY'))
        with self.assertRaises(providers.ProviderError): providers._openai(self.home, 'r', 'p', None, [])
        with mock.patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'secret-value'}):
            self.assertEqual(config.api_key(s), ('secret-value', 'DEEPSEEK_API_KEY'))
        self.assertFalse(any('secret-value' in p.read_text(encoding='utf-8', errors='ignore') for p in self.home.rglob('*') if p.is_file()))


if __name__ == '__main__':
    unittest.main()
