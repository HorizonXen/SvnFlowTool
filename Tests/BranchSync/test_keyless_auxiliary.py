import unittest
from test_config_identity import table, merge, values
from test_workbook import parts, pack
from workbook_cells import Book, first


def auxiliary(rows, main=None, formula=None):
    data=parts(table(main or [(6,dict(ID=1,value=10))]))
    extra=''
    for row,values_ in rows:
        cells=''.join(f'<c r="{col}{row}"><v>{value}</v></c>' for col,value in values_.items())
        if formula and row==formula[0]:
            cells+=f'<c r="G{row}"><f{formula[1]}>{formula[2]}</f><v/></c>'
        extra+=f'<row r="{row}">{cells}</row>'
    data['xl/worksheets/sheet1.xml']=data['xl/worksheets/sheet1.xml'].replace(b'</sheetData>',extra.encode()+b'</sheetData>')
    return pack(data)


class KeylessAuxiliaryTests(unittest.TestCase):
    def test_unique_complete_auxiliary_content_matches_moved_row(self):
        a=auxiliary([(9,{'E':124,'F':1457533})])
        b=auxiliary([])
        t=auxiliary([(22,{'E':124,'F':1457533})],[(9,dict(ID=2,value=99)),(16,dict(ID=1,value=10))])
        result=merge(a,b,t)
        self.assertNotIn('E22',values(result));self.assertNotIn('F22',values(result))
        self.assertEqual(values(result)['B9'],'99')
        self.assertEqual(values(merge(a,b,result)),values(result))

    def test_duplicate_or_edited_or_partial_target_blocks(self):
        a=auxiliary([(9,{'E':124,'F':1457533})]);b=auxiliary([])
        for rows in [[(22,{'E':124,'F':1457534})],[(22,{'E':124,'F':1457533}),(23,{'E':124,'F':1457533})],[(22,{'E':124,'F':1457533,'H':99})]]:
            with self.subTest(rows=rows),self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
                merge(a,b,auxiliary(rows))

    def test_duplicate_source_blocks(self):
        a=auxiliary([(9,{'E':124}),(10,{'E':124})]);b=auxiliary([])
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):merge(a,b,auxiliary([(20,{'E':124})]))

    def test_changed_declaration_blocks_auxiliary_column_guess(self):
        a=auxiliary([(9,{'E':124})]);b=auxiliary([])
        target=parts(auxiliary([(22,{'E':124})]))
        target['xl/worksheets/sheet1.xml']=target['xl/worksheets/sheet1.xml'].replace(b'<t>other</t>',b'<t>different</t>')
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):merge(a,b,pack(target))

    def test_blank_declared_columns_allow_idempotent_replay(self):
        def blanks(data):
            data=parts(data)
            data['xl/worksheets/sheet1.xml']=data['xl/worksheets/sheet1.xml'].replace(b'<row r="2">',b'<row r="2"><c r="E2"/><c r="F2"/>')
            return pack(data)
        a=blanks(auxiliary([(9,{'E':124,'F':1457533})]));b=blanks(auxiliary([]))
        t=blanks(auxiliary([(22,{'E':124,'F':1457533})]))
        result=merge(a,b,t)
        self.assertNotIn('E22',values(result))
        self.assertEqual(values(merge(a,b,result)),values(result))

    def test_never_delete_keyed_record_with_same_auxiliary_values(self):
        a=auxiliary([(9,{'E':124})]);b=auxiliary([])
        t=auxiliary([(22,{'A':2,'E':124})])
        result=merge(a,b,t)
        self.assertEqual(values(result)['A22'],'2');self.assertEqual(values(result)['E22'],'124')

    def test_real_edit_or_formula_deletion_still_blocks(self):
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
            merge(auxiliary([(9,{'E':124})]),auxiliary([(9,{'E':125})]),auxiliary([(9,{'E':124})],[(6,dict(ID=1,value=99))]))
        a=auxiliary([(9,{})],formula=(9,'','A9+1'))
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):merge(a,auxiliary([]),auxiliary([(9,{})],[(6,dict(ID=1,value=99))],formula=(9,'','A9+1')))

    def test_recalculate_flag_does_not_create_keyless_change(self):
        a=auxiliary([(9,{})],formula=(9,'','A9+1'))
        b=auxiliary([(9,{})],formula=(9,' ca="1"','A9+1'))
        t=auxiliary([(9,{'A':2,'E':99})])
        self.assertEqual(values(merge(a,b,t)),values(t))

    def test_other_formula_attributes_and_expression_remain_significant(self):
        a=auxiliary([(9,{})],formula=(9,'','A9+1'))
        for attrs,expression in [('','A9+2'),(' t="array" ref="G9:G10"','A9+1')]:
            b=auxiliary([(9,{})],formula=(9,attrs,expression))
            with self.subTest(attrs=attrs),self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):merge(a,b,auxiliary([(9,{})],[(6,dict(ID=1,value=99))],formula=(9,'','A9+1')))

if __name__=='__main__':unittest.main()
