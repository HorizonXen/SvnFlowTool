import unittest
from lxml import etree as E
from test_config_identity import table, values
from test_workbook import parts, pack, NS
from workbook_compact import compact, Rows

class CompactTests(unittest.TestCase):
    def test_records_and_keyless_notes_move_with_style_and_fields(self):
        raw=table([(6,dict(ID=1,value=10)),(100,dict(ID=2,value=20)),(103,dict(value='note'))])
        p=parts(raw)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B100">',b'<c r="B100" s="0">').replace(b'</sheetData>',b'<row r="104"><c r="A104" s="0"/></row></sheetData>')
        output,counts,skip=compact(pack(p))
        self.assertFalse(skip);self.assertEqual(counts,{'Main':96})
        self.assertEqual(values(output),{'A6':'1','B6':'10','A7':'2','B7':'20'})
        r=E.fromstring(parts(output)['xl/worksheets/sheet1.xml'])
        self.assertEqual(r.find('.//{'+NS+'}c[@r="B7"]').get('s'),'0')
        self.assertEqual(r.find('.//{'+NS+'}c[@r="B8"]/{'+NS+'}is/{'+NS+'}t').text,'note')
        self.assertEqual(compact(output)[0],output)

    def test_metadata_moves_and_removed_ranges_disappear(self):
        raw=table([(6,dict(ID=1,value=10)),(10,dict(ID=2,value=20))])
        p=parts(raw)
        extra='<autoFilter ref="A1:C10"/><conditionalFormatting sqref="B7:B9"><cfRule type="duplicateValues" priority="1"/></conditionalFormatting><conditionalFormatting sqref="B10:B20"><cfRule type="expression" priority="2"><formula>AND(B10&gt;0,LOG10(10)=1,SEARCH("A10",C10))</formula></cfRule></conditionalFormatting>'
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</worksheet>',(extra+'</worksheet>').encode())
        output,_,skip=compact(pack(p));self.assertFalse(skip)
        r=E.fromstring(parts(output)['xl/worksheets/sheet1.xml']);q='{'+NS+'}'
        self.assertEqual(r.find(q+'autoFilter').get('ref'),'A1:C7')
        self.assertEqual(len(r.findall(q+'conditionalFormatting')),1)
        cf=r.find(q+'conditionalFormatting');self.assertEqual(cf.get('sqref'),'B7:B17')
        self.assertEqual(cf.find('.//'+q+'formula').text,'AND(B7>0,LOG10(10)=1,SEARCH("A10",C7))')

    def test_complex_workbooks_are_unchanged(self):
        raw=table([(6,dict(ID=1,value=10)),(10,dict(ID=2,value=20))])
        for xml in ('<mergeCells><mergeCell ref="A7:B9"/></mergeCells>', '<conditionalFormatting sqref="B10"><cfRule><formula>Other!A10</formula></cfRule></conditionalFormatting>'):
            p=parts(raw);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</worksheet>',(xml+'</worksheet>').encode());source=pack(p)
            result,counts,reason=compact(source)
            self.assertEqual(result,source);self.assertFalse(counts);self.assertTrue(reason)
        p=parts(raw);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<v>20</v>',b'<f>A10*10</f><v>20</v>');source=pack(p)
        self.assertEqual(compact(source)[0],source)

    def test_absolute_range_intersects_surviving_rows(self):
        rows=Rows([7,8,9])
        self.assertEqual(rows.reference('$A$7:$B$10'),'$A$7:$B$7')
        self.assertEqual(rows.reference('A7:B9'),'')
        self.assertEqual(rows.reference('A6:A1048576'),'A6:A1048573')
