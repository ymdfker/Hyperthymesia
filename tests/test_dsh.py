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
