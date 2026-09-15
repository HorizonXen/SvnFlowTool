import unittest
import test_sync as legacy
sync = legacy.sync
from file_sync import group_files, merge_text, merge_properties, build_plan
from test_workbook import book, parts

class TextAggregationTests(unittest.TestCase):
    def test_independent_adjacent_lines_stay_separate(self):
        self.assertEqual(merge_text(b'foreign\nother\nend\n', b'foreign\nlatest\nend\n', b'original\nold\nend\n', True), b'original\nlatest\nend\n')
    def test_foreign_value_on_same_line_is_not_copied(self):
        self.assertEqual(merge_text(b'a=1 b=9\n',b'a=2 b=9\n',b'a=1 b=0\n',True), b'a=2 b=0\n')
    def test_older_selected_value_advances_without_losing_other_fields(self):
        self.assertEqual(merge_text(b'a=0 b=0 c=0\n',b'a=2 b=2 c=0\n',b'a=1 b=0 c=9\n',history=[b'a=1 b=0 c=0\n']),b'a=2 b=2 c=9\n')
    def test_revert_to_base_also_removes_older_author_value(self):
        self.assertEqual(merge_text(b'a=0 b=0\n',b'a=0 b=0\n',b'a=1 b=9\n',history=[b'a=1 b=0\n']),b'a=0 b=9\n')
    def test_reverted_property_removes_only_known_older_author_value(self):
        self.assertEqual(merge_properties({}, {}, {'author':b'old','release':b'keep'}, history=[{'author':b'old'}]), {'release':b'keep'})
    def test_independent_insertions(self):
        self.assertEqual(merge_text(b'a\nb\nc\n', b'a\nnew\nb\nc\n', b'a\nb\nc\nrelease\n'), b'a\nnew\nb\nc\nrelease\n')
    def test_conflicting_values_block(self):
        with self.assertRaises(RuntimeError): merge_text(b'base\n', b'author\n', b'release\n')
    def test_author_resolution_keeps_release_only_coordinate(self):
        self.assertEqual(merge_text(b'position: {x: -106.84, y: -20, z: 173.54}\n', b'position: {x: -107.48, y: -20, z: 215.78}\n', b'position: {x: 91.0504, y: 0, z: -85.0257}\n', True), b'position: {x: -107.48, y: 0, z: 215.78}\n')
    def test_group_by_full_path_and_latest_revision(self):
        records=[{'revision':r,'message':str(r),'date':'now','paths':[{'path':p,'kind':'file'} for p in paths]} for r,paths in [(9,['a/x','b/x']),(2,['a/x'])]]
        groups=group_files(records)
        self.assertEqual(len(groups),2); self.assertEqual(groups[0]['revisions'],[2,9]);self.assertEqual(groups[0]['latestRevision'],9)

class FileSyncTests(unittest.TestCase):
    setUp = legacy.SyncTests.setUp
    tearDown = legacy.SyncTests.tearDown
    def commit(self, wc, path, data, author='sample.author'):
        target=wc/path; exists=target.exists(); target.write_bytes(data)
        if not exists: sync.run('add',str(target))
        sync.run('commit',wc,'-m','file change','--username',author)
        return sync.info(str(target))['revision']
    def report_files(self):
        self.config['snapshot']=sync.info(self.url)['revision']; self.config['root']=self.url
        tree=sync.ET.fromstring(sync.run('log','--xml','-v','-r',f"1:{self.config['snapshot']}",self.config['dev']).stdout)
        rows=sync.records(tree,self.config['dev'],self.url,'sample.author','0000','9999')
        self.report={'schema':2,'config':self.config,'dev':rows,'fileItems':group_files(rows)}
        sync.write_json(self.folder/'report.json',self.report)
    def prepare(self):
        self.report_files(); sync.operate(self.folder,'prepare')
    def apply(self,path): sync.operate(self.folder,'apply',file_path=path)
    def state(self): return sync.json.loads((self.folder/'session.json').read_text())
    def test_app_backup_and_result_verification(self):
        import hashlib
        self.commit(self.dev,'a.txt',b'one\nlatest\nthree\n'); self.prepare()
        original=(self.target/'a.txt').read_bytes()
        self.apply('a.txt')
        backup=self.folder/'backups'/hashlib.sha256(b'a.txt').hexdigest()
        self.assertEqual((backup/'content').read_bytes(),original)
        self.assertIn('a.txt',self.state()['verifiedFiles'])
        sync.operate(self.folder,'verify')
        self.assertTrue((self.folder/'迁移核验报告.md').exists())
        (self.target/'a.txt').write_bytes(b'changed outside app')
        with self.assertRaises(RuntimeError): sync.operate(self.folder,'verify')

    def test_multiple_versions_one_file_final_only(self):
        last=self.commit(self.dev,'a.txt',b'one\nlatest\nthree\n'); self.prepare()
        self.assertEqual(len(self.report['fileItems']),1);self.assertEqual(self.report['fileItems'][0]['latestRevision'],last)
        sync.operate(self.folder,'preview',file_path='a.txt');self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')
        self.apply('a.txt');self.assertEqual((self.target/'a.txt').read_bytes(),b'one\nlatest\nthree\n')
        self.assertEqual(self.state()['doneFiles'],['a.txt'])
        self.assertEqual(sync.run('cat',self.url+'/release/a.txt').stdout,b'one\ntwo\nthree\n')
        with self.assertRaises(RuntimeError): self.apply('a.txt')
    def test_reverted_changes_are_same_without_intermediate_writes(self):
        self.commit(self.dev,'a.txt',b'one\ntwo\nthree\n');self.prepare();self.apply('a.txt')
        self.assertEqual(self.state()['results']['a.txt'],'same');self.assertEqual(sync.fingerprint(str(self.target)),[])
    def test_already_latest_in_release_is_same(self):
        self.commit(self.dev,'a.txt',b'one\nlatest\nthree\n');self.commit(self.target,'a.txt',b'one\nlatest\nthree\n','release');self.prepare();self.apply('a.txt')
        self.assertEqual(self.state()['results']['a.txt'],'same');self.assertEqual(sync.fingerprint(str(self.target)),[])
    def test_release_with_earlier_selected_result_advances_to_latest(self):
        self.commit(self.dev,'a.txt',b'one\nlatest\nthree\n')
        self.commit(self.target,'a.txt',b'release\nchanged\nthree\n','release');self.prepare();self.apply('a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'release\nlatest\nthree\n')
    def test_release_earlier_result_is_reverted_by_latest(self):
        self.commit(self.dev,'a.txt',b'one\ntwo\nthree\n')
        self.commit(self.target,'a.txt',b'release\nchanged\nthree\n','release');self.prepare();self.apply('a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'release\ntwo\nthree\n')
    def test_interleaved_authors_latest_selected_value(self):
        self.commit(self.dev,'a.txt',b'foreign\nother\nthree\n','other')
        self.commit(self.dev,'a.txt',b'foreign\nlatest\nthree\n')
        self.commit(self.target,'a.txt',b'release\ntwo\nthree\n','release');self.prepare();self.apply('a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'release\nlatest\nthree\n')
    def test_choose_any_file_does_not_apply_siblings(self):
        self.commit(self.dev,'z.csproj',b'<Project/>'); self.prepare(); self.apply('z.csproj')
        self.assertEqual((self.target/'z.csproj').read_bytes(),b'<Project/>')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n');self.assertEqual(self.state()['doneFiles'],['z.csproj'])
    def seed_excel(self):
        for wc in (self.dev,self.target): self.commit(wc,'table.xlsx',book(),'seed')
    def test_excel_latest_formula_delete_and_foreign_cell(self):
        self.seed_excel();self.commit(self.dev,'table.xlsx',book(a='3'))
        self.commit(self.dev,'table.xlsx',book(a='5',b='99'),'other')
        self.commit(self.dev,'table.xlsx',book(a='7',b='99',formula=False,extra=False))
        self.commit(self.target,'table.xlsx',book(b='8'),'release');self.prepare();self.apply('table.xlsx')
        result=parts((self.target/'table.xlsx').read_bytes());sheet=result['xl/worksheets/sheet1.xml']
        self.assertIn(b'<v>7</v>',sheet);self.assertIn(b'<v>8</v>',sheet);self.assertNotIn(b'99',sheet);self.assertNotIn(b'<f>',sheet);self.assertNotIn('xl/worksheets/sheet2.xml',result)
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')
    def test_excel_release_with_earlier_author_cell_advances(self):
        self.seed_excel();self.commit(self.dev,'table.xlsx',book(a='3'));self.commit(self.dev,'table.xlsx',book(a='7',formula=False))
        self.commit(self.target,'table.xlsx',book(a='3',b='9'),'release');self.prepare();self.apply('table.xlsx')
        result=parts((self.target/'table.xlsx').read_bytes())['xl/worksheets/sheet1.xml']
        self.assertIn(b'<v>7</v>',result);self.assertIn(b'<v>9</v>',result);self.assertNotIn(b'<f>',result)
    def test_excel_cache_revert_keeps_release_cache_and_other_cell(self):
        self.seed_excel();self.commit(self.dev,'table.xlsx',book(a='3'));self.commit(self.dev,'table.xlsx',book())
        self.commit(self.target,'table.xlsx',book(a='3',b='9'),'release');self.prepare();self.apply('table.xlsx')
        result=parts((self.target/'table.xlsx').read_bytes())['xl/worksheets/sheet1.xml']
        self.assertIn(b'<v>3</v>',result);self.assertIn(b'<v>9</v>',result)
    def test_excel_net_revert_is_same(self):
        self.seed_excel();self.commit(self.dev,'table.xlsx',book(a='3'));self.commit(self.dev,'table.xlsx',book())
        self.prepare();self.apply('table.xlsx');self.assertEqual(self.state()['results']['table.xlsx'],'same');self.assertEqual(sync.fingerprint(str(self.target)),[])
    def test_excel_conflict_keeps_file_and_all_siblings(self):
        self.seed_excel();self.commit(self.dev,'table.xlsx',book(a='3',formula=False))
        from test_workbook import pack
        changed=parts(book(a='8'));changed['xl/worksheets/sheet1.xml']=changed['xl/worksheets/sheet1.xml'].replace(b'<f>1+1</f>',b'<f>4+4</f>')
        self.commit(self.target,'table.xlsx',pack(changed),'release');self.prepare()
        before=(self.target/'table.xlsx').read_bytes()
        with self.assertRaises(RuntimeError):self.apply('table.xlsx')
        self.assertEqual((self.target/'table.xlsx').read_bytes(),before);self.assertEqual(sync.fingerprint(str(self.target)),[]);self.assertNotIn('pending',self.state())
    def test_latest_file_deletion(self):
        sync.run('delete',str(self.dev/'a.txt'));sync.run('commit',self.dev,'-m','delete','--username','sample.author');self.prepare();self.apply('a.txt')
        self.assertFalse((self.target/'a.txt').exists());self.assertEqual(self.state()['doneFiles'],['a.txt'])
    def test_copy_provenance_blocks(self):
        sync.run('copy',str(self.dev/'a.txt'),str(self.dev/'copy.txt'));sync.run('commit',self.dev,'-m','copy','--username','sample.author');self.prepare()
        with self.assertRaisesRegex(RuntimeError,'历史'):self.apply('copy.txt')
        self.assertFalse((self.target/'copy.txt').exists())
    def test_preview_is_reused_only_while_valid(self):
        from unittest.mock import patch
        self.prepare()
        with patch.object(sync.file_sync,'build_plan',wraps=sync.file_sync.build_plan) as build:
            sync.operate(self.folder,'preview',file_path='a.txt');self.apply('a.txt')
            self.assertEqual(build.call_count,1)
    def test_damaged_preview_is_rebuilt(self):
        from unittest.mock import patch
        self.prepare();sync.operate(self.folder,'preview',file_path='a.txt')
        cache=next((self.folder/'previews').iterdir());(cache/'data').write_bytes(b'corrupted cache')
        with patch.object(sync.file_sync,'build_plan',wraps=sync.file_sync.build_plan) as build:
            self.apply('a.txt');self.assertEqual(build.call_count,1)
        self.assertNotEqual((self.target/'a.txt').read_bytes(),b'corrupted cache')
    def test_scoped_fingerprint_matches_full_and_detects_outside_changes(self):
        self.prepare();(self.target/'a.txt').write_text('edited')
        scoped=sync.fingerprint(str(self.target),[self.target/'a.txt'])
        self.assertEqual(scoped,sync.fingerprint(str(self.target)))
        (self.target/'outside.txt').write_text('keep')
        self.assertNotEqual(scoped,sync.fingerprint(str(self.target)))
    def test_manual_edits_and_changed_report_block(self):
        self.prepare();(self.target/'a.txt').write_text('manual')
        with self.assertRaises(RuntimeError):self.apply('a.txt')
        self.assertEqual((self.target/'a.txt').read_text(),'manual')
        sync.run('revert',str(self.target/'a.txt'));self.report['config']['author']='other';sync.write_json(self.folder/'report.json',self.report)
        with self.assertRaises(RuntimeError):self.apply('a.txt')
    def test_other_author_revision_is_rejected(self):
        revision=self.commit(self.dev,'a.txt',b'foreign','other');self.report_files()
        item=dict(self.report['fileItems'][0]);item['revisions']=[revision]
        with self.assertRaisesRegex(RuntimeError,'作者'):build_plan(sync,self.report,item)

if __name__=='__main__': unittest.main()
