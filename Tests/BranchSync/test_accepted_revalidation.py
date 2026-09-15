import json
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
import staged_sync as staged
import file_sync as files


class AcceptedRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        subprocess.run(['svnadmin', 'create', str(self.root/'repo')], check=True, capture_output=True)
        self.wc = self.root/'wc'
        self.svn('checkout', (self.root/'repo').as_uri(), str(self.wc))
        self.target = self.wc/'a.txt'
        self.target.write_bytes(b'baseline')
        self.svn('add', str(self.target)); self.svn('commit', '-m', 'fixture', str(self.wc))
        self.folder = self.root/'batch'; self.folder.mkdir()
        self.report = {'config': {'target':str(self.wc)}, 'fileItems':[]}
        self.core = types.SimpleNamespace(run=self.svn, write_json=self.write)

    def svn(self, *args, **kwargs):
        return subprocess.run(['svn', *map(str,args)], check=kwargs.get('check', True), capture_output=True)

    def write(self, path, data):
        path.write_text(json.dumps(data))

    def save(self, data=b'candidate', props=None, pending=False):
        self.entry = {'path':'a.txt', 'status':'accepted', 'candidateHash':files.data_hash(data),
                      'properties':props or {}}
        self.state = {'mode':'review-v1', 'reportHash':files.report_hash(self.report), 'items':{'a.txt':self.entry}}
        if pending: self.state['pending'] = 'a.txt'
        self.write(self.folder/'report.json', self.report)
        self.write(self.folder/'review.json', self.state)

    def status(self):
        staged.repair_review(self.core, self.folder)
        return json.loads((self.folder/'review.json').read_text())['items']['a.txt']['status']

    def test_revert_invalidates_and_preserves_working_file(self):
        self.target.write_bytes(b'candidate'); self.save()
        self.assertEqual(self.status(), 'accepted')
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')
        self.assertEqual(self.target.read_bytes(), b'baseline')

    def test_commit_does_not_invalidate_matching_result(self):
        self.target.write_bytes(b'candidate'); self.save()
        self.svn('commit', '-m', 'candidate', str(self.wc))
        self.assertEqual(self.status(), 'accepted')

    def test_property_only_revert(self):
        self.svn('propset', 'custom:flag', 'yes', str(self.target))
        self.save(b'baseline', staged.encoded({'custom:flag':b'yes'}))
        self.assertEqual(self.status(), 'accepted')
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')

    def test_deleted_file_revert(self):
        self.svn('delete', str(self.target)); self.save(None)
        self.assertEqual(self.status(), 'accepted')
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')

    def test_added_file_revert_even_when_bytes_remain(self):
        self.svn('delete', str(self.target)); self.svn('commit', '-m', 'delete', str(self.wc))
        self.target.write_bytes(b'candidate'); self.svn('add', str(self.target)); self.save()
        self.assertEqual(self.status(), 'accepted')
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')
        self.assertEqual(self.target.read_bytes(), b'candidate')

    def test_pending_write_evidence_untouched(self):
        self.save(pending=True)
        before = (self.folder/'review.json').read_bytes()
        self.assertEqual(self.status(), 'accepted')
        self.assertEqual((self.folder/'review.json').read_bytes(), before)

    def test_restored_content_recovers_and_clears_failure(self):
        self.target.write_bytes(b'candidate'); self.save()
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')
        self.target.write_bytes(b'candidate')
        before = self.target.read_bytes()
        self.assertEqual(self.status(), 'accepted')
        self.assertEqual(self.target.read_bytes(), before)
        entry = json.loads((self.folder/'review.json').read_text())['items']['a.txt']
        self.assertNotIn('preparationIssue', entry)
        self.assertNotIn('a.txt', json.loads((self.folder/'review-failures.json').read_text()))
        self.assertEqual(staged.repair_review(self.core, self.folder), [])

    def test_restored_properties_recover(self):
        self.svn('propset', 'custom:flag', 'yes', str(self.target))
        self.save(b'baseline', staged.encoded({'custom:flag':b'yes'}))
        self.svn('revert', str(self.target))
        self.assertEqual(self.status(), 'invalidated')
        self.svn('propset', 'custom:flag', 'yes', str(self.target))
        self.assertEqual(self.status(), 'accepted')

    def test_matching_bytes_with_conflict_never_recovers(self):
        self.save(); self.assertEqual(self.status(), 'invalidated')
        self.target.write_bytes(b'candidate')
        local = staged.local_state(self.core, self.report['config'], 'a.txt')
        for conflict in ({'props':'conflicted'}, {'tree-conflicted':'true'}):
            with self.subTest(conflict=conflict):
                value = dict(local, status=dict(local['status'], **conflict))
                with mock.patch.object(staged, 'local_state', return_value=value):
                    self.assertEqual(self.status(), 'invalidated')
        self.assertEqual(self.status(), 'accepted')

    def test_ready_or_skipped_is_not_auto_accepted(self):
        self.target.write_bytes(b'candidate'); self.save()
        for status in ('ready', 'skipped'):
            self.entry.update(status=status, candidate=None, baseline=None)
            self.write(self.folder/'review.json', self.state)
            self.assertEqual(self.status(), status)

    def test_changed_report_cannot_restore(self):
        self.save(); self.assertEqual(self.status(), 'invalidated')
        self.target.write_bytes(b'candidate')
        self.write(self.folder/'report.json', dict(self.report, changed=True))
        with self.assertRaisesRegex(RuntimeError, '合入报告已变化'):
            self.status()

    def test_unversioned_result_recovers_only_after_svn_add(self):
        self.svn('delete', str(self.target)); self.svn('commit', '-m', 'delete', str(self.wc))
        self.target.write_bytes(b'candidate'); self.save()
        self.assertEqual(self.status(), 'invalidated')
        self.svn('add', str(self.target))
        self.assertEqual(self.status(), 'accepted')


if __name__ == '__main__': unittest.main()
