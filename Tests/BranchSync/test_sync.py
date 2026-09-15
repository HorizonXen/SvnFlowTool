import sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parents[2]/"scripts"))
import importlib.util,json,pathlib,subprocess,tempfile,unittest
spec=importlib.util.spec_from_file_location('branch_sync',pathlib.Path(__file__).resolve().parents[2]/'scripts/branch_sync.py');sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
class SyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);repo=self.root/'repo'
  subprocess.run(['/opt/homebrew/bin/svnadmin','create',str(repo)],check=True)
  self.url=repo.as_uri();seed=self.root/'seed';seed.mkdir();(seed/'a.txt').write_text('one\ntwo\nthree\n');(seed/'binary.bin').write_bytes(b'\x00old')
  sync.run('import',seed,self.url+'/dev','-m','seed','--username','seed');sync.run('copy',self.url+'/dev',self.url+'/release','-m','branch','--username','seed')
  self.dev=self.root/'dev';self.target=self.root/'release';sync.run('checkout',self.url+'/dev',self.dev);sync.run('checkout',self.url+'/release',self.target)
  (self.dev/'a.txt').write_text('one\nchanged\nthree\n');sync.run('commit',self.dev,'-m','change','--username','sample.author');self.rev=sync.info(str(self.dev/'a.txt'))['revision']
  self.config={'dev':self.url+'/dev','release':self.url+'/release','target':str(self.target),'uuid':sync.info(str(self.target))['uuid'],'snapshot':self.rev,'author':'sample.author'}
  self.folder=self.root/'report';self.folder.mkdir();self.report={'config':self.config,'dev':[{'revision':self.rev,'mergeRecorded':False,'outsideScope':[]}]};sync.write_json(self.folder/'report.json',self.report)
  self.old=sync.load_config;sync.load_config=lambda:self.config
 def tearDown(self):sync.load_config=self.old;self.tmp.cleanup()
 def test_confirmed_merge_and_duplicate_block(self):
  sync.operate(self.folder,'prepare');sync.operate(self.folder,'preview',self.rev)
  self.assertEqual((self.target/'a.txt').read_text(),'one\ntwo\nthree\n')
  sync.operate(self.folder,'apply',self.rev);self.assertIn('changed',(self.target/'a.txt').read_text())
  self.assertEqual(sync.run('cat',self.url+'/release/a.txt').stdout,b'one\ntwo\nthree\n') # no server commit
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'apply',self.rev)
 def test_dirty_target_and_later_edits_preserved(self):
  (self.target/'a.txt').write_text('human draft')
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'prepare')
  self.assertEqual((self.target/'a.txt').read_text(),'human draft')
  sync.run('revert',str(self.target/'a.txt'));sync.operate(self.folder,'prepare');(self.target/'a.txt').write_text('new draft')
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'apply',self.rev)
  self.assertEqual((self.target/'a.txt').read_text(),'new draft')
 def test_conflict_dry_run_does_not_write(self):
  (self.target/'a.txt').write_text('one\nrelease own change\nthree\n');sync.run('commit',self.target,'-m','release change','--username','other')
  self.config['snapshot']=sync.info(str(self.target/'a.txt'))['revision'];sync.write_json(self.folder/'report.json',self.report)
  sync.operate(self.folder,'prepare');before=(self.target/'a.txt').read_bytes()
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'apply',self.rev)
  self.assertEqual(before,(self.target/'a.txt').read_bytes());self.assertEqual(sync.fingerprint(str(self.target)),[])
 def test_binary_conflict_is_not_overwritten(self):
  (self.dev/'binary.bin').write_bytes(b'\x00dev change');sync.run('commit',self.dev,'-m','binary dev','--username','sample.author');binary_revision=sync.info(str(self.dev/'binary.bin'))['revision']
  (self.target/'binary.bin').write_bytes(b'\x00release change');sync.run('commit',self.target,'-m','binary release','--username','other')
  self.config['snapshot']=sync.info(str(self.target/'binary.bin'))['revision'];self.report['dev']=[{'revision':binary_revision,'mergeRecorded':False,'outsideScope':[]}];sync.write_json(self.folder/'report.json',self.report)
  sync.operate(self.folder,'prepare')
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'apply',binary_revision)
  self.assertEqual((self.target/'binary.bin').read_bytes(),b'\x00release change')
 def test_wrong_author_blocked(self):
  sync.operate(self.folder,'prepare');self.config['author']='someone.else';sync.write_json(self.folder/'report.json',self.report)
  with self.assertRaises(RuntimeError):sync.operate(self.folder,'apply',self.rev)
  self.assertEqual(sync.fingerprint(str(self.target)),[])
 def use_revision(self, revision):
  self.config['snapshot']=sync.info(self.url)['revision'];self.report['dev']=[{'revision':revision,'mergeRecorded':False,'outsideScope':[]}];sync.write_json(self.folder/'report.json',self.report)
 def test_interleaved_text_does_not_bring_other_author(self):
  (self.dev/'a.txt').write_text('foreign\nchanged\nthree\n');sync.run('commit',self.dev,'-m','other','--username','other')
  (self.dev/'a.txt').write_text('foreign\nchanged\nauthor\n');sync.run('commit',self.dev,'-m','selected','--username','sample.author');rev=sync.info(str(self.dev/'a.txt'))['revision']
  # Release includes the selected author's earlier change, but excludes the foreign first line.
  (self.target/'a.txt').write_text('one\nchanged\nthree\n');sync.run('commit',self.target,'-m','release base','--username','release')
  self.use_revision(rev);sync.operate(self.folder,'prepare');sync.operate(self.folder,'apply',rev)
  self.assertEqual((self.target/'a.txt').read_text(),'one\nchanged\nauthor\n')
 def test_copy_with_foreign_history_is_blocked(self):
  sync.run('copy',str(self.dev/'a.txt'),str(self.dev/'copied.txt'));sync.run('commit',self.dev,'-m','copy','--username','sample.author');rev=sync.info(str(self.dev/'copied.txt'))['revision']
  self.use_revision(rev);sync.operate(self.folder,'prepare')
  with self.assertRaisesRegex(RuntimeError,'历史'):sync.operate(self.folder,'apply',rev)
  self.assertFalse((self.target/'copied.txt').exists())
 def test_excel_formula_and_sheet_delete_with_foreign_changes(self):
  from test_workbook import book,parts
  for wc in (self.dev,self.target):
   (wc/'table.xlsx').write_bytes(book());sync.run('add',str(wc/'table.xlsx'));sync.run('commit',wc,'-m','excel base','--username','seed')
  (self.dev/'table.xlsx').write_bytes(book(b='99'));sync.run('commit',self.dev,'-m','foreign cell','--username','other')
  (self.dev/'table.xlsx').write_bytes(book(a='2',b='99',formula=False,extra=False));sync.run('commit',self.dev,'-m','formula and delete sheet','--username','sample.author');rev=sync.info(str(self.dev/'table.xlsx'))['revision']
  (self.target/'table.xlsx').write_bytes(book(b='7'));sync.run('commit',self.target,'-m','release cell','--username','release')
  self.use_revision(rev);sync.operate(self.folder,'prepare');before=(self.target/'table.xlsx').read_bytes();sync.operate(self.folder,'preview',rev)
  self.assertEqual((self.target/'table.xlsx').read_bytes(),before)
  sync.operate(self.folder,'apply',rev);result=parts((self.target/'table.xlsx').read_bytes());sheet=result['xl/worksheets/sheet1.xml']
  self.assertNotIn(b'<f>',sheet);self.assertIn(b'<v>7</v>',sheet);self.assertNotIn(b'99',sheet);self.assertNotIn('xl/worksheets/sheet2.xml',result)
  self.assertEqual(sync.run('cat',self.url+'/release/table.xlsx').stdout,before)
  self.assertFalse(list(self.target.glob('*.merge-*')))
 def test_added_project_file(self):
  (self.dev/'new.csproj').write_text('<Project/>');sync.run('add',str(self.dev/'new.csproj'));sync.run('commit',self.dev,'-m','new project','--username','sample.author');rev=sync.info(str(self.dev/'new.csproj'))['revision']
  self.use_revision(rev);sync.operate(self.folder,'prepare');sync.operate(self.folder,'apply',rev)
  self.assertEqual((self.target/'new.csproj').read_text(),'<Project/>')
 def test_merge_commit_provenance_blocked(self):
  sync.run('update',self.dev)
  sync.run('propset','svn:mergeinfo','/other:1',self.dev);sync.run('commit',self.dev,'-m','merge other','--username','sample.author');rev=sync.info(str(self.dev))['revision']
  self.use_revision(rev);sync.operate(self.folder,'prepare')
  with self.assertRaisesRegex(RuntimeError,'合并记录'):sync.operate(self.folder,'apply',rev)
  self.assertEqual(sync.fingerprint(str(self.target)),[])
 def test_excel_conflict_leaves_entire_revision_unwritten(self):
  from test_workbook import book
  for wc in (self.dev,self.target):
   (wc/'table.xlsx').write_bytes(book());sync.run('add',str(wc/'table.xlsx'));sync.run('commit',wc,'-m','excel base','--username','seed')
  (self.dev/'table.xlsx').write_bytes(book(a='2',formula=False));(self.dev/'a.txt').write_text('selected code')
  sync.run('commit',self.dev,'-m','selected','--username','sample.author');rev=sync.info(str(self.dev/'table.xlsx'))['revision']
  (self.target/'table.xlsx').write_bytes(book(a='8'));sync.run('commit',self.target,'-m','release edit','--username','release')
  self.use_revision(rev);sync.operate(self.folder,'prepare');before=(self.target/'table.xlsx').read_bytes()
  with self.assertRaisesRegex(RuntimeError,'A1'):sync.operate(self.folder,'apply',rev)
  self.assertEqual((self.target/'table.xlsx').read_bytes(),before);self.assertEqual((self.target/'a.txt').read_text(),'one\ntwo\nthree\n');self.assertEqual(sync.fingerprint(str(self.target)),[])
 def test_records_exact_author_scope_and_time(self):
  tree=sync.ET.fromstring('<log><logentry revision="1"><author>sample.author</author><date>2026-09-01T00:00:00Z</date><msg>x</msg><paths><path action="M">/dev/a</path><path action="M">/other/b</path></paths></logentry><logentry revision="2"><author>other</author><date>2026-09-01T00:00:00Z</date><msg>sample.author</msg><paths><path action="M">/dev/a</path></paths></logentry></log>')
  rows=sync.records(tree,self.url+'/dev',self.url,'sample.author','2026-08-01','2026-09-05');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['paths'][0]['path'],'a');self.assertEqual(rows[0]['outsideScope'],['/other/b'])
if __name__=='__main__':unittest.main()
