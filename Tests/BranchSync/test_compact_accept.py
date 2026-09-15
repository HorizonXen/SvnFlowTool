import unittest
from unittest.mock import patch
from test_workbook_native import fake_excel
from pathlib import Path
import test_staged_sync as staged_tests
from test_config_identity import table, values
import staged_sync

class CompactAcceptTests(unittest.TestCase):
    setUp=staged_tests.StagedSyncTests.setUp
    tearDown=staged_tests.StagedSyncTests.tearDown
    commit=staged_tests.StagedSyncTests.commit
    report_files=staged_tests.StagedSyncTests.report_files
    start=staged_tests.StagedSyncTests.start

    @patch("workbook_native.apply_edits", side_effect=fake_excel)
    def test_review_and_install_share_final_rows(self, native):
        before=table([(6,dict(ID=1,value=10)),(10,dict(ID=2,value=20))])
        release=table([(6,dict(ID=1,value=10)),(10,dict(ID=2,value=20,other=99))])
        after=table([(6,dict(ID=2,value=21))])
        self.commit(self.dev,'compact.xlsx',before,'other')
        self.commit(self.target,'compact.xlsx',release,'release')
        self.commit(self.dev,'compact.xlsx',after)
        core=self.start()
        entry=staged_sync.operate(core,self.folder,'stage','compact.xlsx')
        candidate=Path(entry['candidate']).read_bytes()
        self.assertEqual(values(candidate)['A9'],'2')
        self.assertEqual(values(candidate)['B9'],'21')
        self.assertEqual((self.target/'compact.xlsx').read_bytes(),release)
        entry=staged_sync.operate(core,self.folder,'withdraw-row','compact.xlsx',sheet='Main',row=9)
        reviewed=Path(entry['candidate']).read_bytes()
        self.assertEqual(values(reviewed)['B9'],'20')
        entry=staged_sync.operate(core,self.folder,'accept','compact.xlsx')
        actual=(self.target/'compact.xlsx').read_bytes()
        self.assertEqual(values(actual),{'A9':'2','B9':'20','C9':'99'})
        self.assertEqual(Path(entry['candidate']).read_bytes(),actual)
        self.assertEqual(actual,reviewed)
        self.assertFalse((self.folder/'整理前副本/compact.xlsx').exists())
        self.assertEqual((self.folder/'本地原件/compact.xlsx').read_bytes(),release)
        self.assertEqual(entry['status'],'accepted')
        self.assertEqual(entry['nativeWrite']['sheets'],{'Main':1})
