"""两阶段写入（staged.BoundBatch，移植自隔离原型）：fake 提供方按调用顺序回答，不调用模型。"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from hyperthymesia import providers, staged, writer
from hyperthymesia.store import close_all, Store, state


def J(**kw): return json.dumps(kw, ensure_ascii=False)


class StagedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {'HYPERTHYMESIA_PROVIDER': 'fake', 'HYPERTHYMESIA_WRITER_MODE': 'staged'}); self.env.start()
        self.u = Store(self.home / 'personal.db', 'u'); self.p = Store(self.home / 'p.db', 'p')
        providers.FAKE_REPLIES.clear(); self.prompts = []

    def tearDown(self):
        self.env.stop(); close_all(); self.tmp.cleanup(); providers.FAKE_REPLIES.clear()

    def turns(self, *pairs):
        return [{'session': 's1', 'turn': i, 'user': u, 'assistant': a, 'at': '2026-11-14'} for i, (u, a) in enumerate(pairs, 1)]

    def reply(self, text):
        def f(prompt): self.prompts.append(prompt); return text
        return f

    def run_batch(self, turns, *replies):
        providers.FAKE_REPLIES.extend(self.reply(r) for r in replies)
        return writer.write_batch(self.home, {'u': self.u, 'p': self.p}, turns, state(self.home))

    def test_extract_windows_have_no_old_records_and_organize_saves_candidates(self):
        o = self.p.add_object('实验'); self.p.add_fact([o], '旧结论：81/84', title='旧')
        t = self.turns(('跑实验。', '结果84/84。'), ('再看召回。', '召回47/48。'), ('记下来。', '好的。'))
        g1 = J(groups=[{'key': 'e', 'name': '64轮修复后实验', 'object': 'p%d' % o, 'scope': 'project', 'items': [{'text': '修复后保存84/84', 'kind': 'fact', 'spans': ['S1A:1']}]}])
        g2 = J(groups=[{'key': 'e', 'name': '64轮修复后实验', 'object': 'p%d' % o, 'scope': 'project', 'items': [{'text': '修复后召回47/48', 'kind': 'fact', 'spans': ['S2A:1']}]}])
        g3 = J(groups=[])
        org = J(already_present=[])
        r = self.run_batch(t, g1, g2, g3, J(groups=[]), org, '{}', J(replacements=[]))
        extract = [p for p in self.prompts if '<existing_subjects>' in p]
        self.assertEqual(len(extract), 4)                       # 3 个窗口 + 第3窗口按轮补问
        self.assertTrue(all('旧结论' not in p for p in extract))   # 抽取阶段不带旧记录
        self.assertIn('本批材料共1轮（S1）', extract[0])
        organize = next(p for p in self.prompts if '<saved_candidates>' in p)
        self.assertIn('旧结论', organize); self.assertIn('C1', organize)
        texts = [f['text'] for f in self.p.facts()]
        self.assertIn('修复后保存84/84', texts); self.assertIn('修复后召回47/48', texts)
        f = next(f for f in self.p.facts() if f['text'] == '修复后保存84/84')
        self.assertEqual(self.p.db.execute('SELECT quote FROM evidence WHERE fact=?', (f['id'],)).fetchone()[0], '结果84/84。')
        self.assertEqual(r['candidates'], 2)

    def test_replacement_merge_and_bad_operation_held(self):
        o = self.p.add_object('配置'); old = self.p.add_fact([o], '超时30秒', title='超时')
        t = self.turns(('超时改成45秒，重试3次。', '已改。'))
        g = J(groups=[{'key': 'c', 'name': '配置', 'object': 'p%d' % o, 'scope': 'project', 'items': [
            {'text': '超时45秒', 'kind': 'fact', 'spans': ['S1U:1']}, {'text': '重试3次', 'kind': 'fact', 'spans': ['S1U:1']},
            {'text': '坏出处', 'kind': 'fact', 'spans': ['S9A:1']}]}])
        org = J(replacements=[{'refs': ['rp%d' % old], 'candidate_ids': ['C1']}], merges=[{'candidate_ids': ['C9'], 'owner': 'C9'}])
        r = self.run_batch(t, g, org, J(replacements=[]))
        self.assertFalse(self.p.fact(old)['active'])
        self.assertEqual(sorted(f['text'] for f in self.p.facts()), ['超时45秒', '重试3次'])
        held = [json.loads(l) for l in (self.home / 'held_entries.jsonl').read_text(encoding='utf-8').splitlines()]
        reasons = {h['reason'] for h in held}
        self.assertIn('pending_candidate_items', reasons); self.assertIn('pending_organize_operations', reasons)
        self.assertFalse(r['organization_complete'])

    def test_extract_object_is_only_hint_and_placement_needs_shown_records(self):
        o = self.p.add_object('本地小模型评估'); self.p.add_fact([o], '旧评估结论', title='旧')
        t = self.turns(('跑Luna测试。', 'Luna 20/20。'))
        g = J(groups=[{'key': 'l', 'name': 'Luna测试', 'hint': 'p%d' % o, 'scope': 'project',
                       'items': [{'text': 'Luna覆盖20/20', 'kind': 'fact', 'spans': ['S1A:1']}]}])
        # 不放置：抽取阶段的对象提示不被采用，按新事项保存
        self.run_batch(t, g, '{}', J(replacements=[]))
        f = next(f for f in self.p.facts() if f['text'] == 'Luna覆盖20/20')
        self.assertNotEqual(f['object'], o)
        organize = next(p for p in self.prompts if '<saved_candidates>' in p)
        self.assertIn('旧评估结论', organize)     # 提示对象的旧记录给整理阶段核对

    def test_placement_moves_subject_into_shown_object(self):
        o = self.p.add_object('配置'); self.p.add_fact([o], '超时30秒', title='超时')
        t = self.turns(('重试改成3次。', '已改。'))
        g = J(groups=[{'key': 'c', 'name': '配置调整', 'scope': 'project', 'items': [{'text': '重试3次', 'kind': 'fact', 'spans': ['S1U:1']}]}])
        org = J(placements=[{'subject': 'extract_0:c', 'object': 'p%d' % o}, {'subject': 'extract_0:c', 'object': 'p999'}])
        r = self.run_batch(t, g, org, J(replacements=[]))
        f = next(f for f in self.p.facts() if f['text'] == '重试3次')
        self.assertEqual(f['object'], o)
        self.assertFalse(r['organization_complete'])   # 不存在/未展示的对象被挂起

    def test_extract_format_fix_and_same_kind_update_not_held(self):
        t = self.turns(('超时改成45秒。', '已改。'))
        good = J(groups=[{'key': 'c', 'name': '配置', 'scope': 'project', 'items': [{'text': '超时45秒', 'kind': 'fact', 'spans': ['S1U:1']}]}])
        bad = good + good + ' ' * 200    # 两段 JSON：Extra data
        r = self.run_batch(t, bad, good, J(kind_updates=[{'candidate': 'C1', 'kind': 'fact'}]), J(replacements=[]))
        self.assertIn('超时45秒', [f['text'] for f in self.p.facts()])
        self.assertTrue(any('只修正JSON语法' in p for p in self.prompts))
        self.assertTrue(r['organization_complete'])

    def test_rules_carry_scope_credentials_and_granularity(self):
        for text in (staged.EXTRACT, staged.ORGANIZE):
            self.assertIn('不记录任何凭据', text); self.assertIn('个人库', text)
        self.assertIn('过大', staged.ORGANIZE); self.assertNotIn('过大', staged.EXTRACT)   # 对象粒度只在整理阶段
        self.assertNotIn('"memories":[{"assertion"', staged.EXTRACT)   # 不混入一次调用流程的输出格式


if __name__ == '__main__':
    unittest.main()
