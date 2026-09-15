import unittest
from unittest import mock
from test_workbook import book,parts,pack
from test_config_identity import table
from test_deletion_history import HistoryFixture
import workbook_cells as cells
from workbook_history import DeletionHistory,summary,inventory
from file_sync import same_data

class PerformanceSemanticsTests(unittest.TestCase):
    def test_native_empty_check_matches_dom_reference(self):
        from xml.dom import minidom
        samples=['', '<v/>','<v>0</v>','<v> </v>','<is><t/></is>',
                 '<is><t xml:space="preserve"> </t></is>','<f/>','<v/><extLst/>',
                 '<!--note-->','<!-- -->','<!---->','<v/> text','<v/>  ',
                 '<is><t/><t/></is>','<is><t><x/></t></is>',
                 '<v xmlns="urn:other"/>','<v custom="1"/>']
        for attrs in ['', ' t="inlineStr"',' t="n"',' t="s"',' t="str"',' r="A1" s="3"',
                      ' custom="1"',' xml:space="preserve"',' xmlns:z="urn:other" z:r="1"']:
            for content in samples:
                xml=f'<c xmlns="{cells.M}"{attrs}>{content}</c>'.encode()
                with self.subTest(xml=xml):
                    self.assertEqual(cells.empty_config_cell(cells.DOM.parseString(xml).documentElement),
                                     cells.empty_config_cell(minidom.parseString(xml).documentElement))

    def test_engine_fingerprint_changes_when_compiled_binary_changes(self):
        import tempfile,pathlib
        from file_sync import compiled_engine_hash
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);before=compiled_engine_hash(root)
            binary=root/'workbook_cells.cpython-312-darwin.so';binary.write_bytes(b'first build')
            first=compiled_engine_hash(root);self.assertNotEqual(first,before)
            binary.write_bytes(b'new build');self.assertNotEqual(first,compiled_engine_hash(root))

    def test_equality_stops_at_changed_sheet_and_caches_only_boolean(self):
        a,b=book(a='1',formula=False),book(a='2',formula=False)
        session=cells.WorkbookMergeSession(b)
        original=cells.sheet_signature;visited=[]
        def signature(book,name,*args,**kw):
            visited.append(name);return original(book,name,*args,**kw)
        with mock.patch.object(cells,'sheet_signature',side_effect=signature):
            self.assertFalse(same_data(a,b,'a.xlsx',session))
            self.assertNotIn('DeleteMe',visited)
            visited.clear();self.assertFalse(same_data(b,a,'a.xlsx',session));self.assertEqual(visited,[])
        session.clear();self.assertFalse(session.equalities)

    def test_equal_first_sheet_still_checks_workbook_metadata_and_other_parts(self):
        a=book(formula=False);p=parts(a);p['custom/data.bin']=b'foreign'
        b=pack(p);self.assertFalse(same_data(a,b,'a.xlsx',cells.WorkbookMergeSession(b)))

    def test_raw_sheet_shortcut_checks_used_strings_and_ignores_unused_strings(self):
        def fixture(used,unused):
            p=parts(book(formula=False));ns=cells.M
            p['xl/sharedStrings.xml']=f'<sst xmlns="{ns}"><si><t>{used}</t></si><si><t>{unused}</t></si></sst>'.encode()
            p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="A1"><v>1</v></c>',b'<c r="A1" t="s"><v>0</v></c>')
            return cells.Book(pack(p))
        a=fixture('keep','old');b=fixture('keep','new');c=fixture('changed','old')
        self.assertTrue(cells.raw_sheet_equal(a,b,'Main'))
        self.assertFalse(cells.raw_sheet_equal(a,c,'Main'))

    def test_raw_sheet_shortcut_checks_row_column_and_default_styles(self):
        def fixture(row_format,col_format,default_format,unused_format):
            p=parts(book(formula=False));ns=cells.M
            p['xl/styles.xml']=(f'<styleSheet xmlns="{ns}"><fonts><font/></fonts><fills><fill/></fills><borders><border/></borders><cellXfs>'+''.join(f'<xf numFmtId="{v}" fontId="0" fillId="0" borderId="0"/>' for v in [default_format,row_format,col_format,unused_format])+'</cellXfs></styleSheet>').encode()
            p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<sheetData>',b'<cols><col min="1" max="1" style="2"/></cols><sheetData>').replace(b'<row r="1">',b'<row r="1" s="1">')
            return cells.Book(pack(p))
        a=fixture(1,2,0,9)
        self.assertTrue(cells.raw_sheet_equal(a,fixture(1,2,0,10),'Main'))
        for values in [(3,2,0,9),(1,3,0,9),(1,2,3,9)]:self.assertFalse(cells.raw_sheet_equal(a,fixture(*values),'Main'))

    def test_batch_deletion_rejects_duplicate_physical_rows_before_mutation(self):
        from workbook_history import remove_rows
        source=cells.Book(book(formula=False));doc=source.doc(source.sheets['Main'][2])
        row=doc.getElementsByTagNameNS(cells.M,'row')[0];row.parentNode.appendChild(row.cloneNode(True))
        before=doc.toxml()
        with self.assertRaisesRegex(ValueError,'XML 行号重复'):remove_rows(source,'Main',[1])
        self.assertEqual(doc.toxml(),before)

    def test_history_cache_expands_when_later_deletion_needs_more_identity(self):
        data=table([(6,dict(ID=1,value=2)),(7,dict(ID=2,value=3))])
        core=HistoryFixture(data,[(6,'other',data)])
        audit=DeletionHistory(core,core.config,'config.xlsx',cells.WorkbookMergeSession(data),5)
        name=next(iter(cells.Book(data).sheets));entry={'revision':6}
        partial=audit.snapshot(entry,{name:({('99',)},False)})[name]
        self.assertFalse(partial['keyed']);self.assertEqual(len(partial['ids']),2)
        complete=audit.snapshot(entry,{name:({('1',)},True)})[name]
        self.assertEqual(len(complete['keyed']),2);self.assertTrue(complete['payloads'])
        audit.snapshot(entry,{name:({('2',)},False)})
        self.assertEqual(sum(c[0]=='cat' for c in core.calls),2)

    def test_history_summaries_are_reused_without_retaining_mutable_books(self):
        after=table([(6,dict(ID=1,value=2))]);later=table([(9,dict(ID=1,value=3))])
        core=HistoryFixture(after,[(6,'other',later)])
        audit=DeletionHistory(core,core.config,'config.xlsx',cells.WorkbookMergeSession(later),5)
        entry={'revision':6};name=next(iter(cells.Book(later).sheets))
        first=audit.snapshot(entry,[name]);second=audit.snapshot(entry,[name])
        self.assertEqual(first,second);self.assertEqual(sum(c[0]=='cat' for c in core.calls),1)
        self.assertTrue(all(isinstance(v,bytes) for v in first[name]['keyed'].values()))
        self.assertNotEqual(summary(inventory(cells.Book(after),name))['keyed'],first[name]['keyed'])
