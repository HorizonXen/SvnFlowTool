"""Regression tests for foreign content sharing an authored cell or field."""
import json
import pathlib
import unittest
from test_workbook import book, parts, pack, NS
from file_sync import merge_data, merge_properties
from workbook_cells import Book
import lua_sync
import test_staged_sync as staged_tests
import staged_sync


def fixture(value='1', style=0, formula=None, text=False):
    p=parts(book(a=value,formula=False))
    p['xl/styles.xml']=(f'<styleSheet xmlns="{NS}"><fonts count="3"><font/><font><b/></font><font><i/></font></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellXfs count="3">'+''.join(f'<xf fontId="{i}" fillId="0" borderId="0" numFmtId="0"/>' for i in range(3))+'</cellXfs></styleSheet>').encode()
    cell=f'<c r="A1" s="{style}"'+(' t="inlineStr"' if text else '')+'>'
    if formula is not None:cell+='<f>'+formula+'</f>'
    cell+=('<is><t>'+value+'</t></is>' if text else '<v>'+value+'</v>')+'</c>'
    p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1">'+cell+'<c r="B1"><v>2</v></c></row></sheetData></worksheet>').encode()
    return pack(p)


def merged(a,b,t):return merge_data(a,b,t,'book.xlsx',latest=True,history=[b])
def cell(data):return Book(data).cells('Main')['A1'].toxml()
def style(data):
    parsed=Book(data);return parsed.cell_value(parsed.cells('Main')['A1'])[1]


class AuthorIsolationTests(unittest.TestCase):
    def test_value_change_does_not_copy_foreign_style(self):
        a,b,t=fixture('1',1),fixture('2',1),fixture('1',0)
        result=merged(a,b,t)
        self.assertIn('<v>2</v>',cell(result));self.assertEqual(style(result),style(t))

    def test_style_change_does_not_copy_foreign_value(self):
        a,b,t=fixture('99',0),fixture('99',1),fixture('7',0)
        result=merged(a,b,t)
        self.assertIn('<v>7</v>',cell(result));self.assertEqual(style(result),style(b))

    def test_formula_change_does_not_copy_untouched_cached_value(self):
        a,b,t=fixture('99',formula='1+1'),fixture('99',formula='2+2'),fixture('2',formula='1+1')
        result=merged(a,b,t)
        self.assertIn('<f>2+2</f>',cell(result));self.assertIn('<v>2</v>',cell(result))

    def test_cached_value_cannot_import_foreign_formula(self):
        a,b,t=fixture('4',formula='2+2'),fixture('5',formula='2+2'),fixture('2',formula='1+1')
        self.assertEqual(cell(merged(a,b,t)),cell(t))

    def test_authored_style_wins_overlap(self):
        self.assertEqual(style(merged(fixture('1',1),fixture('1',2),fixture('1',0))),style(fixture('1',2)))

    def test_authored_string_uses_latest_whole_cell(self):
        result=merged(fixture('foreign old',text=True),fixture('foreign new',text=True),fixture('release old',text=True))
        self.assertIn('foreign new',cell(result))

    def test_lua_authored_string_uses_latest_field(self):
        result=lua_sync.merge(b'local data={name="foreign old"}',b'local data={name="foreign new"}',b'local data={name="release old"}',True)
        self.assertIn(b'foreign new',result)

    def test_property_synthesis_does_not_copy_unmodified_foreign_field(self):
        result=merge_properties({'value':b'a=1 b=99'},{'value':b'a=2 b=99'},{'value':b'a=0 b=0'},latest=True)
        self.assertEqual(result['value'],b'a=2 b=0')

    def test_authored_formula_uses_latest_whole_formula(self):
        result=merged(fixture('2',formula='A1+B1'),fixture('2',formula='A1+C1'),fixture('2',formula='A2+B1'))
        self.assertIn('<f>A1+C1</f>',cell(result))

    def test_lua_missing_table_does_not_import_existing_foreign_fields(self):
        result=lua_sync.merge(b'local data={row={foreign=99,a=1}}',b'local data={row={foreign=99,a=2}}',b'local data={}',True)
        self.assertIn(b'a = 2',result);self.assertNotIn(b'foreign',result)

    def test_structure_attribute_change_keeps_release_text(self):
        from workbook_cells import DOM,merge_structure
        a,b,t=[DOM.parseString(v).documentElement for v in ('<formula1 flag="0">foreign</formula1>','<formula1 flag="1">foreign</formula1>','<formula1 flag="0">release</formula1>')]
        result=merge_structure(a,b,t,True).toxml()
        self.assertIn('flag="1"',result);self.assertIn('release',result);self.assertNotIn('foreign',result)

    def test_missing_target_cell_does_not_restore_foreign_style(self):
        from workbook_cells import DOM
        local=parts(fixture('1',0));document=DOM.parseString(local['xl/worksheets/sheet1.xml'])
        old=document.getElementsByTagNameNS(NS,'c')[0];old.parentNode.removeChild(old)
        local['xl/worksheets/sheet1.xml']=document.toxml(encoding='utf-8')
        result=merged(fixture('1',1),fixture('2',1),pack(local))
        self.assertIn('<v>2</v>',cell(result));self.assertEqual(style(result),style(fixture('2',0)))

    def test_authored_formula_can_replace_missing_target_formula(self):
        result=merged(fixture('2',formula='A1+B1'),fixture('2',formula='A1+C1'),fixture('2'))
        self.assertIn('<f>A1+C1</f>',cell(result))


    def test_font_changes_preserve_release_fill_and_unmodified_font_size(self):
        def custom(font,fill):
            p=parts(fixture())
            p['xl/styles.xml']=(f'<styleSheet xmlns="{NS}"><fonts count="1"><font>{font}</font></fonts>'
                f'<fills count="1"><fill><patternFill patternType="solid"><fgColor rgb="{fill}"/></patternFill></fill></fills>'
                '<borders count="1"><border/></borders><cellXfs count="1"><xf fontId="0" fillId="0" borderId="0" numFmtId="0"/></cellXfs></styleSheet>').encode()
            return pack(p)
        a=custom('<sz val="11"/><color rgb="FFFF0000"/>','FFFF0000')
        b=custom('<sz val="11"/><color rgb="FF00FF00"/>','FFFF0000')
        t=custom('<sz val="20"/><color rgb="FF0000FF"/>','FFFFFF00')
        result=merged(a,b,t)
        self.assertEqual(style(result),style(custom('<sz val="20"/><color rgb="FF00FF00"/>','FFFFFF00')))

    def test_missing_style_property_applies_only_authored_attributes(self):
        from workbook_cells import DOM,merge_structure
        a,b,t=[DOM.parseString(v).documentElement for v in ('<font><color rgb="red"/></font>','<font><color rgb="green"/></font>','<font/>')]
        result=merge_structure(a,b,t,True,allow_missing=True).toxml()
        self.assertIn('rgb="green"',result)

    def test_deleted_cell_removes_release_conflict_but_keeps_neighbor(self):
        from workbook_cells import DOM
        a=fixture('1',1);p=parts(a);doc=DOM.parseString(p['xl/worksheets/sheet1.xml'])
        old=doc.getElementsByTagNameNS(NS,'c')[0];old.parentNode.removeChild(old)
        p['xl/worksheets/sheet1.xml']=doc.toxml(encoding='utf-8')
        result=Book(merged(a,pack(p),fixture('9',2))).cells('Main')
        self.assertNotIn('A1',result);self.assertIn('B1',result)


class StagedAuthorIsolationTests(unittest.TestCase):
    setUp=staged_tests.StagedSyncTests.setUp
    tearDown=staged_tests.StagedSyncTests.tearDown
    commit=staged_tests.StagedSyncTests.commit
    report_files=staged_tests.StagedSyncTests.report_files
    start=staged_tests.StagedSyncTests.start

    def test_interleaved_authors_share_cell_without_style_leak(self):
        self.commit(self.dev,'book.xlsx',fixture('1',0),'seed')
        self.commit(self.target,'book.xlsx',fixture('1',0),'release')
        self.commit(self.dev,'book.xlsx',fixture('1',1),'other-author')
        self.commit(self.dev,'book.xlsx',fixture('2',1),'sample.author')
        core=self.start()
        entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=pathlib.Path(entry['candidate']).read_bytes()
        self.assertIn('<v>2</v>',cell(result));self.assertEqual(style(result),style(fixture('1',0)))
        self.assertEqual(entry['authorIsolation'],staged_sync.AUTHOR_ISOLATION_VERSION)
        self.assertIn('<v>1</v>',cell((self.target/'book.xlsx').read_bytes()))

    def test_old_candidate_cannot_be_confirmed(self):
        core=self.start();staged_sync.operate(core,self.folder,'stage','a.txt')
        ledger=json.loads((self.folder/'review.json').read_text())
        ledger['items']['a.txt'].pop('authorIsolation')
        core.write_json(self.folder/'review.json',ledger)
        with self.assertRaisesRegex(RuntimeError,'旧版作者隔离规则'):staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual(core.fingerprint(str(self.target)),[])


    def test_latest_dev_value_includes_later_other_author_only_at_touched_cell(self):
        self.commit(self.dev,'book.xlsx',book(a='1',b='2',formula=False),'seed')
        self.commit(self.target,'book.xlsx',book(a='9',b='8',formula=False),'release')
        self.commit(self.dev,'book.xlsx',book(a='3',b='2',formula=False),'sample.author')
        self.commit(self.dev,'book.xlsx',book(a='99',b='99',formula=False),'other-author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=Book(pathlib.Path(entry['candidate']).read_bytes()).cells('Main')
        self.assertIn('<v>99</v>',result['A1'].toxml());self.assertIn('<v>8</v>',result['B1'].toxml())
        self.assertIn('<v>9</v>',cell((self.target/'book.xlsx').read_bytes()))

    def test_author_revert_overwrites_release_even_when_net_diff_is_empty(self):
        self.commit(self.dev,'book.xlsx',fixture('1',0),'seed')
        self.commit(self.target,'book.xlsx',fixture('9',2),'release')
        self.commit(self.dev,'book.xlsx',fixture('3',1),'sample.author')
        self.commit(self.dev,'book.xlsx',fixture('1',0),'sample.author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=pathlib.Path(entry['candidate']).read_bytes()
        self.assertIn('<v>1</v>',cell(result))
        # Author removed bold; Release's independent italic remains.
        self.assertEqual(style(result),style(fixture('1',2)))

    def test_each_touched_position_uses_dev_snapshot(self):
        self.commit(self.dev,'book.xlsx',book(a='1',b='2',formula=False),'seed')
        self.commit(self.target,'book.xlsx',book(a='9',b='8',formula=False),'release')
        self.commit(self.dev,'book.xlsx',book(a='3',b='2',formula=False),'sample.author')
        self.commit(self.dev,'book.xlsx',book(a='99',b='99',formula=False),'other-author')
        self.commit(self.dev,'book.xlsx',book(a='99',b='4',formula=False),'sample.author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=Book(pathlib.Path(entry['candidate']).read_bytes()).cells('Main')
        self.assertIn('<v>99</v>',result['A1'].toxml());self.assertIn('<v>4</v>',result['B1'].toxml())

    def test_user_example_and_later_author_edit(self):
        for path in ('value.txt', 'value.lua', 'value.xlsx'):
            def data(a,b):
                if path.endswith('.xlsx'): return book(a=str(a),b=str(b),formula=False)
                if path.endswith('.lua'): return ('return {a='+str(a)+', b='+str(b)+'}').encode()
                return ('a='+str(a)+' b='+str(b)+'\n').encode()
            self.commit(self.dev,path,data(1000,2),'seed')
            self.commit(self.target,path,data(900,8),'release')
            self.commit(self.dev,path,data(500,2),'sample.author')
            self.commit(self.dev,path,data(1200,99),'other-author')
            core=self.start();entry=staged_sync.operate(core,self.folder,'stage',path)
            result=pathlib.Path(entry['candidate']).read_bytes()
            from file_sync import same_data
            self.assertTrue(same_data(result,data(1200,8),path),path)
            self.commit(self.dev,path,data(1500,99),'sample.author')
            core=self.start();entry=staged_sync.operate(core,self.folder,'stage',path)
            self.assertTrue(same_data(pathlib.Path(entry['candidate']).read_bytes(),data(1500,8),path),path)

    def test_other_author_reverts_to_original_value(self):
        self.commit(self.dev,'book.xlsx',book(a='1000',b='2',formula=False),'seed')
        self.commit(self.target,'book.xlsx',book(a='900',b='8',formula=False),'release')
        self.commit(self.dev,'book.xlsx',book(a='500',b='2',formula=False),'sample.author')
        self.commit(self.dev,'book.xlsx',book(a='1000',b='99',formula=False),'other-author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=Book(pathlib.Path(entry['candidate']).read_bytes()).cells('Main')
        self.assertIn('<v>1000</v>',result['A1'].toxml());self.assertIn('<v>8</v>',result['B1'].toxml())

    def test_later_style_change_does_not_leak_with_latest_value(self):
        self.commit(self.dev,'book.xlsx',fixture('1000',0),'seed')
        self.commit(self.target,'book.xlsx',fixture('900',0),'release')
        self.commit(self.dev,'book.xlsx',fixture('500',0),'sample.author')
        self.commit(self.dev,'book.xlsx',fixture('1200',1),'other-author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','book.xlsx')
        result=pathlib.Path(entry['candidate']).read_bytes()
        self.assertIn('<v>1200</v>',cell(result));self.assertEqual(style(result),style(fixture('900',0)))

    def test_dev_values_are_pinned_to_generation_snapshot(self):
        self.commit(self.dev,'value.txt',b'a=1000 b=2\n','seed')
        self.commit(self.target,'value.txt',b'a=900 b=8\n','release')
        self.commit(self.dev,'value.txt',b'a=500 b=2\n','sample.author')
        self.commit(self.dev,'value.txt',b'a=1200 b=99\n','other-author')
        core=self.start()
        self.commit(self.dev,'value.txt',b'a=1500 b=99\n','other-author')
        entry=staged_sync.operate(core,self.folder,'stage','value.txt')
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(),b'a=1500 b=8\n')

    def test_latest_property_value_preserves_unselected_property(self):
        from test_sync import sync
        def prop(wc,key,value,author):
            sync.run('propset',key,value,str(wc/'a.txt'))
            sync.run('commit',wc,'-m','property change','--username',author)
        prop(self.dev,'value','1000','seed')
        prop(self.target,'value','900','release')
        prop(self.target,'untouched','release','release')
        prop(self.dev,'value','500','sample.author')
        prop(self.dev,'value','1200','other-author')
        prop(self.dev,'untouched','foreign','other-author')
        core=self.start();entry=staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual(staged_sync.decoded(entry['properties']),{'value':b'1200','untouched':b'release'})
