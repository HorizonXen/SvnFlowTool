import unittest
from test_config_identity import table, values
from test_keyless_auxiliary import auxiliary
from file_sync import latest_scope_patches, merge_data


def latest(a,b,dev,release):
    project=lambda x,y,t:merge_data(x,y,t,'config.xlsx',latest=True,scope_projection=True)
    for left,right in latest_scope_patches(a,b,dev,project):
        release=merge_data(left,right,release,'config.xlsx',latest=True)
    return release


class LatestScopeTests(unittest.TestCase):
    def test_blank_storage_change_does_not_claim_later_foreign_value(self):
        absent=table([(6,dict(ID=1,value=10))])
        blank=table([(6,dict(ID=1,value=10,other=''))])
        dev=table([(6,dict(ID=1,value=10,other='foreign'))])
        for a,b in ((absent,blank),(blank,absent)):
            for release in (table([(6,dict(ID=1,value=90,other='release'))]),table([(6,dict(ID=2,value=90,other='release'))])):
                with self.subTest(direction=a==absent,release=values(release)):
                    self.assertEqual(values(latest(a,b,dev,release)),values(release))

    def test_blank_style_change_preserves_later_value_and_cached_sources(self):
        from test_workbook import parts,pack
        from workbook_cells import WorkbookMergeSession,Book
        absent=table([(6,dict(ID=1,value=10))]);p=parts(absent)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</sheetData>',b'<row r="8"><c r="A8"><v>2</v></c><c r="C8" s="1"/></row></sheetData>')
        styled=pack(p)
        base=table([(6,dict(ID=1,value=10)),(8,dict(ID=2))])
        dev=table([(6,dict(ID=1,value=10)),(8,dict(ID=2,other='foreign'))])
        session=WorkbookMergeSession(dev);cached=session.source(base);original=cached.cells('Main').copy()
        projected=merge_data(base,styled,dev,'config.xlsx',latest=True,scope_projection=True,workbook_session=session)
        self.assertIn('foreign',Book(projected).cells('Main')['C8'].toxml())
        self.assertEqual(cached.cells('Main'),original)

    def test_later_deleted_id_removes_only_that_record(self):
        a=table([(6,dict(ID=1,value=1000)),(7,dict(ID=2,value=2))])
        b=table([(6,dict(ID=1,value=500)),(7,dict(ID=2,value=2))])
        dev=table([(6,dict(ID=2,value=99))])
        release=table([(10,dict(ID=1,value=900)),(6,dict(ID=2,value=8))])
        result=values(latest(a,b,dev,release))
        self.assertNotIn('A10',result)
        self.assertEqual(result['A6'],'2');self.assertEqual(result['B6'],'8')
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
            merge_data(a,b,dev,'config.xlsx',latest=True)

    def test_cleared_auxiliary_scope_keeps_latest_unrelated_change_out(self):
        a=auxiliary([(9,{'E':124,'F':1457533})])
        b=auxiliary([])
        dev=auxiliary([],[(6,dict(ID=1,value=1200))])
        release=auxiliary([(22,{'E':124,'F':1457533})],[(6,dict(ID=1,value=900))])
        result=latest(a,b,dev,release)
        self.assertNotIn('E22',values(result));self.assertNotIn('F22',values(result))
        self.assertEqual(values(result)['B6'],'900')
        edited=auxiliary([(22,{'E':124,'F':0})],[(6,dict(ID=1,value=900))])
        with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
            latest(a,b,dev,edited)
