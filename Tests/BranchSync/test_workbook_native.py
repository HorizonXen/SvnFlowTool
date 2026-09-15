import io
import pathlib
import sys
import unittest
import zipfile
import tempfile
from unittest.mock import patch
from lxml import etree as E
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from test_config_identity import table, values
import workbook_native as native
from workbook_cells import Book, restore_row


def fake_excel(file, targets):
    """Independent fixture row deletion; real Excel integration uses the 258 workbook."""
    data=file.read_bytes();book=Book(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z: parts={n:z.read(n) for n in z.namelist()}
    for target in targets:
        name=target['sheet'];deleted=target.get('delete_rows',[]);path=book.sheets[name][2]
        root=E.fromstring(parts[path]);q='{'+native.Book(data).workbook.documentElement.namespaceURI+'}'
        for row in list(root.find(q+'sheetData')):
            n=int(row.get('r'))
            if n in deleted:row.getparent().remove(row);continue
            shift=sum(d<n for d in deleted);row.set('r',str(n-shift))
            for cell in row:cell.set('r',native.re.sub(r'\d+$',str(n-shift),cell.get('r')))
        parts[path]=E.tostring(root)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for n,v in parts.items():z.writestr(n,v)
    file.write_bytes(out.getvalue())


class NativeWorkbookTests(unittest.TestCase):
    def test_anonymous_base_styles_registered_without_changing_formats(self):
        data=table([(6,dict(ID=1,value=10))])
        book=Book(data);parts=dict(book.parts)
        parts['xl/styles.xml']=('''<styleSheet xmlns="'''+native.M+'''">
          <fonts count="1"><font><sz val="11"/></font></fonts>
          <fills count="1"><fill/></fills><borders count="1"><border/></borders>
          <cellStyleXfs count="1"><xf fontId="0" fillId="0" borderId="0" numFmtId="0"/></cellStyleXfs>
          <cellXfs count="1"><xf fontId="0" fillId="0" borderId="0" numFmtId="0" xfId="0"/></cellXfs>
        </styleSheet>''').encode()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for n,v in parts.items():z.writestr(n,v)
        before=out.getvalue();after=native.register_style_bases(before)
        native.verify(before,after,{})
        result=Book(after)
        named=native.children(native.first(result.styles.documentElement,'cellStyles'))
        self.assertEqual([(n.getAttribute('xfId'),n.getAttribute('hidden')) for n in named],[('0','1')])
        for name,value in parts.items():
            if name!='xl/styles.xml':self.assertEqual(result.parts[name],value)
        self.assertEqual(native.register_style_bases(after),after)

    def formula_book(self, formula='SUM(A6:A7)', attrs='ca="1" aca="1"', value='3'):
        data=table([(6,dict(ID=1,value=10))])
        book=Book(data)
        parts=dict(book.parts)
        path=book.sheets['Main'][2]
        root=E.fromstring(parts[path]);q='{'+root.nsmap[None]+'}'
        cell=root.find('.//'+q+'c[@r="B6"]')
        for child in list(cell):cell.remove(child)
        cell.attrib.pop('t',None)
        cell.append(E.fromstring(('<f xmlns="'+root.nsmap[None]+'" '+attrs+'>'+formula+'</f>').encode()))
        E.SubElement(cell,q+'v').text=value
        parts[path]=E.tostring(root)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for n,v in parts.items():z.writestr(n,v)
        return out.getvalue()

    def test_recalculation_flags_and_cached_results_are_not_formula_changes(self):
        a=self.formula_book()
        b=self.formula_book(attrs='',value='999')
        # Reproduce the old exact-XML mismatch on the same fixture.
        self.assertNotEqual(Book(a).cell_value(Book(a).cells('Main')['B6']),
                            Book(b).cell_value(Book(b).cells('Main')['B6']))
        native.verify(a,b,{})

    def test_formula_text_array_extent_and_style_still_block(self):
        a=self.formula_book()
        for b in (self.formula_book(formula='SUM(A6:A8)'),
                  self.formula_book(attrs='t="array" ref="B6:B7"')):
            with self.assertRaisesRegex(ValueError,r'Main!B6.*数据或公式变化'):
                native.verify(a,b,{})
        # Independently alter a serialized style via a valid differing style fixture.
        b=Book(a)
        style=native.first(b.styles.documentElement,'cellXfs')
        xf=list(style.e)[0];xf.set('applyNumberFormat','1')
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for n,v in b.parts.items():z.writestr(n,b.styles.toxml(encoding='utf-8') if n=='xl/styles.xml' else v)
        with self.assertRaisesRegex(ValueError,'样式变化'):native.verify(a,out.getvalue(),{})

    def test_failure_artifacts_keep_exact_bytes_and_row_plan(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(pathlib.Path,'home',return_value=pathlib.Path(folder)):
            p=native.preserve_failure(b'before',b'after',{'Main':[6]},'x.xlsx',ValueError('Main!A6'))
            self.assertEqual((p/'candidate.xlsx').read_bytes(),b'before')
            self.assertEqual((p/'saved.xlsx').read_bytes(),b'after')
            self.assertEqual(native.json.loads((p/'failure.json').read_text())['deletedRows'],{'Main':[6]})

    def test_only_merge_emptied_rows_are_deleted(self):
        before=table([(6,dict(ID=1,value=10)),(10,dict(ID=2,value=20))])
        after=table([(10,dict(ID=2,value=21))])
        self.assertEqual(native.deletion_plan(before,after),{'Main':[6]})
        with patch.object(native,'apply_edits',side_effect=fake_excel):
            result,meta=native.finalize(before,after,'table.xlsx')
        self.assertEqual(values(result),{'A9':'2','B9':'21'})
        self.assertEqual(meta['deletedRows'],{'Main':[6]})
        restored=restore_row(result,before,'Main',9,source_number=10)
        self.assertEqual(values(restored),{'A9':'2','B9':'20'})

    def test_partial_clear_does_not_delete_record(self):
        a=table([(6,dict(ID=1,value=10))]);b=table([(6,dict(ID=1))])
        self.assertEqual(native.deletion_plan(a,b),{})

    def test_existing_blank_rows_and_notes_survive(self):
        a=table([(6,dict(ID=1,value=10)),(8,dict(value='note')),(10,dict(ID=2,value=20))])
        b=table([(8,dict(value='note')),(10,dict(ID=2,value=20))])
        with patch.object(native,'apply_edits',side_effect=fake_excel):out,_=native.finalize(a,b,'table.xlsx')
        self.assertEqual(values(out),{'A9':'2','B9':'20'})
        self.assertEqual(native.config_cell_text(Book(out).cells('Main')['B7']),'note')

    def test_failed_or_corrupt_native_save_never_returns_candidate(self):
        a=table([(6,dict(ID=1,value=10))]);b=table([])
        with patch.object(native,'apply_edits',side_effect=RuntimeError('Excel unavailable')):
            with self.assertRaisesRegex(RuntimeError,'unavailable'):native.finalize(a,b,'table.xlsx')
        a=table([(6,dict(ID=1)),(10,dict(ID=2))]);b=table([(10,dict(ID=2))])
        with patch.object(native,'apply_edits'), patch.object(native,'preserve_failure',return_value='diagnostic'):
            with self.assertRaisesRegex(ValueError,'核验不一致'):native.finalize(a,b,'table.xlsx')

    def test_native_commands_use_scoped_workbook_and_descending_entire_rows(self):
        s=native.script_for([{'sheet':'Main','delete_rows':[6,7,10], 'edits':[{'address':'B1','value_type':'text','new_value':'=not a formula'}]}])
        self.assertLess(s.index('A10:A10'),s.index('A6:A7'))
        self.assertIn('entire row',s);self.assertIn('shift shift up',s)
        self.assertIn('update links 0',s);self.assertIn('set display alerts to oldAlerts',s)
        self.assertIn('set number format of range "B1" of ws to "@"',s)
        self.assertNotIn('active workbook',s)
