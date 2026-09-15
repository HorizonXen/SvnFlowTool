import unittest
import sys,pathlib,io,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from lua_sync import merge,parse
from workbook_cells import patch,Book
from test_workbook import book,parts,pack,NS

class SemanticTests(unittest.TestCase):
    def test_lua_add_delete_preserve_other_object_format(self):
        before=b'return {a={x=1},b={x=2}}'
        after=b'return {a={x=3},c={x=4}}'
        local=b'return {\n    a = {\n        x=1 -- keep\n    },\n    b = {x=2},\n    release = 99,\n}\n'
        result=merge(before,after,local,True)
        self.assertIn(b'a = {\n        x=3 -- keep\n    }',result)
        self.assertIn(b'    release = 99,',result)
        self.assertEqual(parse(result)[1].value(),parse(b'return {a={x=3},c={x=4},release=99}')[1].value())

    def test_lua_value_change_preserves_release_format_and_comments(self):
        before = b'return {a = {x=1,y=2}, b=9}'
        after = b'return {a = {x=3,y=2}, b=9}'
        local = 'return {\n    -- 注释\n    a = {\n        x=1, -- 坐标\n        y=2;\n    },\n    b=99,\n}\n'.encode()
        self.assertEqual(merge(before,after,local,True),local.replace(b'x=1',b'x=3'))

    def test_lua_keys_keep_unrelated_release_fields_and_rows(self):
        base=b'local data = {[1]={x=-1,y=-20},[2]={reward=4}}\nreturn data'
        source=b'local data = {[1]={x=2,y=-20},[2]={reward=7}}\nreturn data'
        local=b'local data = {[0]={extra=8},[1]={x=9,y=0},[2]={reward=5}}\nreturn data'
        result=parse(merge(base,source,local,True))[1].value()
        self.assertEqual(result[('index','0')],{('name','extra'):'8'})
        self.assertEqual(result[('index','1')],{('name','x'):'2',('name','y'):'0'})
        self.assertEqual(result[('index','2')],{('name','reward'):'7'})
    def test_lua_does_not_execute_expressions(self):
        with self.assertRaises(ValueError):parse(b'local data = {x=os.execute("bad")}')
    def test_lua_synthesis_excludes_other_author(self):
        result=merge(b'local data={a=3,b=99}',b'local data={a=7,b=99}',b'local data={a=1,b=0}',True)
        self.assertEqual(parse(result)[1].value(),{('name','a'):'7',('name','b'):'0'})
    def test_excel_formula_values_sheet_delete_preserve_release(self):
        before=book(a='3');after=book(a='7',formula=False,extra=False);local=book(a='5',b='99')
        result,notes=patch(before,after,local,True)
        p=parts(result);self.assertNotIn('xl/worksheets/sheet2.xml',p)
        self.assertIn(b'<v>7</v>',p['xl/worksheets/sheet1.xml']);self.assertIn(b'<v>99</v>',p['xl/worksheets/sheet1.xml']);self.assertNotIn(b'<f',p['xl/worksheets/sheet1.xml'])
    def test_excel_formula_shared_translation(self):
        from workbook_cells import translate
        self.assertEqual(translate('SUM(A1,$B1,C$1,$D$1)+"A1"','A1','B2'),'SUM(B2,$B2,D$1,$D$1)+"A1"')
    def test_excel_shared_strings_and_styles_are_remapped(self):
        def fixture(value,other,reverse=False,bold=False):
            p=parts(book(formula=False));strings=[value,other] if not reverse else [other,value]
            p['xl/sharedStrings.xml']=(f'<sst xmlns="{NS}">'+''.join('<si><t>'+v+'</t></si>' for v in strings)+'</sst>').encode()
            p['xl/styles.xml']=(f'<styleSheet xmlns="{NS}"><fonts count="2"><font><name val="Arial"/></font><font><b/><name val="Arial"/></font></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf fontId="0" fillId="0" borderId="0" numFmtId="0"/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" numFmtId="0" xfId="0"/><xf fontId="1" fillId="0" borderId="0" numFmtId="0" xfId="0"/></cellXfs></styleSheet>').encode()
            p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="s" s="{int(bold)}"><v>{int(reverse)}</v></c><c r="B1" t="s"><v>{int(not reverse)}</v></c></row></sheetData></worksheet>').encode()
            return pack(p)
        a=fixture('old','foreign');b=fixture('author','foreign',True);local=fixture('release','keep',bold=True)
        result,_=patch(a,b,local,True);out=Book(result);cells=out.cells('Main')
        self.assertIn('author',cells['A1'].toxml());self.assertIn('keep',cells['B1'].toxml())
        self.assertEqual(out.cell_value(cells['A1'])[1],Book(local).cell_value(Book(local).cells('Main')['A1'])[1])
    def test_sheet_deleted_by_release_is_not_restored_for_unchanged_source(self):
        result,_=patch(book(),book(a='7',formula=False),book(extra=False),True)
        self.assertNotIn('DeleteMe',Book(result).sheets)
    def test_formula_to_value_keeps_shared_followers_valid(self):
        p=parts(book(formula=False))
        p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f t="shared" si="0" ref="A1:B1">1+1</f><v>2</v></c><c r="B1"><f t="shared" si="0"/><v>2</v></c></row></sheetData></worksheet>').encode()
        before=pack(p)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<f t="shared" si="0" ref="A1:B1">1+1</f><v>2</v>',b'<v>3</v>').replace(b'<f t="shared" si="0"/>',b'<f>1+1</f>')
        result,_=patch(before,pack(p),before,True)
        xml=parts(result)['xl/worksheets/sheet1.xml']
        self.assertNotIn(b't="shared"',xml);self.assertIn(b'<f>1+1</f>',xml);Book(result).cells('Main')
    def test_empty_shared_string_cell_is_valid(self):
        from workbook_cells import logical_signature
        p=parts(book(formula=False));p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B1"><v>2</v></c>',b'<c r="B1" t="s"/>')
        local=pack(p);logical_signature(local)
        result,_=patch(book(formula=False),book(a='7',formula=False),local,True)
        self.assertIn(b'<v>7</v>',parts(result)['xl/worksheets/sheet1.xml'])
    def test_single_cell_array_paste_value_preserves_unrelated_release(self):
        def array(scope,other='2'):
            p=parts(book(b=other))
            p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<f>1+1</f>',f'<f t="array" ref="{scope}">1+1</f>'.encode())
            return pack(p)
        before=array('A1');after=book(a='7',formula=False)
        result,_=patch(before,after,array('A1','99'),True)
        xml=parts(result)['xl/worksheets/sheet1.xml']
        self.assertNotIn(b'<f',xml);self.assertIn(b'<v>7</v>',xml);self.assertIn(b'<v>99</v>',xml)
        for source,target in [(array('A1:B1'),array('A1:B1')),(before,array('A1:B1'))]:
            with self.assertRaisesRegex(ValueError,'Main!A1.*完整依赖'):patch(source,after,target,True)

    def test_clear_metadata_reference_without_importing_source_indices(self):
        def metadata(value,index,other='2'):
            p=parts(book(a=value,b=other,formula=False))
            p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="A1">',f'<c r="A1" cm="{index}">'.encode())
            return pack(p)
        before=metadata('1','1');after=book(a='7',formula=False)
        result,_=patch(before,after,metadata('3','99','88'),True)
        xml=parts(result)['xl/worksheets/sheet1.xml']
        self.assertNotIn(b'cm=',xml);self.assertIn(b'<v>7</v>',xml);self.assertIn(b'<v>88</v>',xml)
        with self.assertRaisesRegex(ValueError,'元数据依赖'):
            patch(before,metadata('7','2'),metadata('3','99'),True)

    def test_formula_cache_is_not_an_authored_edit(self):
        from workbook_cells import logical_signature
        self.assertEqual(logical_signature(book(a='1')),logical_signature(book(a='3')))
        result,_=patch(book(a='1'),book(a='3'),book(a='1',b='9'),True)
        xml=parts(result)['xl/worksheets/sheet1.xml']
        self.assertIn(b'<v>1</v>',xml);self.assertIn(b'<v>9</v>',xml)
    def test_excel_conflict_requires_resolution(self):
        with self.assertRaises(ValueError):patch(book(a='1',formula=False),book(a='2',formula=False),book(a='3',formula=False))

if __name__=='__main__':unittest.main()
