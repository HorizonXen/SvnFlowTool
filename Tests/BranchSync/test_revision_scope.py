"""Selected SVN IDs constrain the report before any file content reads."""
import copy
import unittest
from test_directory_scope import report, LUA, EXCEL
import staged_sync as staged

class RevisionScopeTests(unittest.TestCase):
    def source(self):
        source = report()
        for revision, message, path in [(5, '怪物属性修改', LUA+'/a.lua'), (6, '其他修改', EXCEL+'/table.xlsx'), (7, '怪物属性修改', LUA+'/b.lua')]:
            source['dev'].append(dict(revision=revision, message=message, date='2026-09-12', paths=[dict(path=path,action='M',kind='file')]))
        source['fileItems'] = staged.files.group_files(source['dev'])
        return source

    def test_partial_nonconsecutive_and_directory_intersection(self):
        source = self.source(); before = copy.deepcopy(source)
        result = staged.scoped_report(source, [LUA], [7,5,5])
        self.assertEqual(result['config']['scopeRevisions'], [5,7])
        self.assertEqual([r['revision'] for r in result['dev']], [5,7])
        self.assertEqual({i['path']:i['revisions'] for i in result['fileItems']}, {LUA+'/a.lua':[5], LUA+'/b.lua':[7]})
        self.assertEqual(source,before)

    def test_empty_unknown_invalid_are_rejected(self):
        for ids in [[], [999], [5,999], [0], ['5'], [True], [-1]]:
            with self.subTest(ids=ids), self.assertRaises(RuntimeError): staged.scoped_report(self.source(),None,ids)

    def test_all_and_legacy(self):
        source=self.source()
        self.assertEqual(staged.scoped_report(source,None,[4,5,6,7])['fileItems'],source['fileItems'])
        self.assertNotIn('scopeRevisions',staged.scoped_report(source,None)['config'])

# Local disposable SVN repositories exercise the actual replay pipeline.
import pathlib
import test_file_sync as fixture
from test_sync import sync
from file_sync import build_plan, report_hash
from test_workbook import book, parts

class RevisionReplayTests(unittest.TestCase):
    setUp = fixture.FileSyncTests.setUp
    tearDown = fixture.FileSyncTests.tearDown
    commit = fixture.FileSyncTests.commit
    report_files = fixture.FileSyncTests.report_files
    seed_excel = fixture.FileSyncTests.seed_excel

    def select(self, revisions, path='a.txt'):
        self.report_files()
        self.report = staged.scoped_report(self.report, None, revisions)
        sync.write_json(self.folder/'report.json', self.report)
        sync.write_json(self.folder/'review.json', {'mode':'review-v1','items':{},'reportHash':report_hash(self.report)})
        return next(i for i in self.report['fileItems'] if i['path']==path)

    def test_selected_value_excludes_later_same_author_and_foreign_edits(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.dev,'a.txt',b'foreign\nlater\nthree\n')
        self.commit(self.dev,'a.txt',b'foreign\nlatest\nthree\n','other')
        item=self.select([chosen])
        plan=build_plan(sync,self.report,item,True)
        self.assertEqual(plan['data'],b'one\nselected\nthree\n')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')

    def test_nonconsecutive_revisions_keep_unselected_field_out(self):
        one=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.dev,'a.txt',b'unselected\nselected\nthree\n')
        two=self.commit(self.dev,'a.txt',b'unselected\nselected\nlast\n')
        item=self.select([two,one])
        self.assertEqual(build_plan(sync,self.report,item,True)['data'],b'one\nselected\nlast\n')

    def test_latest_equality_does_not_hide_selected_historical_delta(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.dev,'a.txt',b'one\ntwo\nthree\n')
        self.select([chosen])
        result=staged.remaining_diff(sync,self.folder)
        self.assertIn('a.txt',result['differentPaths'])
        entry=staged.operate(sync,self.folder,'stage','a.txt')
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(),b'one\nselected\nthree\n')
        staged.operate(sync,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\nselected\nthree\n')
        self.assertEqual(sync.run('cat',self.config['release']+'/a.txt').stdout,b'one\ntwo\nthree\n')

    def test_excel_selected_cell_excludes_later_values(self):
        self.seed_excel()
        chosen=self.commit(self.dev,'table.xlsx',book(a='3',formula=False))
        self.commit(self.dev,'table.xlsx',book(a='7',b='99',formula=False))
        item=self.select([chosen],'table.xlsx')
        data=build_plan(sync,self.report,item,True)['data']
        sheet=parts(data)['xl/worksheets/sheet1.xml']
        self.assertIn(b'<v>3</v>',sheet);self.assertNotIn(b'<v>7</v>',sheet);self.assertNotIn(b'99',sheet)

    def test_local_latest_equality_still_requires_historical_replay(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.dev,'a.txt',b'one\nlater\nthree\n')
        self.select([chosen])
        (self.target/'a.txt').write_bytes(b'one\nlater\nthree\n')
        result=staged.remaining_diff(sync,self.folder)
        # The local edit overlaps the chosen historical value: protect it, never register equality.
        self.assertEqual(result['localStates']['a.txt'],'error')
        self.assertTrue(result['localIssues']['a.txt'])

    def test_selection_check_marks_merged_without_staging(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.target,'a.txt',b'one\nselected\nthree\n')
        self.report_files()
        preview=self.folder/'scope-preview.json'
        self.report['config'].update(days=30,start='0000',end='9999')
        sync.write_json(preview,self.report)
        destination=self.folder/'selection-check'
        before=(self.target/'a.txt').read_bytes()
        result=staged.scope_check(sync,destination,self.report['config']['author'],30,None,preview,[chosen])
        self.assertTrue(result['complete'])
        self.assertIn('a.txt',result['noDiffPaths'])
        self.assertNotIn('a.txt',result['localIssues'])
        self.assertEqual(result['localStates']['a.txt'],'same')
        self.assertEqual((self.target/'a.txt').read_bytes(),before)
        self.assertEqual(__import__('json').loads((destination/'review.json').read_text())['items'],{})

    def test_selection_check_keeps_unmerged_and_local_issues(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.report_files()
        preview=self.folder/'scope-preview.json'
        self.report['config'].update(days=30,start='0000',end='9999')
        sync.write_json(preview,self.report)
        result=staged.scope_check(sync,self.folder/'check-pending',self.report['config']['author'],30,None,preview,[chosen])
        self.assertIn('a.txt',result['differentPaths'])
        self.commit(self.target,'a.txt',b'one\nselected\nthree\n')
        (self.target/'a.txt').write_bytes(b'one\nconflicting-local\nthree\n')
        result=staged.scope_check(sync,self.folder/'check-local',self.report['config']['author'],30,None,preview,[chosen])
        self.assertIn('a.txt',result['noDiffPaths'])
        self.assertNotEqual(result['localStates']['a.txt'],'same')

    def test_legacy_report_still_uses_latest_values(self):
        chosen=self.commit(self.dev,'a.txt',b'one\nselected\nthree\n')
        self.commit(self.dev,'a.txt',b'one\nlatest\nthree\n','other')
        item=self.select([chosen]);del self.report['config']['scopeRevisions']
        self.assertEqual(build_plan(sync,self.report,item,True)['data'],b'one\nlatest\nthree\n')

if __name__ == '__main__': unittest.main()
