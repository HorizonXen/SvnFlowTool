import unittest
from test_config_identity import table, values
from test_formula_freeze import formula
from test_workbook import parts,pack,NS
from workbook_cells import Book,first,patch
from test_keyless_auxiliary import auxiliary


def array(data,address,ref=None):
    from lxml import etree as E
    data=parts(data);root=E.fromstring(data['xl/worksheets/sheet1.xml']);q='{'+NS+'}'
    c=root.find('.//'+q+'c[@r="'+address+'"]');c.set('cm','1')
    f=c.find(q+'f');f.set('t','array');f.set('ref',ref or address)
    data['xl/worksheets/sheet1.xml']=E.tostring(root);return pack(data)


class FormulaProjectionTests(unittest.TestCase):
    def test_keyless_saved_empty_formula_is_not_a_scope_record(self):
        old=auxiliary([(9,{})],formula=(9,'','A9+1'))
        data=parts(old)
        data['xl/worksheets/sheet1.xml']=data['xl/worksheets/sheet1.xml'].replace(b'<c r="G9"><f>A9+1</f><v/></c>',b'<c r="G9" t="str"><f>A9+1</f><v/></c>')
        old=pack(data)
        literal=parts(old)
        literal['xl/worksheets/sheet1.xml']=literal['xl/worksheets/sheet1.xml'].replace(b'<c r="G9" t="str"><f>A9+1</f><v/></c>',b'<c r="G9" t="inlineStr"><is><t/></is></c>')
        literal=pack(literal)
        latest=auxiliary([(9,{'A':2,'E':99})])
        for a,b in [(old,literal),(literal,old)]:
            result,_=patch(a,b,latest,prefer_source=True,scope_projection=True)
            self.assertEqual(values(result),values(latest))
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):
            patch(literal,old,latest,prefer_source=True)

    def test_keyless_changed_literal_is_not_ignored_by_projection(self):
        old=auxiliary([(9,{'E':10})])
        old=formula(old,'E9','1+9')
        literal=auxiliary([(9,{'E':11})])
        latest=auxiliary([(9,{'A':2,'E':99})])
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):
            patch(literal,old,latest,prefer_source=True,scope_projection=True)

    def test_keyless_single_array_equal_cache_is_not_a_scope_record(self):
        old=array(formula(auxiliary([(9,{'E':10})]),'E9'),'E9')
        literal=auxiliary([(9,{'E':10})]);latest=auxiliary([(9,{'A':2,'E':99})])
        result,_=patch(literal,old,latest,prefer_source=True,scope_projection=True)
        self.assertEqual(values(result),values(latest))

    def test_keyless_equal_caches_do_not_hide_changed_formulas(self):
        a=formula(auxiliary([(9,{'E':10})]),'E9','1+9')
        b=formula(auxiliary([(9,{'E':10})]),'E9','2+8')
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):
            patch(a,b,auxiliary([]),prefer_source=True,scope_projection=True)

    def test_keyless_multi_cell_array_conversion_still_blocks(self):
        old=array(formula(auxiliary([(9,{'E':10})]),'E9'),'E9','E9:E10')
        literal=auxiliary([(9,{'E':10})])
        with self.assertRaisesRegex(ValueError,'数组或跨单元格'):
            patch(literal,old,auxiliary([]),prefer_source=True,scope_projection=True)

    def test_added_formula_row_can_be_removed_from_moved_dev_mask(self):
        before=table([(6,dict(ID=1,value=10))])
        after=formula(table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))]),'B7','A7+18')
        latest=table([(6,dict(ID=1,value=10)),(12,dict(ID=2,value=20))])
        masked,_=patch(after,before,latest,prefer_source=True,scope_projection=True)
        self.assertNotIn('A12',values(masked))
        with self.assertRaisesRegex(ValueError,'公式位置变化'):
            patch(after,before,latest,prefer_source=True)

    def test_restore_moved_single_array_only_in_dev_mask_and_freeze_release_cache(self):
        old=array(formula(table([(6,dict(ID=1,value=10))]),'B6','A6+9'),'B6')
        frozen=table([(6,dict(ID=1,value=10))])
        latest=table([(9,dict(ID=1,value=10,other=8))])
        masked,_=patch(frozen,old,latest,prefer_source=True,scope_projection=True)
        cell=Book(masked).cells('Main')['B9']
        self.assertEqual(first(cell,'f').getAttribute('ref'),'B9')
        self.assertFalse(cell.hasAttribute('cm'))
        release=array(formula(table([(12,dict(ID=1,value=99,other=77))]),'B12','A12+98'),'B12')
        result,_=patch(masked,latest,release,prefer_source=True)
        self.assertEqual(values(result)['B12'],'99');self.assertEqual(values(result)['C12'],'77')
        self.assertIsNone(first(Book(result).cells('Main')['B12'],'f'))
        with self.assertRaisesRegex(ValueError,'公式位置变化'):
            patch(frozen,old,latest,prefer_source=True)

    def test_same_cell_array_restore_is_still_blocked_for_real_release(self):
        old=array(formula(table([(6,dict(ID=1,value=10))]),'B6'),'B6')
        frozen=table([(6,dict(ID=1,value=10))]);target=table([(6,dict(ID=1,value=99))])
        with self.assertRaisesRegex(ValueError,'数组或跨单元格'):
            patch(frozen,old,target,prefer_source=True)

    def test_multi_cell_array_remains_blocked_even_in_projection(self):
        old=array(formula(table([(6,dict(ID=1,value=10))]),'B6'),'B6','B6:B7')
        frozen=table([(6,dict(ID=1,value=10))]);target=table([(6,dict(ID=1,value=99))])
        with self.assertRaisesRegex(ValueError,'数组或跨单元格'):
            patch(frozen,old,target,prefer_source=True,scope_projection=True)

if __name__=='__main__':unittest.main()
