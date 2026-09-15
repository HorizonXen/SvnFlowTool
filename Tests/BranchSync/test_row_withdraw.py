import pathlib
import unittest
from test_author_isolation import fixture,cell,style
from test_workbook import parts,pack,NS
from workbook_cells import Book,restore_row
import test_staged_sync as staged_tests
import staged_sync

class RowRestoreTests(unittest.TestCase):
    def test_restores_value_formula_and_style(self):
        baseline=fixture('4',1,formula='2+2');candidate=fixture('9',2)
        result=restore_row(candidate,baseline,'Main',1)
        self.assertIn('<v>4</v>',cell(result));self.assertIn('<f>2+2</f>',cell(result))
        self.assertEqual(style(result),style(baseline))

    def test_added_row_removed_without_shifting_neighbors(self):
        p=parts(fixture());xml=p['xl/worksheets/sheet1.xml']
        xml=xml.replace(b'</sheetData>',b'<row r="8"><c r="F8"><v>99</v></c></row><row r="9"><c r="A9"><v>8</v></c></row></sheetData>')
        p['xl/worksheets/sheet1.xml']=xml
        result=Book(restore_row(pack(p),fixture(),'Main',8)).cells('Main')
        self.assertNotIn('F8',result);self.assertIn('<v>8</v>',result['A9'].toxml())
        self.assertIn('A1',result)

    def test_deleted_row_restored_and_repeated_restore_is_safe(self):
        p=parts(fixture());p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData/></worksheet>').encode()
        result=restore_row(pack(p),fixture('4',1),'Main',1)
        self.assertIn('<v>4</v>',cell(result));self.assertEqual(style(result),style(fixture('4',1)))
        self.assertEqual(cell(restore_row(result,fixture('4',1),'Main',1)),cell(result))

    def test_shared_string_indexes_are_translated(self):
        def shared(text):
            p=parts(fixture());p['xl/sharedStrings.xml']=(f'<sst xmlns="{NS}"><si><t>{text}</t></si></sst>').encode()
            p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>').encode()
            return pack(p)
        result=restore_row(shared('candidate'),shared('release'),'Main',1)
        self.assertIn('release',cell(result));self.assertNotIn('candidate',cell(result))

    def test_replacing_shared_formula_master_keeps_other_row_formula(self):
        p=parts(fixture());p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f t="shared" si="0" ref="A1:A2">B1+1</f><v>3</v></c></row><row r="2"><c r="A2"><f t="shared" si="0"/><v>4</v></c></row></sheetData></worksheet>').encode()
        result=Book(restore_row(pack(p),fixture('5'),'Main',1)).cells('Main')
        self.assertIn('<f>B2+1</f>',result['A2'].toxml())
        self.assertIn('<v>5</v>',result['A1'].toxml())

    def test_invalid_rows_rejected(self):
        for row in (None,0,-1,1048577):
            with self.assertRaises(ValueError):restore_row(fixture(),fixture(),'Main',row)

class RowWithdrawTests(unittest.TestCase):
    setUp=staged_tests.StagedSyncTests.setUp
    tearDown=staged_tests.StagedSyncTests.tearDown
    commit=staged_tests.StagedSyncTests.commit
    report_files=staged_tests.StagedSyncTests.report_files
    start=staged_tests.StagedSyncTests.start

    def prepare(self):
        self.commit(self.dev,'book.xlsx',fixture('1'),'seed')
        self.commit(self.target,'book.xlsx',fixture('1'),'release')
        self.commit(self.dev,'book.xlsx',fixture('3'),'sample.author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        return core,entry

    def test_edit_changes_only_candidate_and_confirmation_uses_updated_hash(self):
        core,entry=self.prepare();oldhash=entry['candidateHash']
        original=(self.target/'book.xlsx').read_bytes()
        updated=staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)
        self.assertNotEqual(updated['candidateHash'],oldhash)
        self.assertIn('<v>1</v>',cell(pathlib.Path(updated['candidate']).read_bytes()))
        self.assertEqual((self.target/'book.xlsx').read_bytes(),original)
        self.assertTrue(list((self.folder/'撤回前副本').rglob('*.xlsx')))
        staged_sync.operate(core,self.folder,'accept','book.xlsx')
        self.assertIn('<v>1</v>',cell((self.target/'book.xlsx').read_bytes()))

    def test_tampered_candidate_cannot_be_edited(self):
        core,entry=self.prepare();pathlib.Path(entry['candidate']).write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError,'副本已被修改'):
            staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)

    def test_skipped_candidate_cannot_be_edited(self):
        core,entry=self.prepare();staged_sync.operate(core,self.folder,'defer','book.xlsx')
        with self.assertRaisesRegex(RuntimeError,'不能编辑'):
            staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)

    def test_withdraw_restore_and_withdraw_again(self):
        core,entry=self.prepare();original=(self.target/'book.xlsx').read_bytes()
        for expected in ('1','3','1','3'):
            updated=staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)
            self.assertIn('<v>'+expected+'</v>',cell(pathlib.Path(updated['candidate']).read_bytes()))
            self.assertEqual(bool(updated['withdrawnRows']),expected=='1')
            self.assertEqual((self.target/'book.xlsx').read_bytes(),original)

    def test_restore_rejects_tampered_backup(self):
        core,entry=self.prepare()
        updated=staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)
        for backup in (self.folder/'撤回前副本').rglob('*.xlsx'):backup.write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError,'备份已改变'):
            staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)

    def test_legacy_withdrawal_can_be_restored(self):
        import json
        core,entry=self.prepare()
        staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)
        path=self.folder/'review.json';state=json.loads(path.read_text())
        state['items']['book.xlsx']['withdrawnRows'][0].pop('backupHash');path.write_text(json.dumps(state))
        updated=staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=1)
        self.assertIn('<v>3</v>',cell(pathlib.Path(updated['candidate']).read_bytes()))

    def test_restoring_one_row_keeps_other_row_withdrawn(self):
        def two(a,b):
            p=parts(fixture(a));p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</sheetData>',f'<row r="2"><c r="A2"><v>{b}</v></c></row></sheetData>'.encode());return pack(p)
        self.commit(self.dev,'book.xlsx',two('1','2'),'seed')
        self.commit(self.target,'book.xlsx',two('1','2'),'release')
        self.commit(self.dev,'book.xlsx',two('3','4'),'sample.author')
        core=self.start();staged_sync.operate(core,self.folder,'stage','book.xlsx')
        for row in (1,2,1):updated=staged_sync.operate(core,self.folder,'withdraw-row','book.xlsx',sheet='Main',row=row)
        cells=Book(pathlib.Path(updated['candidate']).read_bytes()).cells('Main')
        self.assertIn('<v>3</v>',cells['A1'].toxml());self.assertIn('<v>2</v>',cells['A2'].toxml())
        self.assertEqual([v['row'] for v in updated['withdrawnRows']],[2])
