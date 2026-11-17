"""写入器：用 fake 提供方（预设回答）验证程序侧逻辑，不调用任何模型。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import providers, writer
from hyperthymesia.store import close_all, Store, state


def J(**kw): return json.dumps(kw, ensure_ascii=False)


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_PROVIDER': 'fake'}); self.env.start()
        self.u = Store(self.home / 'personal.db', 'u'); self.p = Store(self.home / 'p.db', 'p')
        providers.FAKE_REPLIES.clear()

    def tearDown(self):
        self.env.stop(); close_all(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

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

    def test_ref_typo_fixed_but_unmatched_quote_kept_pending(self):
        o = self.p.add_object('滨江店'); old = self.p.add_fact([o], '员工8人', evidence=[('s0:1:u', '8人')])
        t = self.turns(('滨江店现在10个员工了。', '好的。'))
        bad = 'rp%d' % old + 'x'   # 多一个字：编辑距离 1，可纠正
        main = J(memories=[{'title': '员工', 'text': '滨江店员工10人', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['滨江店现在10个员工'], 'invalidates': [bad]},
                           {'title': '编造', 'text': '店长换人了', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['店长已经换成老王'], 'invalidates': []}])
        with self.assertRaises(writer.PendingEvidence):
            self.run_batch(t, main, J(quotes=['还是对不上的引用']))
        texts = [f['text'] for f in self.p.facts()]
        self.assertIn('滨江店员工10人', texts); self.assertNotIn('员工8人', texts); self.assertNotIn('店长换人了', texts)
        checkpoint = json.loads(state(self.home).execute('SELECT payload FROM writer_progress').fetchone()[0])
        self.assertNotIn('main', checkpoint['done'])
        self.assertEqual(checkpoint['main_output']['memories'][1]['text'], '店长换人了')

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

    def test_same_batch_near_duplicates_are_candidates(self):
        a = self.p.add_object('配置'); b = self.p.add_object('日志')
        f1 = self.p.add_fact([a], 'inventory/config.py将DEFAULT_PAGE_SIZE设为50；list未指定--limit时使用该值。')
        f2 = self.p.add_fact([b], '项目的list命令未提供--limit时默认分页大小为50。')
        f3 = self.p.add_fact([a], '低库存阈值为10'); f4 = self.p.add_fact([b], '滨江店员工10人')
        bt = writer.Batch(self.home, {'p': self.p}, []); bt.new_facts = [('p', x) for x in (f1, f2, f3, f4)]
        pairs = {frozenset((f['id'], g['id'])) for _, f, g in bt.conflict_candidates()}
        self.assertIn(frozenset((f1, f2)), pairs)                 # 同一取值说了两遍
        self.assertNotIn(frozenset((f3, f4)), pairs)              # 只是碰巧数字相同

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

    def test_missing_array_bracket_preserves_every_value(self):
        raw = '{"memories":[{"text":"原文含,]不能改","evidence":["原文","invalidates":[]}]}'
        got = writer.parse(raw)
        self.assertEqual(got, {'memories': [{'text': '原文含,]不能改', 'evidence': ['原文'], 'invalidates': []}]})
        with self.assertRaises(ValueError): writer.parse('{"text":"他说"好""}')

    def test_quote_repair_receives_original_and_keeps_replacement(self):
        o = self.p.add_object('版本'); old = self.p.add_fact([o], '版本1.0')
        turns = self.turns(('版本改到2.0。', '已发布 **2.0**，仓库 https://example.org/repo.git。'))
        main = J(replacements=[{'refs': ['rp%d' % old], 'memories': [
            {'title': '发布结果', 'text': '已发布2.0', 'kind': 'fact', 'about': ['p%d' % o], 'evidence': ['发布成功2.0']}]}])
        def repair(prompt):
            self.assertIn(turns[0]['assistant'], prompt)
            self.assertIn(turns[0]['user'], prompt)
            return J(quotes=[['已发布 **2.0**']])
        result = self.run_batch(turns, main, repair, J(), J(replacements=[]))
        self.assertFalse(self.p.fact(old)['active'])
        fact = next(f for f in self.p.facts() if f['text'] == '已发布2.0')
        self.assertEqual(fact['source_role'], 'assistant')
        self.assertEqual(self.p.db.execute('SELECT quote FROM evidence WHERE fact=?', (fact['id'],)).fetchone()[0], '已发布 **2.0**')

    def test_resume_gap_failure_does_not_extract_or_save_main_twice(self):
        turns = self.turns(('我有一只叫年糕的猫。', '已完成项目部署。'))
        main = J(objects=[{'key': 'deploy', 'name': '部署', 'scope': 'project'}], memories=[
            {'title': '部署结果', 'text': '项目部署完成', 'about': ['deploy'], 'evidence': ['已完成项目部署']}])
        def failed(_): raise providers.ProviderError('补漏请求连接失败')
        with self.assertRaises(providers.ProviderError): self.run_batch(turns, main, failed)
        first = self.p.facts()[0]
        gap = J(objects=[{'key': 'cat', 'name': '年糕', 'scope': 'personal'}], memories=[
            {'title': '宠物', 'text': '用户的猫叫年糕', 'about': ['cat'], 'evidence': ['一只叫年糕的猫']}])
        result = self.run_batch(turns, gap)
        self.assertEqual(result['calls'], 1)
        self.assertEqual(self.p.facts()[0]['id'], first['id'])
        self.assertEqual(len(self.p.facts()), 1)
        self.assertEqual(self.u.facts()[0]['text'], '用户的猫叫年糕')

    def test_resume_only_retries_bad_quotes_and_keeps_good_entries(self):
        turns = self.turns(('项目端口8080，超时45秒。', '收到。'))
        main = J(objects=[{'key': 'k', 'name': '配置', 'scope': 'project'}], memories=[
            {'title': '端口', 'text': '项目端口8080', 'about': ['k'], 'evidence': ['端口8080']},
            {'title': '超时', 'text': '项目超时45秒', 'about': ['k'], 'evidence': ['不存在的超时原句']}])
        with self.assertRaises(writer.PendingEvidence): self.run_batch(turns, main, J(quotes=['仍不匹配']))
        port = self.p.facts()[0]
        result = self.run_batch(turns, J(quotes=['超时45秒']))
        self.assertEqual(result['calls'], 1)
        self.assertEqual(len(self.p.facts()), 2)
        self.assertEqual(len(self.p.objects()), 1)
        self.assertEqual(self.p.fact(port['id'])['text'], '项目端口8080')
        self.assertEqual(self.p.db.execute('SELECT COUNT(*) FROM facts WHERE text=?', ('项目端口8080',)).fetchone()[0], 1)

    def test_old_history_cannot_supersede_newer_source(self):
        o = self.p.add_object('超时')
        self.p.add_source('new:1:u', 'new', 1, 'user', '2026-11-15T00:00:00Z', '超时已改成60秒')
        current = self.p.add_fact([o], '超时60秒', evidence=[('new:1:u', '超时已改成60秒')])
        turns = self.turns(('超时45秒。', '收到。')); turns[0]['at'] = '2026-11-01T00:00:00Z'
        main = J(memories=[{'title': '超时', 'text': '超时45秒', 'about': ['p%d' % o],
                           'evidence': ['超时45秒'], 'invalidates': ['rp%d' % current]}])
        result = self.run_batch(turns, main)
        self.assertTrue(self.p.fact(current)['active'])
        older = self.p.db.execute('SELECT * FROM facts WHERE text=?', ('超时45秒',)).fetchone()
        self.assertFalse(older['active']); self.assertEqual(older['superseded_by'], current)
        self.assertEqual(result['calls'], 1)

    def test_conflict_prompt_has_original_dates_not_insert_order(self):
        o = self.p.add_object('开业')
        self.p.add_source('old:1:u', 'old', 1, 'user', '2026-10-01T00:00:00Z', '开业12月1日')
        self.p.add_fact([o], '开业12月1日', evidence=[('old:1:u', '开业12月1日')])
        turns = self.turns(('开业改成12月2日。', '收到。'))
        main = J(memories=[{'text': '开业12月2日', 'about': ['p%d' % o], 'evidence': ['改成12月2日']}])
        def check(prompt):
            self.assertIn('2026-10-01', prompt); self.assertIn('2026-11-14', prompt)
            self.assertIn('不按入库先后', prompt)
            return J(replacements=[])
        self.run_batch(turns, main, check)

    def test_old_history_cannot_withdraw_newer_advice(self):
        o = self.p.add_object('建议')
        self.p.add_source('new:1:a', 'new', 1, 'assistant', '2026-11-15T00:00:00Z', '建议周四检查日志')
        n = self.p.add_fact([o], '建议周四检查日志', kind='suggestion', source_role='assistant',
                            evidence=[('new:1:a', '建议周四检查日志')])
        turns = self.turns(('取消旧建议。', '收到。')); turns[0]['at'] = '2026-11-01T00:00:00Z'
        main = J(advice_updates=[{'ref': 'rp%d' % n, 'effect': 'withdrawn', 'reason': '较早会话的取消请求'}])
        self.run_batch(turns, main, J())
        self.assertIsNone(self.p.fact(n)['advice_status'])

    def test_store_operation_is_atomic_and_idempotent(self):
        o = self.p.add_object('配置')
        first = self.p.add_fact([o], '阈值10', operation='same-operation')
        again = self.p.add_fact([o], '阈值10', operation='same-operation')
        self.assertEqual(first, again); self.assertEqual(len(self.p.facts()), 1)

    def test_failed_batch_resumes_after_threshold_changes(self):
        from hyperthymesia import writecmd
        with mock.patch.dict(os.environ, {'HYPERTHYMESIA_HOME': str(self.home)}):
            st = state(self.home)
            for i, text in enumerate(['我只喝茶。', '我的猫3岁。'], 1):
                st.execute('INSERT INTO backlog(session,turn,project,user_text,assistant_text,started_at,completed_at) VALUES(?,?,?,?,?,?,?)',
                           ('s1', i, '', text, '收到。', '2026-11-14', '2026-11-14'))
            main = J(objects=[{'key': 'k', 'name': '个人偏好', 'scope': 'personal'}], memories=[
                {'text': '用户只喝茶', 'about': ['k'], 'evidence': ['我只喝茶']}])
            def failed(_): raise providers.ProviderError('补漏暂时不可用')
            providers.FAKE_REPLIES[:] = [main, failed]
            with mock.patch.object(writecmd, 'BATCH_TOKENS', 99999), self.assertRaises(RuntimeError):
                writecmd.write_project('')
            before = self.u.facts()[0]['id']
            providers.FAKE_REPLIES[:] = [J(memories=[{'text': '用户的猫3岁', 'about': ['k'], 'evidence': ['我的猫3岁']}])]
            with mock.patch.object(writecmd, 'BATCH_TOKENS', 1):
                self.assertEqual(writecmd.write_project(''), 2)
            self.assertEqual(self.u.fact(before)['text'], '用户只喝茶')
            self.assertEqual(len(self.u.objects()), 1)
            self.assertEqual(st.execute('SELECT COUNT(*) FROM backlog WHERE written=1').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
