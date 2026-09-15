import json
import pathlib
import plistlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'scripts'))
import branch_sync as sync

class ConfigTests(unittest.TestCase):
    def load(self, dev_tail='', release_tail=''):
        copies=[{'id':'1','path':'/dev'+dev_tail},{'id':'2','path':'/release'+release_tail}]
        def info(path):
            dev=path.startswith('/dev')
            prefix='/dev' if dev else '/release'
            return {'url':'svn://host/repo/Branch/'+('Dev/Dev_Name' if dev else 'Release/Release_Name')+path[len(prefix):], 'root':'svn://host/repo','uuid':'same'}
        with patch.object(sync,'merge_copies',return_value=(copies[0],copies[1])), patch.object(sync,'info',side_effect=info):
            return sync.load_config()
    def test_distinct_branch_names_use_release_root(self):
        config=self.load()
        self.assertEqual(config['target'],'/release')
        self.assertEqual(config['sourceName'],'dev')
        self.assertEqual(config['targetName'],'release')
    def test_client_scope_aligns_to_release_child(self):
        self.assertEqual(self.load('/Client')['target'],'/release/Client')
    def test_scope_mismatch_blocks(self):
        with self.assertRaises(RuntimeError): self.load('/Client','/Server')

class InventoryTests(unittest.TestCase):
    def inventory(self, path='Game Kit (Read Me).unity', url=None, kind='file', depth='infinity'):
        tree=sync.ET.Element('info');entry=sync.ET.SubElement(tree,'entry',path='/release/'+path,kind=kind)
        sync.ET.SubElement(entry,'url').text=url or 'svn://host/repo/release/Game%20Kit%20(Read%20Me).unity'
        wc=sync.ET.SubElement(entry,'wc-info');sync.ET.SubElement(wc,'depth').text=depth
        return tree
    def check(self, **kwargs):sync.validate_inventory(self.inventory(**kwargs),{'target':'/release','release':'svn://host/repo/release'})
    def test_parentheses_encoding_is_equivalent(self):self.check()
    def test_unicode_and_reserved_punctuation(self):
        self.check(path="表 (1)!+$@#%.xlsx",url='svn://host/repo/release/%E8%A1%A8%20(1)!+$@%23%25.xlsx')
    def test_literal_percent_is_not_decoded_twice(self):
        self.assertFalse(sync.same_repository_url('svn://host/r/a%2520b','svn://host/r/a%20b'))
        self.assertFalse(sync.same_repository_url('svn://host/r/a%2Fb','svn://host/r/a/b'))
    def test_real_switch_is_still_blocked(self):
        with self.assertRaisesRegex(RuntimeError,'切换'):self.check(url='svn://host/repo/dev/Game%20Kit%20(Read%20Me).unity')
    def test_sparse_directory_is_still_blocked(self):
        with self.assertRaisesRegex(RuntimeError,'未完整检出'):self.check(path='folder',url='svn://host/repo/release/folder',kind='dir',depth='immediates')
    def test_file_depth_is_not_directory_sparsity(self):self.check(depth='empty')

if __name__ == '__main__': unittest.main()
