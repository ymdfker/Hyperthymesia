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

    def test_model_ranking_and_choice(self):
        from hyperthymesia import models
        ids = ['auto', 'hy4free', 'deepseek-v4-pro', 'glm-5.3', 'glm-5.3-flash', 'kimi-k3.1-pro', 'custom-local:x']
        self.assertEqual(models.rank(ids)[:2], ['hy4free', 'glm-5.3-flash'])          # 低价档在前，auto 与本地自定义不参与
        self.assertNotIn('auto', models.rank(ids))
        probes = {'hy4free': (False, 0.01), 'glm-5.3-flash': (True, 0.37), 'glm-5.3': (True, 0.9), 'deepseek-v4-pro': (True, 2.0)}
        with mock.patch.object(models, 'list_models', return_value=ids), mock.patch.object(models, '_probe', side_effect=lambda p, m: probes.get(m, (False, None))):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')                # 最便宜的没通过试探，选通过的里最便宜的
        with mock.patch.object(models, 'list_models', side_effect=AssertionError('不应重新识别')):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')                # 命中缓存
        models.forget('codebuddy')
        with mock.patch.object(models, 'list_models', return_value=['gpt-5.6-sol', 'gpt-6-luna', 'gpt-5.6-luna']), \
             mock.patch.object(models, '_probe', return_value=(True, None)):
            self.assertEqual(models.choose('codex'), 'gpt-6-luna')                      # 不报告消耗：按粗排取第一个通过的

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
