"""前台读取：快照（全文/增量/失效提示/压缩后重来）、目录模式、读取工具分页与去重、MCP 协议。"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from agent_memory import reader
from agent_memory.store import close_all, Store, state


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.u = Store(self.home / 'personal.db', 'u'); self.p = Store(self.home / 'proj.db', 'p'); self.st = state(self.home)
        self.cat = self.u.add_object('年糕')
        self.f1 = self.u.add_fact([self.cat], '年糕是英短，3岁')
        self.adv = self.u.add_fact([self.cat], '助手建议的猫粮储存方法：密封避光', kind='suggestion', source_role='assistant', title='猫粮储存建议')
        self.cfg = self.p.add_object('配置'); self.f2 = self.p.add_fact([self.cfg], '低库存阈值为10')
        self.stores = {'u': self.u, 'p': self.p}

    def tearDown(self): close_all(); self.tmp.cleanup()

    def test_snapshot_full_then_incremental_then_stale(self):
        c1 = reader.context(self.stores, self.st, 's1')
        self.assertIn('（长期记忆全文）', c1); self.assertIn('年糕是英短，3岁', c1); self.assertIn('低库存阈值为10', c1)
        self.assertIn('助手建议：猫粮储存建议', c1); self.assertNotIn('密封避光', c1)          # 建议只列标题
        self.assertIn('【个人 年糕 u%d】' % self.cat, c1); self.assertIn('【项目 配置 p%d】' % self.cfg, c1)
        self.assertEqual(reader.context(self.stores, self.st, 's1'), '')                     # 没变化不注入
        new = self.p.add_fact([self.cfg], '低库存阈值为12', supersedes=[self.f2])
        c3 = reader.context(self.stores, self.st, 's1')
        self.assertIn('低库存阈值为12', c3); self.assertIn('不再有效', c3); self.assertIn('低库存阈值为10', c3); self.assertNotIn('年糕', c3)
        self.assertEqual(reader.context(self.stores, self.st, 's1'), '')                     # 失效只提示一次
        self.assertIn('（长期记忆全文）', reader.context(self.stores, self.st, 's2'))         # 别的会话从全文开始
        reader.reset_session(self.st, 's1')
        self.assertIn('（长期记忆全文）', reader.context(self.stores, self.st, 's1'))         # 压缩后重新注入全文

    def test_advice_status_shown(self):
        self.u.set_advice_status(self.adv, 'basis_changed', '年糕改吃处方粮')
        self.assertIn('〔依据已变：年糕改吃处方粮〕', reader.context(self.stores))

    def test_directory_mode_when_large(self):
        c = reader.context(self.stores, self.st, 's1', limit=10)
        self.assertIn('年糕[u%d]' % self.cat, c); self.assertIn('配置[p%d]' % self.cfg, c); self.assertNotIn('英短', c)
        self.assertEqual(reader.context(self.stores, self.st, 's1', limit=10), '')

    def test_read_objects_paging_and_dedupe(self):
        for i in range(30): self.p.add_fact([self.cfg], '配置项%02d的取值说明比较长一些' % i)
        r1 = reader.read_objects(self.stores, ['p%d' % self.cfg, 'u%d' % self.cat], self.st, 'm1', cap=300)
        self.assertIn('已达返回上限', r1)
        r2 = reader.read_objects(self.stores, ['p%d' % self.cfg], self.st, 'm1', cap=100000)
        self.assertIn('本会话已返回过', r2); self.assertIn('配置项29', r2)                  # 被截掉的部分下次能读到
        self.assertIn('没有可读的对象ID', reader.read_objects(self.stores, ['s3']))

    def test_mcp_protocol_over_stdio(self):
        env = dict(os.environ, AGENT_MEMORY_HOME=str(self.home / 'h'), AGENT_MEMORY_CWD=str(self.home))
        root = Path(__file__).resolve().parents[1]
        reqs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'memory_read_objects', 'arguments': {'object_ids': ['u1']}}}]
        r = subprocess.run([sys.executable, '-m', 'agent_memory', 'serve'], input='\n'.join(json.dumps(x) for x in reqs) + '\n',
                           capture_output=True, text=True, encoding='utf-8', env=env, cwd=root, timeout=60)
        out = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertEqual([o['id'] for o in out], [1, 2, 3])
        self.assertEqual(out[0]['result']['protocolVersion'], '2025-06-18')
        self.assertTrue(out[1]['result']['tools'][0]['_meta']['anthropic/alwaysLoad'])
        self.assertIn('长期记忆', out[2]['result']['content'][0]['text'])


if __name__ == '__main__':
    unittest.main()
