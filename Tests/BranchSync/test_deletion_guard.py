import unittest
import pathlib
import json
from unittest.mock import patch
from test_config_identity import table, values
from test_workbook import book, parts, pack
from test_galaxy_sync import asset
from test_latest_scope import latest
import deletion_guard as guard
import test_staged_sync as staged_tests
import staged_sync


class DeletionGuardTests(unittest.TestCase):
    def duplicate_table(self, tail=9):
        return table([(6,dict(ID=':',value=1)),(7,dict(ID=':',value=2)),
                      (8,dict(ID=100,value=tail))])

    def test_reserialized_duplicate_page_has_no_deletion(self):
        a=self.duplicate_table();p=parts(a)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(
            b'<is><t>:</t></is>',b'<is><t xml:space="preserve">:</t></is>')
        p['xl/sharedStrings.xml']=b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>unused</t></si></sst>'
        self.assertEqual(guard.check(a,pack(p),a,'config.xlsx')['removedIdentities'],0)

    def test_formatting_only_duplicate_page_has_no_deletion(self):
        a=self.duplicate_table();p=parts(a)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'r="B6"',b'r="B6" s="1"')
        self.assertEqual(guard.check(a,pack(p),a,'config.xlsx')['removedIdentities'],0)

    def test_shared_string_values_are_resolved_before_no_deletion_proof(self):
        a=self.duplicate_table();p=parts(a)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(
            b't="inlineStr"><is><t>:</t></is>',b't="s"><v>0</v>')
        p['xl/sharedStrings.xml']=b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>:</t></si></sst>'
        b=pack(p)
        self.assertEqual(guard.check(a,b,a,'config.xlsx')['removedIdentities'],0)
        p['xl/sharedStrings.xml']=p['xl/sharedStrings.xml'].replace(b'<t>:</t>',b'<t>changed</t>')
        with self.assertRaisesRegex(ValueError,'ID 重复'):
            guard.check(b,pack(p),a,'config.xlsx')

    def test_unchanged_duplicate_group_does_not_block_other_record(self):
        a=self.duplicate_table();b=self.duplicate_table(10)
        self.assertEqual(guard.check(a,b,b,'config.xlsx')['removedIdentities'],0)

    def test_unchanged_duplicate_group_does_not_hide_restored_record(self):
        a=self.duplicate_table();b=table([(6,dict(ID=':',value=1)),(7,dict(ID=':',value=2))])
        with self.assertRaisesRegex(ValueError,'删除保护.*100'):
            guard.check(a,b,a,'config.xlsx')
        self.assertEqual(guard.check(a,b,b,'config.xlsx')['status'],'passed')

    def test_changed_or_removed_duplicate_cannot_use_unchanged_group_proof(self):
        a=self.duplicate_table()
        for rows in ([(6,dict(ID=':',value=1)),(7,dict(ID=':'))],
                     [(6,dict(ID=':',value=1))],
                     [(6,dict(ID=':',value=2)),(7,dict(ID=':',value=1))]):
            b=table(rows+[(8,dict(ID=100,value=9))])
            with self.subTest(rows=rows),self.assertRaisesRegex(ValueError,'ID 重复'):
                guard.check(a,b,a,'config.xlsx')

    def test_formula_clear_is_not_a_formatting_only_change(self):
        a=self.duplicate_table();p=parts(a)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<v>1</v>',b'<f>1+0</f><v>1</v>')
        a=pack(p)
        b=table([(6,dict(ID=':')),(7,dict(ID=':',value=2)),(8,dict(ID=100,value=9))])
        with self.assertRaisesRegex(ValueError,'ID 重复'):guard.check(a,b,a,'config.xlsx')

    def test_old_row_deletion_is_rejected_after_other_author_restores_id(self):
        release=table([(6,dict(ID=100,value=9)),(7,dict(ID=200,value=8))])
        broken=table([(7,dict(ID=200,value=8))])
        dev=table([(20,dict(ID=100,value=12)),(9,dict(ID=200,value=99))],('ID','other','value'))
        with self.assertRaisesRegex(ValueError,'删除保护.*100'):
            guard.check(release,broken,dev,'config.xlsx')

    def test_latest_scope_restoration_keeps_id_and_release_only_cells(self):
        a=table([(6,dict(ID=100,value=1,other=2))])
        removed=table([])
        dev=table([(16,dict(ID=100,value=12,other=2))])
        release=table([(30,dict(ID=100,value=1,other=2)),(31,dict(ID=200,value=7))])
        result=latest(a,removed,dev,release)
        self.assertEqual(values(result)['A30'],'100');self.assertEqual(values(result)['B30'],'12')
        self.assertEqual(values(result)['B31'],'7')
        guard.check(release,result,dev,'config.xlsx')

    def test_restored_cell_cannot_be_cleared(self):
        a=table([(6,dict(ID=100,value=1,other=2))]);b=table([(6,dict(ID=100,other=2))])
        dev=table([(16,dict(ID=100,value=12,other=9))])
        with self.assertRaisesRegex(ValueError,'删除保护.*value'):guard.check(a,b,dev,'config.xlsx')

    def test_actual_dev_deletion_remains_allowed(self):
        a=table([(6,dict(ID=100,value=1)),(7,dict(ID=200,value=8))]);b=table([(7,dict(ID=200,value=8))]);dev=table([(12,dict(ID=200,value=99))])
        self.assertEqual(guard.check(a,b,dev,'config.xlsx')['status'],'passed')

    def test_zero_and_false_are_data_not_empty(self):
        for value in (0,'false'):
            a=table([(6,dict(ID=100,value=value))]);b=table([(6,dict(ID=100))])
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'删除保护'):guard.check(a,b,a,'config.xlsx')

    def test_deleted_sheet_still_in_dev_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'工作表 DeleteMe'):guard.check(book(),book(extra=False),book(),'config.xlsx')
        guard.check(book(),book(extra=False),book(extra=False),'config.xlsx')

    def test_formula_to_value_does_not_count_as_clear(self):
        guard.check(book(formula=True),book(formula=False),book(formula=False),'config.xlsx')

    def test_compound_keys_distinguish_restored_records(self):
        fields=('ID','**Level','value')
        a=table([(6,{'ID':1,'**Level':1,'value':10}),(7,{'ID':1,'**Level':2,'value':20})],fields)
        b=table([(7,{'ID':1,'**Level':2,'value':20})],fields)
        with self.assertRaisesRegex(ValueError,'删除保护'):guard.check(a,b,a,'config.xlsx')
        guard.check(a,b,b,'config.xlsx')

    def test_row_and_column_moves_do_not_look_like_deletion(self):
        a=table([(6,dict(ID=100,value=1,other=2))]);b=table([(30,dict(ID=100,value=1,other=2))],('ID','other','value'))
        guard.check(a,b,a,'config.xlsx')

    def test_duplicate_id_blocks_inventory(self):
        a=table([(6,dict(ID=100,value=1))]);b=table([(6,dict(ID=100))]);dev=table([(6,dict(ID=100,value=1)),(7,dict(ID=100,value=2))])
        with self.assertRaisesRegex(ValueError,'ID 重复'):guard.check(a,b,dev,'config.xlsx')

    def test_lua_object_and_field_restoration(self):
        a=b'return {[100]={reward=1},[200]={reward=2}}';b=b'return {[200]={reward=2}}'
        with self.assertRaisesRegex(ValueError,'删除保护.*100'):guard.check(a,b,a,'config.lua')
        guard.check(a,b,b,'config.lua')
        with self.assertRaisesRegex(ValueError,'删除保护'):guard.check(a,b'return {[100]={},[200]={reward=2}}',a,'config.lua')

    def test_non_configuration_lua_keeps_file_level_protection(self):
        result=guard.check(b'print("before")',b'print("after")',b'print("after")','script.lua')
        self.assertEqual(result['kind'],'file')
        with self.assertRaisesRegex(ValueError,'删除保护'):
            guard.check(b'return {[100]={reward=1}}',b'print("after")',b'return {[100]={reward=1}}','config.lua')

    def test_galaxy_restored_adventure_is_rejected(self):
        a=asset((100,1,2,'beacon'),(200,3,4,'reward'));b=asset((200,3,4,'reward'))
        with self.assertRaisesRegex(ValueError,'删除保护.*100'):guard.check(a,b,a,'Client/Config/Galaxy/52101.asset')
        guard.check(a,b,b,'Client/Config/Galaxy/52101.asset')

    def test_file_and_property_restoration(self):
        with self.assertRaisesRegex(ValueError,'整个文件'):guard.check(b'old',None,b'restored','file.txt')
        guard.check(b'old',None,None,'file.txt')
        with self.assertRaisesRegex(ValueError,'SVN 属性'):guard.check_properties({'a':b'1'},{},{'a':b'2'},'file.txt')


class AcceptanceGuardTests(unittest.TestCase):
    setUp=staged_tests.StagedSyncTests.setUp
    tearDown=staged_tests.StagedSyncTests.tearDown
    commit=staged_tests.StagedSyncTests.commit
    report_files=staged_tests.StagedSyncTests.report_files
    start=staged_tests.StagedSyncTests.start

    def test_dev_changes_after_stage_blocks_before_any_write(self):
        core=self.start();staged_sync.operate(core,self.folder,'stage','a.txt');original=(self.target/'a.txt').read_bytes()
        self.commit(self.dev,'a.txt',b'one\nrestored by other\nthree\n','other-author')
        with self.assertRaisesRegex(RuntimeError,'Dev 最新内容'):
            staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),original)
        self.assertFalse(json.loads((self.folder/'review.json').read_text()).get('pending'))
        self.assertFalse((self.folder/'本地原件').exists())

    def test_old_candidate_without_guard_is_not_accepted(self):
        core=self.start();staged_sync.operate(core,self.folder,'stage','a.txt');ledger=json.loads((self.folder/'review.json').read_text())
        ledger['items']['a.txt'].pop('deletionGuardVersion');core.write_json(self.folder/'review.json',ledger)
        with self.assertRaisesRegex(RuntimeError,'删除保护规则已更新'):staged_sync.operate(core,self.folder,'accept','a.txt')

    def test_guard_catches_faulty_generator_independently(self):
        a=table([(6,dict(ID=100,value=1))]);self.commit(self.dev,'config.xlsx',a,'seed');self.commit(self.target,'config.xlsx',a,'release')
        self.commit(self.dev,'config.xlsx',table([(6,dict(ID=100,value=2))]))
        core=self.start();import file_sync
        with patch('workbook_cells.WorkbookReplay.finish',return_value=table([])):
            with self.assertRaisesRegex(ValueError,'删除保护'):staged_sync.operate(core,self.folder,'stage','config.xlsx')
        self.assertEqual((self.target/'config.xlsx').read_bytes(),a)

    def test_acceptance_rechecks_edited_candidate_for_restored_excel_id(self):
        a=table([(6,dict(ID=100,value=1))]);self.commit(self.dev,'config.xlsx',a,'seed');self.commit(self.target,'config.xlsx',a,'release')
        self.commit(self.dev,'config.xlsx',table([(6,dict(ID=100,value=2))]))
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','config.xlsx')
        broken=table([]);pathlib.Path(entry['candidate']).write_bytes(broken)
        ledger=json.loads((self.folder/'review.json').read_text());ledger['items']['config.xlsx']['candidateHash']=__import__('hashlib').sha256(broken).hexdigest();core.write_json(self.folder/'review.json',ledger)
        with self.assertRaisesRegex(ValueError,'删除保护'):staged_sync.operate(core,self.folder,'accept','config.xlsx')
        self.assertEqual((self.target/'config.xlsx').read_bytes(),a)
