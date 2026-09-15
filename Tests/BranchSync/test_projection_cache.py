import unittest
from unittest.mock import patch as mock
from xml.dom import minidom

from test_workbook import book, parts, pack
from test_config_identity import table, values
from test_formula_freeze import formula
from test_formula_projection import array
from test_keyless_auxiliary import auxiliary
import workbook_cells as cells
from file_sync import merge_data, latest_scope_patches


def projected(before, after, latest, release, cached):
    session = cells.WorkbookMergeSession(latest) if cached else None
    replay = cells.WorkbookReplay(release,session=session)
    project = lambda a,b,t: merge_data(a,b,t,'test.xlsx',latest=True,scope_projection=True,workbook_session=session)
    for a,b in latest_scope_patches(before,after,latest,project): replay.apply(a,b)
    return replay.finish()


class ProjectionCacheTests(unittest.TestCase):
    def test_cached_projection_matches_uncached_for_reversions_deletions_and_formulas(self):
        fixtures = [
            (table([(6,dict(ID=1,value=1))]), table([(6,dict(ID=1,value=2))]),
             table([(9,dict(ID=1,value=1,other=55))]), table([(12,dict(ID=1,value=99,other=77))])),
            (table([(6,dict(ID=1,value=1)),(7,dict(ID=2,value=2))]),
             table([(6,dict(ID=1,value=3)),(7,dict(ID=2,value=2))]),
             table([(6,dict(ID=2,value=88))]), table([(10,dict(ID=1,value=9)),(6,dict(ID=2,value=7))])),
            (auxiliary([(9,{'E':124,'F':1457533})]), auxiliary([]),
             auxiliary([],[(6,dict(ID=1,value=1200))]),
             auxiliary([(22,{'E':124,'F':1457533})],[(6,dict(ID=1,value=900))])),
            (array(formula(table([(6,dict(ID=1,value=10))]),'B6','A6+9'),'B6'),
             table([(6,dict(ID=1,value=10))]), table([(9,dict(ID=1,value=10,other=8))]),
             array(formula(table([(12,dict(ID=1,value=99,other=77))]),'B12','A12+98'),'B12')),
        ]
        for fixture in fixtures:
            with self.subTest(index=fixtures.index(fixture)):
                self.assertEqual(cells.logical_signature(projected(*fixture,True)),
                                 cells.logical_signature(projected(*fixture,False)))

    def test_cached_sources_are_immutable_across_opposite_projections(self):
        a,b,t = (table([(6,dict(ID=1,value=v,other=8))]) for v in (1,2,3))
        session=cells.WorkbookMergeSession(t)
        sources=[session.source(data) for data in (t,a,b)]
        def snapshot(source):
            for _,_,path in source.sheets.values():source.doc(path)
            return dict(source.parts),{path:doc.toxml() for path,doc in source.docs.items()}
        original=[snapshot(source) for source in sources]
        for left,right in ((a,b),(b,a),(a,b)):
            cached=merge_data(left,right,t,'test.xlsx',latest=True,scope_projection=True,workbook_session=session)
            fresh=merge_data(left,right,t,'test.xlsx',latest=True,scope_projection=True)
            self.assertEqual(cells.logical_signature(cached),cells.logical_signature(fresh))
        self.assertEqual([snapshot(source) for source in sources],original)

    def test_cache_is_bounded_and_pinned_tip_survives_eviction(self):
        tip=book(a='99',formula=False);session=cells.WorkbookMergeSession(tip)
        original=session.source(tip)
        for i in range(8):
            session.source(book(a=str(i),formula=False))
            self.assertLessEqual(len(session.books),3)
        self.assertIs(session.source(tip),original)
        session.clear();self.assertEqual(len(session.books),0)

    def test_cached_projection_keeps_ambiguous_id_rejection(self):
        a=table([(6,dict(ID=1,value=1))]);b=table([(6,dict(ID=1,value=2))])
        tip=table([(6,dict(ID=1,value=3)),(7,dict(ID=1,value=4))])
        with self.assertRaisesRegex(RuntimeError,'配置 ID 重复'):
            merge_data(a,b,tip,'test.xlsx',latest=True,scope_projection=True,workbook_session=cells.WorkbookMergeSession(tip))

    def test_native_key_text_matches_dom_for_rich_text_and_tails(self):
        raw=('<c xmlns="'+cells.M+'"><v>123<!--comment-->tail</v><is><r><t> a </t></r><r><t>b</t></r></is></c>').encode()
        self.assertEqual(cells.config_cell_text(cells.DOM.parseString(raw).documentElement),
                         cells.config_cell_text(minidom.parseString(raw).documentElement))

    def test_native_normalization_matches_dom_for_storage_variants(self):
        data=parts(book(formula=False))
        data['xl/sharedStrings.xml']=('<sst xmlns="'+cells.M+'"><si><r><t> a </t></r><r><t>b</t></r></si></sst>').encode()
        fragments=[
            '<c r="A1" t="s"><v>0</v></c>', '<c r="B1" t="s"><v/></c>',
            '<c r="C1" t="n"><v>001.2000</v></c>', '<c r="D1"><v>-0e9</v></c>',
            '<c r="E1"><v>123456789012345678901234567890</v></c>',
            '<c r="F1"><v>1e-10</v></c>', '<c r="G1"><v>NaN</v></c>',
            '<c r="H1" t="inlineStr"><is><t>text</t><phoneticPr fontId="1"/></is></c>',
            '<c r="I1" t="inlineStr"><is><t>text</t><rPh sb="0" eb="1"><t>x</t></rPh><phoneticPr fontId="1"/></is></c>',
            '<c r="J1"><f t="shared" si="0" ref="J1:K1">A1+$B$2</f><v>10</v></c>',
            '<c r="K1"><f t="shared" si="0"/><v>20</v></c>',
            '<c r="L1" t="str"><f>IF(A1,\"\",\"x\")</f><v/></c>',
            '<c r="M1" t="n"/>', '<c r="N1"><v>invalid</v></c>',
        ]
        data['xl/worksheets/sheet1.xml']=('<worksheet xmlns="'+cells.M+'"><sheetData><row r="1">'+''.join(fragments)+'</row></sheetData></worksheet>').encode()
        raw=pack(data)
        native=cells.Book(raw)
        normalized={k:cells.sig(v) for k,v in native.cells('Main').items()}
        with mock.object(cells,'DOM',minidom):
            reference=cells.Book(raw)
            expected={k:cells.sig(v) for k,v in reference.cells('Main').items()}
        self.assertEqual(normalized,expected)
        self.assertEqual(native.doc('xl/worksheets/sheet1.xml').toxml(),cells.DOM.parseString(data['xl/worksheets/sheet1.xml']).toxml())

    def test_cancellation_is_observed_during_cached_parsing(self):
        def cancel(phase):raise RuntimeError('已取消')
        session=cells.WorkbookMergeSession(None,cancel)
        with mock.object(cells.Book,'save',side_effect=AssertionError('must not save')):
            with self.assertRaisesRegex(RuntimeError,'已取消'):session.source(book(formula=False))


if __name__=='__main__':unittest.main()
