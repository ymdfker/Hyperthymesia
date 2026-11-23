"""原型功能落地审查（2026-11-20）补回项的回归测试：fake 提供方，不调用模型。
每条测试对应审查报告 port-audit-20261120/REPORT.md 里的编号。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import providers, reader, writer, writecmd
from hyperthymesia.store import close_all, Store, state
os.environ.setdefault('HYPERTHYMESIA_WRITER_MODE', 'single')   # 这些用例按一次调用流程预设回答；两阶段流程见 test_staged.py


def J(**kw): return json.dumps(kw, ensure_ascii=False)


class PortAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_PROVIDER': 'fake'}); self.env.start()
        self.u = Store(self.home / 'personal.db', 'u'); self.p = Store(self.home / 'p.db', 'p')
        providers.FAKE_REPLIES.clear()

    def tearDown(self):
        self.env.stop(); close_all(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

    def turns(self, *pairs):
        return [{'session': 's1', 'turn': i, 'user': u, 'assistant': a, 'at': '2026-11-14'} for i, (u, a) in enumerate(pairs, 1)]

    def run_batch(self, turns, *replies):
        providers.FAKE_REPLIES.extend(replies)
        return writer.write_batch(self.home, {'u': self.u, 'p': self.p}, turns, state(self.home))

    def held(self):
        p = self.home / 'held_entries.jsonl'
        return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []

    # ---------------- 整批失败类
    def test_W13_conflict_check_failure_keeps_batch(self):
        o = self.p.add_object('配置'); self.p.add_fact([o], '超时30秒', title='超时')
        t = self.turns(('超时改成45秒。', '好的。'))
        main = J(memories=[{'title': '超时', 'text': '超时45秒', 'kind': 'fact', 'about': ['p%d' % o], 'spans': ['S1U:1'], 'invalidates': []}])
        r = self.run_batch(t, main, '这不是JSON')
        self.assertIn('超时45秒', [f['text'] for f in self.p.facts()])
        self.assertTrue(any(x['step'] == 'conflict_failed_kept_batch' for x in r['log']))
        self.assertEqual(self.held()[-1]['reason'], 'conflict_check_failed')

    def test_N3_harmless_extra_field_dropped(self):
        o = self.p.add_object('配置')
        main = J(memories=[{'title': '端口', 'text': '端口8080', 'kind': 'fact', 'about': ['p%d' % o], 'spans': ['S1U:1']}], skip_rounds=[1])
        r = self.run_batch(self.turns(('端口8080。', '好。')), main, J(replacements=[]))
        self.assertEqual([f['text'] for f in self.p.facts()], ['端口8080'])
        self.assertTrue(any(x['step'] == 'dropped_fields' for x in r['log']))

    def test_W6_empty_format_fix_is_loss(self):
        bad = '{"memories":[{"title":"a","text":"' + 'x' * 250 + '",}'
        with self.assertRaises(providers.ProviderError) as cm:
            self.run_batch(self.turns(('a', 'b')), bad, '{}')
        self.assertIn('判为内容丢失', str(cm.exception))

    def test_W3_missing_about_guessed_or_held(self):
        o = self.p.add_object('滨江店')
        main = J(memories=[{'title': '员工', 'text': '滨江店员工10人', 'kind': 'fact', 'about': ['不存在'], 'spans': ['S1U:1']},
                           {'title': '谜', 'text': '无从归属', 'kind': 'fact', 'about': [], 'spans': ['S1U:1']}])
        r = self.run_batch(self.turns(('滨江店10个员工。', '好。')), main, J(replacements=[]))
        f = self.p.facts()[0]; self.assertEqual((f['text'], f['object']), ('滨江店员工10人', o))
        self.assertEqual(self.held()[-1]['reason'], 'no_about')

    # ---------------- 补漏
    def test_W8_user_fact_in_passing_triggers_gap_even_if_assistant_cited(self):
        t = self.turns(('车险5月20日到期，帮我写个自驾清单。', '清单如下……'))
        main = J(objects=[{'key': 'k', 'name': '自驾', 'scope': 'personal', 'parents': []}],
                 memories=[{'title': '清单', 'text': '助手建议自驾前检查胎压', 'kind': 'suggestion', 'about': ['k'], 'spans': ['S1A:1']}])
        seen = []
        def gap(prompt):
            seen.append(prompt)
            return J(objects=[{'key': 'c', 'name': '车险', 'scope': 'personal', 'parents': []}],
                     memories=[{'title': '车险到期', 'text': '车险5月20日到期', 'kind': 'fact', 'about': ['c'], 'spans': ['S1U:1']}])
        r = self.run_batch(t, main, gap, J(replacements=[]))
        self.assertIn('车险5月20日到期', [f['text'] for f in self.u.facts()])
        g = next(x for x in r['log'] if x['step'] == 'gap_fill'); self.assertEqual(g['still_uncovered'], [])

    def test_W9_object_only_round_and_gap_window(self):
        t = self.turns(*[('第%d轮随便聊。' % i, '好。') for i in range(1, 10)])
        calls = []
        def gap(prompt): calls.append(prompt); return '{}'
        r = self.run_batch(t, '{}', gap, gap, J(replacements=[]))
        self.assertEqual(len(calls), 2)                     # 9 轮缺口按每次 7 轮分两次补问
        self.assertIn('本次补漏只给7轮', calls[0]); self.assertIn('本次补漏只给2轮', calls[1])
        self.assertEqual(next(x for x in r['log'] if x['step'] == 'gap_fill')['still_uncovered'], list(range(1, 10)))

    # ---------------- 来源
    def test_W1_markdown_ellipsis_and_approximate_quotes(self):
        o = self.p.add_object('发布')
        t = self.turns(('发布吧。', '- 已发布 **2.0** 版本\n- 仓库地址不变；文档已更新'))
        main = J(memories=[{'title': 'a', 'text': '已发布2.0', 'kind': 'fact', 'assertion': 'report', 'about': ['p%d' % o], 'evidence': ['已发布 2.0 版本']},
                           {'title': 'b', 'text': '仓库与文档', 'kind': 'fact', 'assertion': 'report', 'about': ['p%d' % o], 'evidence': ['仓库地址不变…文档已更新']},
                           {'title': 'c', 'text': '近似', 'kind': 'fact', 'assertion': 'report', 'about': ['p%d' % o], 'evidence': ['已发布了2.0版本']}])
        r = self.run_batch(t, main, '{}', J(replacements=[]))   # 用户原话“发布吧”未被用户事实引用，按 §23.53 补问一次
        self.assertEqual(sorted(f['title'] for f in self.p.facts()), ['a', 'b', 'c'])
        self.assertTrue(any(x['step'] == 'approximate_quote' for x in r['log']))

    def test_W2_user_echo_makes_user_decision_mixed(self):
        o = self.p.add_object('配置')
        t = self.turns(('低库存阈值改成10吧。', '已把 LOW_STOCK_THRESHOLD 改为 10。'))
        main = J(memories=[{'title': '阈值', 'text': '低库存阈值为10', 'kind': 'fact', 'about': ['p%d' % o], 'spans': ['S1A:1']}])
        self.run_batch(t, main, J(replacements=[]))
        self.assertEqual(self.p.facts()[0]['source_role'], 'mixed')

    def test_W5_cross_object_ref_retargeted(self):
        a = self.p.add_object('文三路店'); b = self.p.add_object('滨江店')
        fa = self.p.add_fact([a], '文三路店豆子140元', title='豆价'); fb = self.p.add_fact([b], '滨江店豆子150元', title='豆价')
        t = self.turns(('滨江那家豆子涨到160了。', '好的。'))
        main = J(memories=[{'title': '豆价', 'text': '滨江店豆子160元', 'kind': 'fact', 'about': ['p%d' % b], 'spans': ['S1U:1'], 'invalidates': ['rp%d' % fa]}])
        r = self.run_batch(t, main, J(replacements=[]))
        self.assertTrue(self.p.fact(fa)['active']); self.assertFalse(self.p.fact(fb)['active'])
        self.assertTrue(any(x['step'] == 'cross_object_ref_retargeted' for x in r['log']))

    def test_W7_same_name_object_reused(self):
        o = self.p.add_object('滨江店')
        main = J(objects=[{'key': 'n', 'name': '滨江店', 'scope': 'project', 'parents': []}],
                 memories=[{'title': '员工', 'text': '滨江店员工10人', 'kind': 'fact', 'about': ['n'], 'spans': ['S1U:1']}])
        self.run_batch(self.turns(('滨江店10个员工。', '好。')), main, J(replacements=[]))
        self.assertEqual(len(self.p.objects()), 1); self.assertEqual(self.p.facts()[0]['object'], o)

    def test_N1_replacement_without_evidence_uses_batch_and_R3_inherits_entrances(self):
        a = self.p.add_object('寿宴'); b = self.p.add_object('预算')
        old = self.p.add_fact([a, b], '寿宴42人')
        t = self.turns(('人数改成45了。', '好的。'))
        main = J(replacements=[{'refs': ['rp%d' % old], 'memories': [{'title': '人数', 'text': '寿宴45人', 'kind': 'fact', 'about': ['p%d' % a]}]}])
        r = self.run_batch(t, main, J(replacements=[]))
        new = next(f for f in self.p.facts() if f['text'] == '寿宴45人')
        self.assertFalse(self.p.fact(old)['active']); self.assertEqual(set(new['about']), {a, b})
        self.assertTrue(any(x['step'] == 'replacement_batch_source' for x in r['log']))

    # ---------------- 冲突检查
    def test_W14_exact_duplicate_merged_by_program(self):
        big = self.p.add_object('门店'); small = self.p.add_object('滨江排班', parents=[big])
        for i in range(3): self.p.add_fact([big], '其他%d' % i)
        dup = self.p.add_fact([big], '滨江店周二闭店', title='闭店')
        main = J(memories=[{'title': '闭店', 'text': '滨江店周二闭店', 'kind': 'fact', 'about': ['p%d' % small], 'spans': ['S1U:1']}])
        r = self.run_batch(self.turns(('滨江店周二闭店。', '好。')), main)
        act = [f for f in self.p.facts() if f['text'] == '滨江店周二闭店']
        self.assertEqual(len(act), 1); self.assertEqual(act[0]['object'], small); self.assertFalse(self.p.fact(dup)['active'])
        self.assertTrue(any(x['step'] == 'dedupe_merged' for x in r['log']))

    def test_W15_title_containment_and_percent_rules(self):
        o = self.p.add_object('财务'); x = self.p.add_object('其他')
        for i in range(8): self.p.add_fact([o], '填充%d' % i)
        self.p.add_fact([o], '运费每单3元', title='运费'); self.p.add_fact([x], '税率按7%计算')
        b = writer.Batch(self.home, {'u': self.u, 'p': self.p}, self.turns(('a', 'b')))
        n1 = self.p.add_fact([o], '外卖运费改为每单3.5元', title='外卖运费'); n2 = self.p.add_fact([o], '税率改为8.25%计算')
        b.new_facts = [('p', n1), ('p', n2)]
        texts = {(f['text'], g['text']) for _, f, g in b.conflict_candidates()}
        self.assertIn(('外卖运费改为每单3.5元', '运费每单3元'), texts); self.assertIn(('税率改为8.25%计算', '税率按7%计算'), texts)

    # ---------------- 读取
    def test_R1_R2_R5_read_full_recursive_history(self):
        top = self.p.add_object('门店'); mid = self.p.add_object('滨江', parents=[top]); leaf = self.p.add_object('排班', parents=[mid])
        self.p.add_fact([leaf], '滨江周二闭店')
        self.p.add_fact([leaf], '建议错峰排班，周末多排两人', kind='suggestion', source_role='assistant', title='排班建议')
        old = self.p.add_fact([leaf], '滨江周一闭店'); self.p.add_fact([leaf], '滨江周三闭店', supersedes=[old])
        txt = reader.read_objects({'p': self.p}, ['p%d' % top])
        self.assertIn('滨江周二闭店', txt); self.assertIn('助手建议：排班建议', txt); self.assertNotIn('周末多排两人', txt)
        self.assertNotIn('滨江周一闭店', txt)
        txt = reader.read_objects({'p': self.p}, ['p%d' % top], full=True, history=True)
        self.assertIn('周末多排两人', txt); self.assertIn('滨江周一闭店〔已失效', txt)

    def test_R4_directory_hint_when_unchanged_and_read(self):
        o = self.p.add_object('大'); st = state(self.home)
        for i in range(400): self.p.add_fact([o], '事实%03d：' % i + '内容' * 10)
        first = reader.context({'p': self.p}, st, 's'); self.assertIn('对象ID', first)
        self.assertEqual(reader.context({'p': self.p}, st, 's'), '')
        reader.read_objects({'p': self.p}, ['p%d' % o], st, 's')
        self.assertIn('无需再读', reader.context({'p': self.p}, st, 's'))

    # ---------------- 分批
    def test_B2_batch_capped_at_seven_turns(self):
        rows = [{'session': 's', 'turn': i, 'user_text': 'u', 'assistant_text': 'a', 'diff': '', 'numstat': '', 'started_at': 't'} for i in range(1, 16)]
        sizes = []
        with mock.patch.object(writer, 'write_batch', side_effect=lambda h, s, t, st, p: sizes.append(len(t)) or {'new_facts': 1, 'calls': 1, 'usage': {}, 'log': [], 'batch': None}), \
             mock.patch.object(writecmd, 'tx'), mock.patch.object(writecmd, 'Store'), mock.patch.object(writecmd, '_log'):
            writecmd._write_rows('', mock.MagicMock(), rows)                 # 默认：两阶段写入批内切窗口，不按轮数切批
            with mock.patch.object(writecmd, 'BATCH_TURNS', 7): writecmd._write_rows('', mock.MagicMock(), rows)
        self.assertEqual(sizes, [15, 7, 7, 1])


if __name__ == '__main__':
    unittest.main()
