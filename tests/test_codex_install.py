"""Codex 安装：原型 §22/§23.37 实测的读取配置（直连 + 返回上限 262144），顶层键位置正确、可重复安装、卸载干净。"""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import install


class CodexInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        (self.home / '.codex').mkdir(); self.cp = self.home / '.codex' / 'config.toml'
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)}); self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_limits_written_top_level_idempotent_and_removed(self):
        self.cp.write_text('model = "x"\n\n[profiles.a]\nm = 1\n', encoding='utf-8')
        install.codex(); install.codex()
        t = self.cp.read_text(encoding='utf-8')
        self.assertEqual(t.count('tool_output_token_limit = 262144'), 1)
        self.assertLess(t.index('tool_output_token_limit'), t.index('[profiles.a]'))   # 顶层键在所有表之前
        self.assertIn('[mcp_servers.hyperthymesia.tools.memory_read_objects]\noutput_token_limit = 262144', t)
        self.assertIn('direct_only_tool_namespaces = ["mcp__hyperthymesia"]', t)
        install.codex(remove=True)
        self.assertEqual(self.cp.read_text(encoding='utf-8'), 'model = "x"\n\n[profiles.a]\nm = 1\n')

    def test_user_limit_kept(self):
        self.cp.write_text('tool_output_token_limit = 50000\n', encoding='utf-8')
        install.codex()
        t = self.cp.read_text(encoding='utf-8')
        self.assertEqual(t.count('tool_output_token_limit'), 1); self.assertIn('= 50000', t)


if __name__ == '__main__':
    unittest.main()
