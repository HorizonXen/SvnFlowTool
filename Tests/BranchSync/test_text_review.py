import json
import pathlib
import unittest
import test_staged_sync as staged_tests
import staged_sync
import text_review

class TextReviewTests(unittest.TestCase):
    setUp = staged_tests.StagedSyncTests.setUp
    tearDown = staged_tests.StagedSyncTests.tearDown
    commit = staged_tests.StagedSyncTests.commit
    report_files = staged_tests.StagedSyncTests.report_files
    start = staged_tests.StagedSyncTests.start

    def setup_lua(self):
        data = b'return {\n a = {x = 1, y = 2},\n b = {x = 9}\n}\n'
        self.commit(self.dev,'data.lua',data,'seed')
        self.commit(self.target,'data.lua',data,'release')
        self.author_revision = self.commit(self.dev,'data.lua',data.replace(b'x = 1',b'x = 3'))
        self.latest_revision = self.commit(self.dev,'data.lua',data.replace(b'x = 1',b'x = 7'),'other')
        self.core = self.start()
        self.entry = staged_sync.operate(self.core,self.folder,'stage','data.lua')
        return data

    def review(self): return staged_sync.operate(self.core,self.folder,'text-review','data.lua')
    def choose(self,key,side): return staged_sync.operate(self.core,self.folder,'choose-text','data.lua',sheet=key,row=side)

    def test_inherited_review_uses_pinned_snapshot_and_edits_own_copy(self):
        self.setup_lua()
        original_folder = self.folder
        original_candidate = pathlib.Path(self.entry['candidate']).read_bytes()
        newer = self.commit(self.dev,'data.lua',b'return {a = {x = 99, y = 2}, b = {x = 9}}\n','other')
        self.folder = self.root/'new-review'; self.folder.mkdir()
        report = json.loads((original_folder/'report.json').read_text())
        report['config']['snapshot'] = newer
        state = json.loads((original_folder/'review.json').read_text())
        state['reportHash'] = staged_sync.files.report_hash(report)
        self.core.write_json(self.folder/'report.json',report)
        self.core.write_json(self.folder/'review.json',state)
        self.assertEqual(staged_sync.repair_review(self.core,self.folder), ['data.lua'])
        review = self.review()
        self.assertEqual(review['revision'],self.entry['revision'])
        choice = next(v for v in review['choices'] if v['label']=='a / x')
        self.assertEqual(choice['values'],['1','7','7'])
        updated = self.choose(choice['id'],0)
        self.assertNotEqual(pathlib.Path(updated['candidate']).read_bytes(),original_candidate)
        self.assertEqual(pathlib.Path(self.entry['candidate']).read_bytes(),original_candidate)

    def test_three_versions_origins_and_round_trip_preserve_working_copy(self):
        original = self.setup_lua()
        review = self.review()
        choice = next(v for v in review['choices'] if v['label']=='a / x')
        self.assertEqual(choice['values'],['1','7','7'])
        self.assertIn('other',choice['origins'][1])
        self.assertIn('r'+str(self.latest_revision),choice['origins'][1])
        self.assertIn('other',choice['origins'][2])
        self.assertIn('r'+str(self.latest_revision),choice['origins'][2])
        self.assertNotIn('b / x',[v['label'] for v in review['choices']])
        entry = self.choose(choice['id'],2)
        self.assertEqual(text_review.fields(pathlib.Path(entry['candidate']).read_bytes())[choice['id']][0].raw,'7')
        self.assertEqual(self.review()['choices'][0]['selected'],2)
        self.choose(choice['id'],0)
        self.assertEqual(text_review.fields(pathlib.Path(entry['candidate']).read_bytes())[choice['id']][0].raw,'1')
        self.choose(choice['id'],1)
        self.assertEqual(text_review.fields(pathlib.Path(entry['candidate']).read_bytes())[choice['id']][0].raw,'7')
        self.assertEqual((self.target/'data.lua').read_bytes(),original)
        self.assertEqual(self.core.fingerprint(str(self.target)),[])

    def test_source_advances_after_choice_blocks_before_write(self):
        original = self.setup_lua(); choice = self.review()['choices'][0]
        self.choose(choice['id'],2)
        self.commit(self.dev,'data.lua',original.replace(b'x = 1',b'x = 8'),'other')
        with self.assertRaisesRegex(RuntimeError,'源分支最新值已变化'):
            staged_sync.operate(self.core,self.folder,'accept','data.lua')
        self.assertEqual((self.target/'data.lua').read_bytes(),original)

    def test_tampered_candidate_rejected(self):
        self.setup_lua(); choice = self.review()['choices'][0]
        pathlib.Path(self.entry['candidate']).write_bytes(b'return {}')
        with self.assertRaisesRegex(RuntimeError,'副本已被修改'): self.choose(choice['id'],2)

    def test_selected_latest_applies_only_selected_field(self):
        self.setup_lua(); choice = self.review()['choices'][0]
        entry = self.choose(choice['id'],2)
        expected = pathlib.Path(entry['candidate']).read_bytes()
        staged_sync.operate(self.core,self.folder,'accept','data.lua')
        self.assertEqual((self.target/'data.lua').read_bytes(),expected)
        self.assertIn(b'x = 9',expected)

    def test_add_remove_restore_field_and_unicode_comments(self):
        key = json.dumps([['name','a'],['name','x']])
        data = b'return {a = {x = 1, y = 2}, b = {x = 9}}'
        removed = text_review.replace_field(data,key,None)
        self.assertNotIn(key,text_review.fields(removed))
        restored = text_review.replace_field(removed,key,'7')
        self.assertEqual(text_review.fields(restored)[key][0].raw,'7')
        text = 'return { -- 注释\n a = {x = 1, y = 2}}\n'.encode()
        changed = text_review.replace_field(text,key,'3')
        self.assertEqual(changed,text.replace(b'x = 1',b'x = 3'))

    def test_new_file_and_deleted_source_are_explicit(self):
        self.setup_lua()
        self.core.run('delete',self.dev/'data.lua')
        self.core.run('commit',self.dev,'-m','delete','--username','other')
        self.core = self.start()
        staged_sync.operate(self.core,self.folder,'stage','data.lua')
        choice = next(v for v in self.review()['choices'] if v['label']=='a / x')
        self.assertIsNone(choice['values'][2])

if __name__ == '__main__': unittest.main()
