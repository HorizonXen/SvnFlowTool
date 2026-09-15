"""Absent destination fields must distinguish empty OOXML cells from data."""
import unittest
from test_config_identity import table,values
from test_latest_scope import latest
from test_workbook import parts,pack
from file_sync import merge_data

class MissingFieldTests(unittest.TestCase):
    def inputs(self,value):
        a=table([])
        b=table([(6,dict(ID=1,value=2))])
        dev=table([(6,dict(ID=1,value=3,new=value,other=8))],('ID','new','value','other'))
        release=table([(6,dict(ID=2,value=90,other=70))])
        return a,b,dev,release

    def test_empty_foreign_field_on_added_record(self):
        a,b,d,t=self.inputs('')
        result=values(latest(a,b,d,t))
        self.assertEqual(result['A6'],'2')
        self.assertEqual(result['B6'],'90')
        self.assertEqual(result['C6'],'70')
        self.assertEqual(result['A7'],'1')
        self.assertEqual(result['B7'],'3')
        self.assertNotIn('D7',result)

    def test_nonempty_foreign_field_stays_blocked(self):
        for value in (0,8,' ','text'):
            with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'字段无法匹配'):
                latest(*self.inputs(value))

    def test_plain_and_style_only_empty_cells(self):
        for cell in (b'<c r="B6"/>',b'<c r="B6" s="0"/>',b'<c r="B6"><v/></c>'):
            with self.subTest(cell=cell):
                a,b,d,t=self.inputs('');p=parts(d)
                p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B6" t="inlineStr"><is><t></t></is></c>',cell)
                self.assertEqual(values(latest(a,b,pack(p),t))['B7'],'3')

    def test_empty_cells_with_metadata_or_extensions_stay_blocked(self):
        for cell in (b'<c r="B6" cm="1"/>',b'<c r="B6"><extLst/></c>'):
            with self.subTest(cell=cell):
                a,b,d,t=self.inputs('');p=parts(d)
                p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B6" t="inlineStr"><is><t></t></is></c>',cell)
                with self.assertRaisesRegex(RuntimeError,'字段无法匹配'):
                    latest(a,b,pack(p),t)

    def test_empty_result_formula_stays_blocked(self):
        a,b,d,t=self.inputs('');p=parts(d)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B6" t="inlineStr"><is><t></t></is></c>',b'<c r="B6"><f>IF(1=1,"",1)</f><v/></c>')
        with self.assertRaisesRegex(RuntimeError,'字段无法匹配'):
            latest(a,b,pack(p),t)

    def test_undeclared_empty_column_does_not_require_physical_match(self):
        a,b,_,t=self.inputs('')
        d=table([(6,{'ID':1,'value':3,'new':'','': ''})],('ID','new','value',''))
        self.assertEqual(values(latest(a,b,d,t))['B7'],'3')

    def test_empty_storage_does_not_require_an_untouched_missing_id(self):
        a=table([(6,dict(ID=1,value=10,other=''))])
        b=table([(6,dict(ID=1,value=10))])
        t=table([(6,dict(ID=2,value=99,other=8))])
        self.assertEqual(values(merge_data(a,b,t,'config.xlsx',latest=True)),values(t))
        changed=table([(6,dict(ID=1,value=11))])
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
            merge_data(a,changed,t,'config.xlsx',latest=True)
