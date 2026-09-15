import contextlib,hashlib,importlib.util,io,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch as mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from test_workbook import book,parts,pack
import workbook_cells as cells
from file_sync import merge_data
from revision_cache import reads
from sync_progress import SyncProgress, SyncCancelled

class ReplayTests(unittest.TestCase):
    def test_sequential_reversion_and_foreign_cells_match_existing_merge(self):
        local=book(a='9',b='88',formula=False)
        history=[(book(a='1',b='77',formula=False),book(a='2',b='77',formula=False)),
                 (book(a='2',b='66',formula=False),book(a='3',b='66',formula=False)),
                 (book(a='3',b='55',formula=False),book(a='1',b='55',formula=False))]
        expected=local
        for a,b in history:expected=merge_data(a,b,expected,'book.xlsx',latest=True)
        saves=[];save=cells.Book.save
        with mock.object(cells.Book,'save',lambda b:(saves.append(b),save(b))[1]):
            replay=cells.WorkbookReplay(local)
            for a,b in history:replay.apply(a,b)
            self.assertEqual(saves,[])
            result=replay.finish()
            self.assertEqual(len(saves),1)
        self.assertEqual(cells.logical_signature(result),cells.logical_signature(expected))
        self.assertIn(b'<v>88</v>',parts(result)['xl/worksheets/sheet1.xml'])
        self.assertIn(b'<v>1</v>',parts(result)['xl/worksheets/sheet1.xml'])
    def test_replay_cancellation_happens_before_serializing_candidate(self):
        def cancelled(message):raise RuntimeError('已取消')
        replay=cells.WorkbookReplay(book(a='9',formula=False),cancelled)
        with mock.object(cells.Book,'save',side_effect=AssertionError('must not save')):
            with self.assertRaisesRegex(RuntimeError,'已取消'):
                replay.apply(book(a='1',formula=False),book(a='2',formula=False))
    def test_delete_and_recreate_matches_existing_merge(self):
        local=book(a='9',formula=False);before=book(a='1',formula=False);after=book(a='4',formula=False)
        replay=cells.WorkbookReplay(local);replay.apply(before,None);replay.apply(None,after)
        self.assertEqual(replay.finish(),after)
    def test_unchanged_sheet_does_not_require_record_alignment(self):
        data=book(formula=False);a=cells.Book(data);b=cells.Book(data);t=cells.Book(book(a='7',formula=False))
        with mock.object(cells,'align_config_cells',side_effect=AssertionError('unchanged sheet')):
            cells.patch_books(a,b,t,True,retain=True)
    def test_shared_string_changes_are_not_skipped_for_identical_sheet_xml(self):
        ns=cells.M
        def fixture(text):
            p=parts(book(formula=False))
            p['xl/sharedStrings.xml']=(f'<sst xmlns="{ns}"><si><t>{text}</t></si></sst>').encode()
            p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="A1"><v>1</v></c>',b'<c r="A1" t="s"><v>0</v></c>')
            return pack(p)
        before,after=fixture('old'),fixture('author')
        replay=cells.WorkbookReplay(fixture('release'));replay.apply(before,after)
        self.assertIn('author',cells.Book(replay.finish()).cells('Main')['A1'].toxml())
    def test_native_signature_matches_dom_reference(self):
        from xml.dom import minidom
        data=b'<c xmlns="urn:sheet" xmlns:z="urn:attr" r="A1" z:k="v"><is><t xml:space="preserve"> a </t></is><!--note--></c>'
        self.assertEqual(cells.sig(cells.DOM.parseString(data).documentElement),cells.sig(minidom.parseString(data).documentElement))

class CacheTests(unittest.TestCase):
    def test_only_pinned_content_cached_and_checksum_rechecked(self):
        import types
        calls=[]
        def runner(*args,**kw):calls.append(args);return subprocess.CompletedProcess(args,0,b'content',b'')
        core=types.SimpleNamespace(run=runner)
        args=('cat','-r',7,'--','svn://repo/book.xlsx@7')
        with tempfile.TemporaryDirectory() as folder:
            with reads(core,folder,'repo-uuid'):
                core.run(*args);core.run(*args)
                self.assertEqual(len(calls),1)
                core.run('log','-r',7,'svn://repo@7');core.run('log','-r',7,'svn://repo@7')
                self.assertEqual(len(calls),3)
                file=next(p for p in pathlib.Path(folder).rglob('*') if p.is_file() and len(p.name)==64);file.write_bytes(b'bad')
                core.run(*args);self.assertEqual(len(calls),4)
            self.assertIs(core.run,runner)
            with reads(core,folder,'another-repo'):core.run(*args)
            self.assertEqual(len(calls),5)
    def test_error_and_cancellation_are_persisted_without_cancelling_writes(self):
        import os
        with tempfile.TemporaryDirectory() as folder,mock.dict(os.environ,SVNFLOW_PROGRESS_TOKEN='fixture'):
            progress=SyncProgress(folder,'stage','book.xlsx');progress.phase('读取工作表 Main')
            pathlib.Path(folder,'cancel-fixture').touch()
            try:progress.phase('保存候选')
            except SyncCancelled as error:progress.finish(error)
            value=json.loads(pathlib.Path(folder,'activity-fixture.json').read_text())
            self.assertEqual(value['status'],'cancelled');self.assertIn('已取消',value['error'])
            self.assertIn('已取消',pathlib.Path(folder,'operation-fixture.log').read_text())
            writer=SyncProgress(folder,'accept');writer.phase('写入已确认文件')

    def test_info_cache_never_caches_head_local_or_failed_reads(self):
        import types
        calls=[]
        def runner(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1 if 'svn://repo/missing@7' in args else 0, b'info', b'error')
        core=types.SimpleNamespace(run=runner)
        with tempfile.TemporaryDirectory() as folder, reads(core, folder, 'repo-uuid'):
            for args, count in [
                (('info','--xml','-r',7,'--','svn://repo/file@7'), 1),
                (('info','--xml','-r','HEAD','--','svn://repo/file@HEAD'), 2),
                (('info','--xml','-r',7,'--','/local/file@7'), 2),
                (('info','--xml','-r',7,'--','svn://repo/missing@7'), 2)]:
                before=len(calls)
                core.run(*args,check=False);core.run(*args,check=False)
                self.assertEqual(len(calls)-before,count)
