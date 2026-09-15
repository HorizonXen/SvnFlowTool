import io
import pathlib
import sys
import unittest
import zipfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'scripts'))
from workbook_sync import patch_workbook

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
def book(a='1', b='2', formula=True, extra=True):
    sheet = f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1">' + ('<f>1+1</f>' if formula else '') + f'<v>{a}</v></c><c r="B1"><v>{b}</v></c></row></sheetData></worksheet>'
    relns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    pkgns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    extra_sheet = '<sheet name="DeleteMe" sheetId="2" r:id="rId2"/>' if extra else ''
    extra_rel = f'<Relationship Id="rId2" Type="{relns}/worksheet" Target="worksheets/sheet2.xml"/>' if extra else ''
    extra_type = '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' if extra else ''
    parts = {'xl/worksheets/sheet1.xml': sheet.encode(),
             '_rels/.rels': f'<Relationships xmlns="{pkgns}"><Relationship Id="rId1" Type="{relns}/officeDocument" Target="xl/workbook.xml"/></Relationships>'.encode(),
             'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{relns}"><sheets><sheet name="Main" sheetId="1" r:id="rId1"/>{extra_sheet}</sheets></workbook>'.encode(),
             'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{pkgns}"><Relationship Id="rId1" Type="{relns}/worksheet" Target="worksheets/sheet1.xml"/>{extra_rel}</Relationships>'.encode(),
             '[Content_Types].xml': ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' + extra_type + '</Types>').encode()}
    if extra: parts['xl/worksheets/sheet2.xml'] = f'<worksheet xmlns="{NS}"><sheetData/></worksheet>'.encode()
    return pack(parts)
def pack(parts):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items(): archive.writestr(name, data)
    return output.getvalue()
def parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive: return {n: archive.read(n) for n in archive.namelist()}

class WorkbookTests(unittest.TestCase):
    def test_formula_to_value_excludes_other_author_cell_and_keeps_release(self):
        result, notes = patch_workbook(book(b='99'), book(a='2', b='99', formula=False), book(b='7'))
        sheet = parts(result)['xl/worksheets/sheet1.xml']
        self.assertNotIn(b'<f>', sheet)
        self.assertIn(b'<v>7</v>', sheet)
        self.assertNotIn(b'99', sheet)
        self.assertTrue(notes)
    def test_delete_sheet_keeps_unrelated_release_cell(self):
        result, _ = patch_workbook(book(), book(extra=False), book(b='77'))
        self.assertNotIn('xl/worksheets/sheet2.xml', parts(result))
        self.assertNotIn(b'DeleteMe', parts(result)['xl/workbook.xml'])
        self.assertIn(b'77', parts(result)['xl/worksheets/sheet1.xml'])
    def test_cell_conflict_blocks(self):
        with self.assertRaisesRegex(ValueError, 'A1'):
            patch_workbook(book(), book(a='2', formula=False), book(a='4'))
    def test_delete_modified_sheet_blocks(self):
        local = parts(book()); local['xl/worksheets/sheet2.xml'] = b'<changed/>'
        with self.assertRaises(ValueError): patch_workbook(book(), book(extra=False), pack(local))
    def test_shared_strings_dependency_blocks(self):
        before = parts(book()); after = parts(book(formula=False)); local = parts(book(b='9'))
        before['xl/sharedStrings.xml'] = b'base'; after['xl/sharedStrings.xml'] = b'base'; local['xl/sharedStrings.xml'] = b'release'
        with self.assertRaisesRegex(ValueError, '依赖'): patch_workbook(pack(before), pack(after), pack(local))
    def test_whitespace_string_is_a_real_release_edit(self):
        def string_book(value):
            data=parts(book())
            data['xl/worksheets/sheet1.xml']=data['xl/worksheets/sheet1.xml'].replace(b'<c r="A1"><f>1+1</f><v>1</v></c>', ('<c r="A1" t="inlineStr"><is><t xml:space="preserve">'+value+'</t></is></c>').encode())
            return pack(data)
        with self.assertRaisesRegex(ValueError,'A1'):
            patch_workbook(string_book(''),string_book('new'),string_book(' '))
    def test_reverted_sheet_addition_removes_older_author_sheet(self):
        result,_=patch_workbook(book(extra=False),book(extra=False),book(b='9'),accepted=[book()])
        self.assertNotIn('xl/worksheets/sheet2.xml',parts(result))
        self.assertIn(b'<v>9</v>',parts(result)['xl/worksheets/sheet1.xml'])
    def test_idempotent(self):
        after = book(formula=False)
        result, notes = patch_workbook(book(), after, after)
        self.assertEqual(parts(result), parts(after)); self.assertEqual(notes, [])

if __name__ == '__main__': unittest.main()
