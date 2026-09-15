import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
import staged_sync as staged
import file_sync as files


class BatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.old, self.new = self.root/'old', self.root/'new'
        self.old.mkdir(); self.new.mkdir()
        self.path = 'Client/data.lua'
        self.report = {'config': {'uuid':'repo', 'dev':'dev', 'release':'release',
                                 'target':str(self.root/'working'), 'author':'author', 'days':30, 'snapshot':12},
                       'fileItems':[{'path':self.path, 'revisions':[10]}]}
        self.entry = {'path':self.path, 'status':'ready', 'revision':12, 'revisions':[10],
                      'textReview':{'selected':{'field':2}, 'revision':12}}
        for key, directory, data in [('candidate','待合入',b'candidate'), ('baseline','Release快照',b'baseline')]:
            p = self.old/directory/self.path
            p.parent.mkdir(parents=True); p.write_bytes(data)
            self.entry[key] = str(p); self.entry[key+'Hash'] = files.data_hash(data)
        self.core = types.SimpleNamespace(write_json=self.write)
        self.save()

    def write(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))

    def save(self):
        self.state = {'mode':'review-v1', 'reportHash':files.report_hash(self.report),
                      'items':{self.path:copy.deepcopy(self.entry)}}
        for folder in (self.old,self.new):
            self.write(folder/'report.json', self.report)
            self.write(folder/'review.json', self.state)

    def recover(self):
        return staged.repair_review(self.core, self.new)

    def read_entry(self):
        return json.loads((self.new/'review.json').read_text())['items'][self.path]

    def test_legacy_records_recover_and_future_edits_do_not_touch_origin(self):
        old_ledger = (self.old/'review.json').read_bytes()
        self.write(self.new/'review-failures.json', {self.path:'待确认文件路径已改变', 'other':'需人工处理'})
        self.assertEqual(self.recover(), [self.path])
        e = self.read_entry()
        self.assertEqual(staged.reviewed_bytes(self.new,e,'candidate','待合入'), b'candidate')
        self.assertEqual(staged.reviewed_bytes(self.new,e,'baseline','Release快照'), b'baseline')
        self.assertEqual(e['textReview'], self.entry['textReview'])
        self.assertEqual(json.loads((self.new/'review-failures.json').read_text()), {'other':'需人工处理'})
        self.assertEqual(self.recover(), [])
        pathlib.Path(e['candidate']).write_bytes(b'edited')
        self.assertEqual(pathlib.Path(self.entry['candidate']).read_bytes(), b'candidate')
        self.assertEqual((self.old/'review.json').read_bytes(), old_ledger)
        with self.assertRaisesRegex(RuntimeError, '已被修改'):
            staged.reviewed_bytes(self.new,e,'candidate','待合入')

    def test_added_and_deleted_files_keep_null_side(self):
        for absent in ('baseline','candidate'):
            with self.subTest(absent=absent):
                saved = copy.deepcopy(self.entry)
                self.entry[absent] = None; self.entry[absent+'Hash'] = None
                self.save(); self.assertEqual(self.recover(), [self.path])
                self.assertIsNone(self.read_entry()[absent])
                self.entry = saved

    def test_tampered_or_missing_source_never_rewrites_ledger(self):
        p = pathlib.Path(self.entry['candidate'])
        for data in (b'tampered',None):
            if data is None: p.unlink()
            else: p.write_bytes(data)
            self.assertEqual(self.recover(), [])
            self.assertEqual(self.read_entry(), self.entry)
            self.assertFalse((self.new/'待合入'/self.path).exists())

    def test_source_symlink_rejected_even_when_content_matches(self):
        p = pathlib.Path(self.entry['candidate']); p.unlink()
        outside = self.root/'outside'; outside.write_bytes(b'candidate'); p.symlink_to(outside)
        self.assertEqual(self.recover(), [])
        self.assertEqual(self.read_entry(), self.entry)

    def test_changed_author_or_revisions_rejected(self):
        for change in ('author','revisions'):
            report = copy.deepcopy(self.report)
            if change == 'author': report['config']['author'] = 'other'
            else: report['fileItems'][0]['revisions'] = [11]
            state = copy.deepcopy(self.state); state['reportHash'] = files.report_hash(report)
            self.write(self.new/'report.json',report); self.write(self.new/'review.json',state)
            self.assertEqual(self.recover(), [])
            self.assertEqual(self.read_entry(),self.entry)

    def test_new_snapshot_keeps_original_review_revision(self):
        report = copy.deepcopy(self.report); report['config']['snapshot'] = 15
        state = copy.deepcopy(self.state); state['reportHash'] = files.report_hash(report)
        self.write(self.new/'report.json', report); self.write(self.new/'review.json',state)
        self.assertEqual(self.recover(), [self.path])
        self.assertEqual(self.read_entry()['revision'],12)

    def test_pending_or_changed_origin_is_preserved(self):
        for key, value in [('pending',self.path), ('items',{})]:
            state = copy.deepcopy(self.state); state[key] = value
            self.write(self.old/'review.json',state)
            self.assertEqual(self.recover(), [])
            self.assertEqual(self.read_entry(),self.entry)

    def test_existing_different_destination_not_overwritten(self):
        target = self.new/'待合入'/self.path; target.parent.mkdir(parents=True)
        target.write_bytes(b'user edit')
        self.assertEqual(self.recover(), [])
        self.assertEqual(target.read_bytes(),b'user edit')
        self.assertEqual(self.read_entry(),self.entry)

    def test_restoration_backups_and_choices_are_carried(self):
        digest = files.data_hash(b'original workbook')
        relative = pathlib.Path('撤回前副本')/hashlib.sha256(self.path.encode()).hexdigest()/(digest+'.xlsx')
        backup = self.old/relative; backup.parent.mkdir(parents=True); backup.write_bytes(b'original workbook')
        self.entry['withdrawnRows'] = [{'sheet':'sheet', 'row':1, 'backupHash':digest}]
        field_relative = pathlib.Path('字段选择前副本')/(self.path+'.'+files.data_hash(b'previous field'))
        backup = self.old/field_relative; backup.parent.mkdir(parents=True); backup.write_bytes(b'previous field')
        self.save(); self.assertEqual(self.recover(),[self.path])
        self.assertEqual((self.new/relative).read_bytes(),b'original workbook')
        self.assertEqual((self.new/field_relative).read_bytes(),b'previous field')
        self.assertEqual(self.read_entry()['withdrawnRows'], self.entry['withdrawnRows'])

    def test_pending_destination_does_not_recover(self):
        state = copy.deepcopy(self.state); state['pending'] = self.path
        self.write(self.new/'review.json',state)
        self.assertEqual(self.recover(),[])
        self.assertEqual(json.loads((self.new/'review.json').read_text()),state)


if __name__ == '__main__': unittest.main()
