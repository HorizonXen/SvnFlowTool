import unittest
from unittest.mock import patch
from test_deletion_history import HistoryFixture
from test_config_identity import table
from test_workbook import book
from workbook_cells import WorkbookMergeSession, logical_signature
from workbook_history import DeletionHistory, inventory
from file_sync import SourceAnalysisCache, merge_data


class AnalysisReuseTests(unittest.TestCase):
    def test_saved_projection_identity_does_not_depend_on_wall_clock(self):
        import zipfile
        from workbook_cells import Book
        data=book(a='1',formula=False)
        with patch.object(zipfile.time,'localtime',return_value=(2026,1,1,0,0,0,0,0,0)):
            first=Book(data).save()
        with patch.object(zipfile.time,'localtime',return_value=(2026,2,1,0,0,0,0,0,0)):
            second=Book(data).save()
        self.assertEqual(first,second)
        self.assertEqual(logical_signature(first),logical_signature(data))

    def test_history_coverage_does_not_oscillate_and_payload_promotes(self):
        data=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))])
        core=HistoryFixture(data,[(6,'other',data)])
        session=WorkbookMergeSession(data)
        audit=DeletionHistory(core,core.config,'config.xlsx',session,5)
        name=next(iter(session.source(data).sheets))
        def request(ids,payloads=False):
            return audit.snapshot({'revision':6},{name:(ids,payloads)})[name]
        first=request({('1',)})
        second=request({('2',)})
        self.assertTrue(second['complete'])
        self.assertIn(('1',),second['keyed'])
        self.assertIn(('2',),second['keyed'])
        self.assertEqual(request({('1',)})['keyed'][('1',)],first['keyed'][('1',)])
        self.assertEqual(session.metrics['history_builds'],2)
        full=request({('2',)},True)
        self.assertTrue(full['withPayloads'])
        self.assertIs(request({('1',)}),full)
        self.assertEqual(session.metrics['history_builds'],3)

    def test_history_cache_isolated_by_path_and_config(self):
        data=table([(6,dict(ID=1,value=10))]);core=HistoryFixture(data,[])
        s=WorkbookMergeSession(data)
        a=DeletionHistory(core,core.config,'a.xlsx',s,5)
        b=DeletionHistory(core,core.config,'b.xlsx',s,5)
        a.snapshots[6,'Main']=None
        self.assertEqual(b.snapshots,{})

    def test_inventory_does_not_pin_row_trees_on_source(self):
        data=table([(6,dict(ID=1,value=10))]);s=WorkbookMergeSession(data)
        source=s.source(data);name=next(iter(source.sheets))
        inventory(source,name)
        self.assertFalse(hasattr(source,'inventory_cache'))
        from workbook_cells import Book
        target=Book(data)
        self.assertIsNot(inventory(target,name),inventory(target,name))

    def test_projection_cache_retains_direction_and_target_identity(self):
        a,b,t=[book(a=str(v),b='77',formula=False) for v in (1,2,3)]
        s=WorkbookMergeSession(t);calls=[]
        def project(x,y,z):
            def compute():
                calls.append(1)
                return merge_data(x,y,z,'a.xlsx',latest=True,scope_projection=True,workbook_session=s)
            return s.project(x,y,z,compute)
        for x,y,z in [(a,b,t),(b,a,t),(a,b,a),(a,b,t)]:
            self.assertEqual(logical_signature(project(x,y,z)),logical_signature(
                merge_data(x,y,z,'a.xlsx',latest=True,scope_projection=True)))
        self.assertEqual(len(calls),3)
        self.assertEqual(s.metrics['projection_hits'],1)
        s.projection_limit=1
        s.project(t,a,b,lambda:b'x')
        self.assertLessEqual(s.projection_bytes,1)

    def test_cached_projection_checks_cancellation_and_does_not_cache_errors(self):
        s=WorkbookMergeSession(None)
        with self.assertRaises(ValueError):s.project(b'a',b'b',b'c',lambda:(_ for _ in ()).throw(ValueError()))
        self.assertEqual(s.projections,{})
        s.project(b'a',b'b',b'c',lambda:b'ok')
        def cancel(_):raise RuntimeError('cancelled')
        s.phase=cancel
        with self.assertRaisesRegex(RuntimeError,'cancelled'):s.project(b'a',b'b',b'c',lambda:b'wrong')

    def test_source_analysis_rebinds_when_scope_or_content_changes(self):
        cache=SourceAnalysisCache();config={'author':'a','snapshot':1};item={'path':'a.xlsx','revisions':[1]}
        one=cache.bind(config,item,b'one',None)
        self.assertIs(cache.bind(config,item,b'one',None),one)
        for changed_config,changed_item,data in [(dict(config,author='b'),item,b'one'),
                (config,dict(item,revisions=[2]),b'one'),(config,item,b'two')]:
            self.assertIsNot(cache.bind(changed_config,changed_item,data,None),one)
        cache.clear();self.assertIsNone(cache.session)

import test_file_sync as fixtures
import types
import file_sync

class TargetAnalysisTests(unittest.TestCase):
    setUp=fixtures.FileSyncTests.setUp
    tearDown=fixtures.FileSyncTests.tearDown
    commit=fixtures.FileSyncTests.commit
    report_files=fixtures.FileSyncTests.report_files

    def test_two_targets_reuse_source_projection_but_keep_distinct_values(self):
        self.commit(self.dev,'config.xlsx',book(a='1',b='77',formula=False))
        self.commit(self.dev,'config.xlsx',book(a='2',b='77',formula=False))
        self.commit(self.dev,'config.xlsx',book(a='3',b='99',formula=False),author='other')
        self.report_files()
        item=next(i for i in self.report['fileItems'] if i['path']=='config.xlsx')
        # Restrict to the edit, not the initial file-add commit.
        item=dict(item,revisions=[item['revisions'][-1]])
        core=types.SimpleNamespace(**vars(fixtures.sync));core.source_analysis=SourceAnalysisCache()
        for target in (book(a='9',b='55',formula=False),book(a='3',b='44',formula=False)):
            actual=file_sync.build_plan(core,self.report,item,True,baseline=(target,{}))
            expected=file_sync.build_plan(fixtures.sync,self.report,item,True,baseline=(target,{}))
            self.assertEqual(logical_signature(actual['data']),logical_signature(expected['data']))
            self.assertEqual(actual['same'],expected['same'])
            self.assertEqual(actual['deletionHistory'],expected['deletionHistory'])
        self.assertGreater(core.source_analysis.session.metrics['projection_hits'],0)
        core.source_analysis.clear()

if __name__=='__main__':unittest.main()
