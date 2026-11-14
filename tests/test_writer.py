"""写入器：用 fake 提供方（预设回答）验证程序侧逻辑，不调用任何模型。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from agent_memory import providers, writer
from agent_memory.store import Store, state


def J(**kw): return json.dumps(kw, ensure_ascii=False)


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'AGENT_MEMORY_PROVIDER': 'fake'}); self.env.start()
        self.u = Store(self.home / 'personal.db', 'u'); self.p = Store(self.home / 'p.db', 'p')
        providers.FAKE_REPLIES.clear()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

    def turns(self, *pairs):
        return [{'session': 's1', 'turn': i, 'user': u, 'assistant': a, 'at': '2026-11-14'} for i, (u, a) in enumerate(pairs, 1)]

    def run_batch(self, turns, *replies, stores=None):
        providers.FAKE_REPLIES.extend(replies)
        return writer.write_batch(self.home, stores or {'u': self.u, 'p': self.p}, turns, state(self.home))

    def test_scopes_evidence_and_roles(self):
        t = self.turns(('我女儿朵朵上二年级。项目里低库存阈值定成10。', '好的，阈值已改为10。建议加单元测试。'))
        main = J(objects=[{'key': 'k1', 'name': '朵朵', 'purpose': '女儿', 'scope': 'personal', 'parents': []},
                          {'key': 'k2', 'name': '库存', 'purpose': '库存配置', 'scope': 'project', 'parents': []}],
                 memories=[{'title': '朵朵年级', 'text': '女儿朵朵上二年级', 'kind': 'fact', 'about': ['k1'], 'evidence': ['朵朵上二年级'], 'invalidates': []},
                           {'title': '阈值', 'text': '低库存阈值为10', 'kind': 'fact', 'about': ['k2'], 'evidence': ['低库存阈值定成10'], 'invalidates': []},
                           {'title': '测试建议', 'text': '助手建议加单元测试', 'kind': 'suggestion', 'about': ['k2'], 'evidence': ['建议加单元测试'], 'invalidates': []}])
        r = self.run_batch(t, main)
        uf = self.u.facts(); pf = self.p.facts()
        self.assertEqual([f['text'] for f in uf], ['女儿朵朵上二年级'])
        self.assertEqual(sorted(f['text'] for f in pf), ['低库存阈值为10', '助手建议加单元测试'])
        self.assertEqual({f['text']: f['source_role'] for f in pf}['助手建议加单元测试'], 'assistant')
        self.assertEqual(r['calls'], 1)   # 用户原话已被引用：无缺口补写；只有新对象内的两条事实：无冲突

    def test_correction_supersedes_and_readonly_advice(self):
        o = self.p.add_object('文三路店')
        old = self.p.add_fact([o], '每周三闭店', evidence=[('s0:1:u', '每周三闭店')])
        adv = self.p.add_fact([o], '助手建议周三做盘点', kind='suggestion', source_role='assistant')
        t = self.turns(('文三路店以后改成周四闭店。', '收到。'))
        main = J(memories=[{'title': '闭店日', 'text': '文三路店每周四闭店', 'kind': 'fact', 'about': ['p%d' % o],
                            'evidence': ['改成周四闭店'], 'invalidates': ['rp%d' % old, 'rp%d' % adv]}])
        self.run_batch(t, main, J(replacements=[]))
        self.assertFalse(self.p.fact(old)['active'])
        self.assertTrue(self.p.fact(adv)['active']); self.assertIn('basis_changed', self.p.fact(adv)['advice_status'])

    def test_ref_typo_fixed_and_unmatched_quote_asked_then_dropped(self):
        o = self.p.add_object('滨江店'); old = self.p.add_fact([o], '员工8人', evidence=[('s0:1:u', '8人')])
        t = self.turns(('滨江店现在10个员工了。', '好的。'))
        bad = 'rp%d' % old + 'x'   # 多一个字：编辑距离 1，可纠正
        main = J(memories=[{'title': '员工', 'text': '滨江店员工10人', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['滨江店现在10个员工'], 'invalidates': [bad]},
                           {'title': '编造', 'text': '店长换人了', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['店长已经换成老王'], 'invalidates': []}])
        r = self.run_batch(t, main, J(quotes=['还是对不上的引用']), J(replacements=[]))
        texts = [f['text'] for f in self.p.facts()]
        self.assertIn('滨江店员工10人', texts); self.assertNotIn('员工8人', texts); self.assertNotIn('店长换人了', texts)
        steps = [x['step'] for x in r['log']]
        self.assertIn('ref_fixed', steps); self.assertIn('ask_quotes', steps); self.assertIn('dropped_unsourced', steps)

    def test_need_objects_delta_merge_keeps_first_answer(self):
        o = self.p.add_object('良渚店')
        for i in range(300): self.p.add_fact([o], '良渚店历史事实%d：' % i + '很长的说明文字' * 3)   # 超过全量附带上限 -> 预选
        other = self.p.add_object('年糕'); self.p.add_fact([other], '年糕3岁')
        t = self.turns(('良渚店开业改到3月22日，猫粮又买了两袋。', '好的。'))
        first = J(memories=[{'title': '开业', 'text': '良渚店3月22日开业', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['开业改到3月22日'], 'invalidates': []}],
                  need_objects=['p%d' % other])
        delta = J(memories=[{'title': '猫粮', 'text': '又买了两袋猫粮', 'kind': 'fact', 'about': ['p%d' % other], 'evidence': ['猫粮又买了两袋'], 'invalidates': []}])
        r = self.run_batch(t, first, delta, J(replacements=[]))
        texts = [f['text'] for f in self.p.facts()]
        self.assertIn('良渚店3月22日开业', texts); self.assertIn('又买了两袋猫粮', texts)   # 增量合并：第一次的内容没丢
        self.assertIn('need_objects', [x['step'] for x in r['log']])

    def test_gap_fill_for_uncited_user_turn(self):
        t = self.turns(('车险5月20日到期，帮我写个自驾清单。', '清单如下……'))
        main = J(objects=[{'key': 'k', 'name': '自驾', 'scope': 'personal', 'parents': []}],
                 memories=[{'title': '清单', 'text': '助手建议自驾前检查胎压', 'kind': 'suggestion', 'about': ['k'], 'evidence': ['清单如下'], 'invalidates': []}])
        gap = J(objects=[{'key': 'c', 'name': '车险', 'scope': 'personal', 'parents': []}],
                memories=[{'title': '车险到期', 'text': '车险5月20日到期', 'kind': 'fact', 'about': ['c'], 'evidence': ['车险5月20日到期'], 'invalidates': []}])
        r = self.run_batch(t, main, gap, J(replacements=[]))
        self.assertIn('车险5月20日到期', [f['text'] for f in self.u.facts()])
        self.assertTrue(any(x['step'] == 'gap_fill' and x['added'] == 1 for x in r['log']))

    def test_conflict_check_merges_old_and_new_value(self):
        o = self.p.add_object('杯子'); old = self.p.add_fact([o], '绿源可降解杯每个0.42元', evidence=[('s0:1:u', '0.42元')])
        t = self.turns(('绿源可降解杯现在每个0.39元。', '好的。'))
        main = J(memories=[{'title': '杯价', 'text': '绿源可降解杯每个0.39元', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['每个0.39元'], 'invalidates': []}])
        def conflict(prompt):
            refs = __import__('re').findall(r'rp\d+', prompt)
            return J(replacements=[{'refs': refs[:2], 'memories': [{'text': '绿源可降解杯每个0.39元', 'kind': 'fact'}]}])
        self.run_batch(t, main, conflict)
        act = self.p.facts()
        self.assertEqual([f['text'] for f in act], ['绿源可降解杯每个0.39元']); self.assertFalse(self.p.fact(old)['active'])

    def test_secrets_never_reach_prompt_or_store(self):
        t = self.turns(('数据库连接是 postgres://admin:hunter2pass@db.local/inv，端口改成8443。', '好的。'))
        main = J(objects=[{'key': 'k', 'name': '部署', 'scope': 'project', 'parents': []}],
                 memories=[{'title': '端口', 'text': '部署端口8443', 'kind': 'fact', 'about': ['k'], 'evidence': ['端口改成8443'], 'invalidates': []}])
        log = []
        with mock.patch.object(providers, '_fake', wraps=providers._fake) as f:
            self.run_batch(t, main, J(replacements=[]))
            prompts = ' '.join(c.args[2] for c in f.call_args_list)
        self.assertNotIn('hunter2pass', prompts)
        src = ' '.join(r[0] for r in self.p.db.execute('SELECT text FROM sources'))
        self.assertNotIn('hunter2pass', src); self.assertIn('db.local', src)

    def test_no_project_means_personal_only(self):
        t = self.turns(('我只喝茶。', '好的。'))
        main = J(objects=[{'key': 'k', 'name': '饮品', 'scope': 'project', 'parents': []}],
                 memories=[{'title': '茶', 'text': '用户只喝茶', 'kind': 'fact', 'about': ['k'], 'evidence': ['我只喝茶'], 'invalidates': []}])
        self.run_batch(t, main, stores={'u': self.u, 'p': None})
        self.assertEqual([f['text'] for f in self.u.facts()], ['用户只喝茶'])   # 没有项目库时，误标 project 的对象落到个人库

    def test_parse_local_repairs(self):
        self.assertEqual(writer.parse('```json\n{"a":[1,2,],}\n```'), {'a': [1, 2]})


if __name__ == '__main__':
    unittest.main()
