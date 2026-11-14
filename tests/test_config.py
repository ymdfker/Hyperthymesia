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
        def probe(p, m): probed.append(m); return m != 'space-bunny'          # 最便宜的没通过能力试探
        with mock.patch.object(models, 'list_models', return_value=ids), mock.patch.object(models, 'codebuddy_prices', return_value=price), \
             mock.patch.object(models, '_probe', side_effect=probe):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')    # 按价格依次试探，取第一个通过的
        self.assertEqual(probed, ['space-bunny', 'glm-5.3-flash'])            # 只试探到通过为止，不碰贵模型
        with mock.patch.object(models, 'list_models', return_value=ids), mock.patch.object(models, 'codebuddy_prices', side_effect=AssertionError('命中缓存')):
            self.assertEqual(models.choose('codebuddy'), 'glm-5.3-flash')
        with mock.patch.object(models, 'list_models', return_value=ids + ['new-model']), mock.patch.object(models, 'codebuddy_prices', return_value=dict(price, **{'new-model': 0.01})), \
             mock.patch.object(models, '_probe', return_value=True):
            self.assertEqual(models.choose('codebuddy'), 'new-model')         # 模型列表变化：重新识别

    def test_measured_prices_only_for_new_models(self):
        from hyperthymesia import models
        measured = []
        def measure(p, m): measured.append(m); return {'A': 0.02, 'B': 0.005, 'C': 0.5}[m]
        with mock.patch.object(models, 'list_models', return_value=['A', 'B']), mock.patch.object(models, 'measure', side_effect=measure), \
             mock.patch.object(models, '_probe', return_value=True):
            self.assertEqual(models.choose('qoder'), 'B')
        with mock.patch.object(models, 'list_models', return_value=['A', 'B', 'C']), mock.patch.object(models, 'measure', side_effect=measure), \
             mock.patch.object(models, '_probe', return_value=True):
            self.assertEqual(models.choose('qoder'), 'B')
        self.assertEqual(measured, ['A', 'B', 'C'])                          # 第二次只补测新出现的 C

    def test_codebuddy_prices_from_local_cache(self):
        from hyperthymesia import models
        d = self.home / 'cb' / '.codebuddy' / 'local_storage'; d.mkdir(parents=True)
        (d / 'entry_x.info').write_text('{"data":{"models":[{"id":"hy4free","credits":"x0.00"},{"id":"glm-5.3-flash","credits":"x0.08"}]}}TRAILER', encoding='utf-8')
        with mock.patch('pathlib.Path.home', return_value=self.home / 'cb'):
            self.assertEqual(models.codebuddy_prices(), {'hy4free': 0.0, 'glm-5.3-flash': 0.08})

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
