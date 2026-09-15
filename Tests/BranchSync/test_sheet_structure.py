import unittest
from xml.dom import minidom
from unittest.mock import patch
from lxml import etree as E
import workbook_cells as cells
from test_workbook import parts, pack, NS
from test_config_identity import table, merge, values

class SheetStructureTests(unittest.TestCase):
    def test_added_validation_precedes_hyperlinks_and_extensions(self):
        before = table([(6, dict(ID=1, value=10))])
        p = parts(before)
        tail = '<hyperlinks/><pageMargins left="0.7"/><extLst/>'
        p['xl/worksheets/sheet1.xml'] = p['xl/worksheets/sheet1.xml'].replace(b'</worksheet>', (tail+'</worksheet>').encode())
        target = pack(p)
        p = parts(before)
        validation = '<dataValidations count="1"><dataValidation type="whole" sqref="B6"><formula1>0</formula1></dataValidation></dataValidations>'
        p['xl/worksheets/sheet1.xml'] = p['xl/worksheets/sheet1.xml'].replace(b'</worksheet>', (validation+'</worksheet>').encode())
        after = pack(p)
        for dom in (cells.DOM, minidom):
            with self.subTest(dom=dom.__name__), patch.object(cells, 'DOM', dom):
                result = merge(before, after, target)
                root = E.fromstring(parts(result)['xl/worksheets/sheet1.xml'])
                tags = [E.QName(n).localname for n in root]
                self.assertLess(tags.index('dataValidations'), tags.index('hyperlinks'))
                self.assertEqual(tags[-1], 'extLst')
                self.assertEqual(values(result), values(target))
                self.assertEqual(root.find('{'+NS+'}dataValidations').get('count'), '1')

    def test_all_merged_metadata_insert_in_schema_order(self):
        for dom in (cells.DOM, minidom):
            with self.subTest(dom=dom.__name__):
                doc = dom.parseString(f'<worksheet xmlns="{NS}"><sheetData/><extLst/></worksheet>')
                for tag in ('pageSetup','pageMargins','printOptions','dataValidations','mergeCells','autoFilter','sheetProtection'):
                    cells.insert_sheet_structure(doc, doc.createElementNS(NS, tag))
                self.assertEqual([n.localName for n in cells.children(doc.documentElement)],
                    ['sheetData','sheetProtection','autoFilter','mergeCells','dataValidations','printOptions','pageMargins','pageSetup','extLst'])
