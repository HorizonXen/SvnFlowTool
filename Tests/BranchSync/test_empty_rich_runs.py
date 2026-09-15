"""Saving empty rich strings must neither require missing IDs nor clear Release."""
import unittest
from xml.dom import minidom
from test_config_identity import table, merge, values
from test_workbook import parts, pack
from workbook_cells import DOM, M, empty_config_cell, WorkbookReplay


def rich(data, content='<r><t/></r>'):
    p=parts(data)
    p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(
        b'<is><t></t></is>', ('<is>'+content+'</is>').encode())
    return pack(p)


class EmptyRichRunTests(unittest.TestCase):
    def test_empty_runs_agree_in_both_parsers(self):
        for body in ('<r><t/></r>', '<r><t/></r><r><t/></r>', '<t/><r><t/></r>'):
            for parser in (DOM, minidom):
                cell=parser.parseString(f'<c xmlns="{M}" t="inlineStr"><is>{body}</is></c>').documentElement
                self.assertTrue(empty_config_cell(cell))

    def test_real_content_and_metadata_are_not_empty(self):
        for body in ('<r><t> </t></r>', '<r><t>new</t></r>', '<r><rPr><b/></rPr><t/></r>',
                     '<r custom="1"><t/></r>', '<r><f/></r>', '<r><t/></r><extLst/>'):
            for parser in (DOM, minidom):
                cell=parser.parseString(f'<c xmlns="{M}" t="inlineStr"><is>{body}</is></c>').documentElement
                self.assertFalse(empty_config_cell(cell))

    def test_missing_unchanged_id_does_not_block_real_edit(self):
        a=table([(6,dict(ID=1,value=10,other='')),(7,dict(ID=2,value=20,other=''))])
        b=rich(table([(6,dict(ID=1,value=10,other='')),(7,dict(ID=2,value=21,other=''))]))
        t=table([(9,dict(ID=2,value=90,other=88))])
        replay=WorkbookReplay(t);replay.apply(a,b);result=replay.finish()
        self.assertEqual(values(result),{'A9':'2','B9':'21','C9':'88'})

    def test_empty_reencoding_preserves_release_value_both_directions(self):
        a=table([(6,dict(ID=1,value=10,other=''))]); b=rich(a)
        t=table([(9,dict(ID=1,value=90,other=88))])
        for left,right in ((a,b),(b,a)):
            self.assertEqual(values(merge(left,right,t)),values(t))

    def test_missing_id_with_actual_edit_remains_blocked(self):
        a=table([(6,dict(ID=1,value=10,other=''))])
        for b in (rich(table([(6,dict(ID=1,value=11,other=''))])),rich(a,'<r><t>new</t></r>')):
            with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
                merge(a,b,table([(9,dict(ID=2,value=90))]))

class ValidationSaveTests(unittest.TestCase):
    def node(self, sqref='H6 H140:H867', dropdown='', uid=True, formula='0'):
        from workbook_cells import DOM, M
        attr=' xr:uid="same"' if uid else ''
        return DOM.parseString(f'<dataValidations xmlns="{M}" xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" count="1"><dataValidation type="list" sqref="{sqref}"{attr}{dropdown}><formula1>{formula}</formula1></dataValidation></dataValidations>').documentElement

    def test_default_and_uid_rewrite_keeps_release_range(self):
        from workbook_cells import merge_structure, sig
        a=self.node();t=self.node('H6 H105:H832',formula='release')
        for value in ('0','false'):
            b=self.node(dropdown=f' showDropDown="{value}"',uid=False)
            for left,right in ((a,b),(b,a)):
                self.assertEqual(sig(merge_structure(left,right,t,True)),sig(t))

    def test_real_rule_change_missing_range_stays_blocked(self):
        from workbook_cells import merge_structure
        a=self.node();t=self.node('H6 H105:H832')
        for b in (self.node(formula='1'),self.node(dropdown=' showDropDown="1"')):
            with self.assertRaisesRegex(ValueError,'缺少已有工作表结构'):
                merge_structure(a,b,t,True)
