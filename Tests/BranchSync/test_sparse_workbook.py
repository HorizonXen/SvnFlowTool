import unittest
from lxml import etree as E
from test_workbook import NS, book, parts, pack
from test_config_identity import table, merge, values
from workbook_cells import Book
from workbook_sparse import compact_xml

class SparseWorkbookTests(unittest.TestCase):
    def test_removes_empty_tail_without_moving_records_or_references(self):
        xml=f'<worksheet xmlns="{NS}"><dimension ref="A1:XFD1048576"/><sheetData><row r="9"><c r="A9"><v>7</v></c></row><row r="100000"><c r="A100000"/><c r="B100000"><v/></c></row></sheetData><mergeCells><mergeCell ref="A20:B20"/></mergeCells></worksheet>'.encode()
        result=E.fromstring(compact_xml(xml));q='{'+NS+'}'
        self.assertEqual([r.get('r') for r in result.findall(q+'sheetData/'+q+'row')],['9'])
        self.assertEqual(result.find('.//'+q+'mergeCell').get('ref'),'A20:B20')
        self.assertIsNone(result.find(q+'dimension'))

    def test_keeps_styles_formulas_strings_and_row_layout(self):
        xml=f'<worksheet xmlns="{NS}"><sheetData><row r="8" hidden="1"/><row r="9"><c r="A9" s="0"/><c r="B9"><f>SUM(A1:A8)</f><v/></c><c r="C9" t="inlineStr"><is><t/></is></c><c r="D9" cm="1"/></row></sheetData></worksheet>'.encode()
        self.assertEqual(compact_xml(xml),xml)

    def test_sparse_tail_does_not_displace_new_key(self):
        before=table([(6,dict(ID=1,value=10))]);after=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))]);target=table([(9,dict(ID=1,value=99))])
        p=parts(target);q='{'+NS+'}';root=E.fromstring(p['xl/worksheets/sheet1.xml']);row=E.SubElement(root.find(q+'sheetData'),q+'row',r='900000');E.SubElement(row,q+'c',r='A900000');p['xl/worksheets/sheet1.xml']=E.tostring(root)
        result=merge(before,after,pack(p));v=values(result)
        self.assertEqual(v['A9'],'1');self.assertEqual(v['B9'],'99');self.assertEqual(v['A10'],'2');self.assertNotIn('A900000',Book(result).cells('Main'))


    def test_finder_metadata_does_not_change_export_input_fingerprint(self):
        import sys, types
        from unittest.mock import patch
        from xtools_export import desktop_metadata_ignored
        original=lambda root: {'.DS_Store':'old', 'global/.DS_Store':'new', 'global/table.xlsx':'data', 'global/notes.json':'notes'}
        bridge=types.SimpleNamespace(tree=original)
        with patch.dict(sys.modules, {'xtools_bridge':bridge}):
            with desktop_metadata_ignored():
                self.assertEqual(bridge.tree('unused'), {'global/table.xlsx':'data', 'global/notes.json':'notes'})
            self.assertIs(bridge.tree, original)
