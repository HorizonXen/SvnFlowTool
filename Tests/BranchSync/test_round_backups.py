import json
import unittest
from unittest.mock import patch
from test_staged_sync import StagedSyncTests
import staged_sync


class RoundBackupsTests(unittest.TestCase):
    setUp = StagedSyncTests.setUp
    tearDown = StagedSyncTests.tearDown
    report_files = StagedSyncTests.report_files
    start = StagedSyncTests.start

    def test_every_write_keeps_distinct_original_and_properties(self):
        core = self.start()
        first, _ = staged_sync.backup_before_write(core, self.folder, 'a.txt', b'first', {'properties': {'x': 'eA=='}})
        second, _ = staged_sync.backup_before_write(core, self.folder, 'a.txt', b'second', {'properties': {}})
        self.assertNotEqual(first, second)
        self.assertEqual((first/'原件.txt').read_bytes(), b'first')
        self.assertEqual((second/'原件.txt').read_bytes(), b'second')
        self.assertEqual(json.loads((first/'record.json').read_text())['local']['properties'], {'x': 'eA=='})

    def test_backup_failure_prevents_working_copy_write(self):
        core = self.start()
        staged_sync.operate(core, self.folder, 'stage', 'a.txt')
        before = (self.target/'a.txt').read_bytes()
        with patch.object(staged_sync, 'backup_before_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): staged_sync.operate(core, self.folder, 'accept', 'a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(), before)

    def test_regeneration_keeps_old_candidate_and_does_not_write_target(self):
        core = self.start()
        original = (self.target/'a.txt').read_bytes()
        old = staged_sync.operate(core, self.folder, 'stage', 'a.txt')
        old_bytes = __import__('pathlib').Path(old['candidate']).read_bytes()
        staged_sync.operate(core, self.folder, 'regenerate', 'a.txt')
        archive = list((self.folder/'副本历史').glob('*/record.json'))
        self.assertEqual(len(archive), 1)
        record = json.loads(archive[0].read_text())
        self.assertEqual(__import__('pathlib').Path(record['candidate']).read_bytes(), old_bytes)
        self.assertEqual((self.target/'a.txt').read_bytes(), original)

    def test_missing_original_is_recorded_without_fake_empty_file(self):
        core = self.start()
        folder, record = staged_sync.backup_before_write(core, self.folder, 'new.txt', None, {})
        self.assertFalse(record['existed'])
        self.assertIsNone(record['before'])
        self.assertFalse((folder/'原件.txt').exists())
