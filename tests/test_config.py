"""写入器配置：TOML 子集解析、优先级、自动选择只挑命令行、key 只从指定环境变量读取。"""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock

from agent_memory import config, providers


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        clean = {k: v for k, v in os.environ.items() if not k.startswith('AGENT_MEMORY_')}
        clean['AGENT_MEMORY_HOME'] = str(self.home)
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
        with mock.patch.dict(os.environ, {'AGENT_MEMORY_PROVIDER': 'claude'}):
            s = config.writer_settings(); self.assertEqual((s['provider'], s['source']), ('claude', '环境变量'))

    def test_auto_select_only_cli_never_api(self):
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-x', 'DEEPSEEK_API_KEY': 'k'}), \
             mock.patch('shutil.which', side_effect=lambda n: '/bin/claude' if n == 'claude' else None), \
             mock.patch('agent_memory.install.codebuddy_exe', return_value=None):
            self.assertEqual(config.writer_settings()['provider'], 'claude')
        with mock.patch('shutil.which', return_value=None), mock.patch('agent_memory.install.codebuddy_exe', return_value=None):
            self.assertEqual(config.writer_settings()['provider'], '')

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
