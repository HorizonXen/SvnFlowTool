import json
import pathlib
import unittest
from test_staged_sync import StagedSyncTests
import staged_sync


class MergeRiskTests(unittest.TestCase):
    setUp = StagedSyncTests.setUp
    tearDown = StagedSyncTests.tearDown
    commit = StagedSyncTests.commit
    report_files = StagedSyncTests.report_files
    start = StagedSyncTests.start

    def small_change(self):
        before = b'one\ntwo\nthree\nfour\nfive\n'
        for wc in (self.dev, self.target): self.commit(wc, 'small.lua', before, 'seed')
        self.commit(self.dev, 'small.lua', before.replace(b'two', b'changed'))
        core = self.start()
        return core, staged_sync.operate(core, self.folder, 'stage', 'small.lua')

    def test_small_uncontested_change_can_batch_accept_without_remote_commit(self):
        core, entry = self.small_change()
        self.assertEqual(entry['risk']['level'], 'low')
        self.assertEqual(core.fingerprint(str(self.target)), [])
        staged_sync.operate(core, self.folder, 'accept-low', 'small.lua')
        self.assertIn(b'changed', (self.target/'small.lua').read_bytes())
        self.assertIn(b'two', core.run('cat', self.config['release']+'/small.lua').stdout)

    def test_conflict_needs_manual_review(self):
        core, entry = self.small_change()
        # Regenerate with a conflicting committed Release value.
        self.commit(self.target, 'small.lua', b'one\nrelease\nthree\nfour\nfive\n', 'release')
        core = self.start()
        entry = staged_sync.operate(core, self.folder, 'stage', 'small.lua')
        self.assertEqual(entry['risk']['level'], 'high')
        before = (self.target/'small.lua').read_bytes()
        with self.assertRaisesRegex(RuntimeError, '低风险评估'):
            staged_sync.operate(core, self.folder, 'accept-low', 'small.lua')
        self.assertEqual((self.target/'small.lua').read_bytes(), before)
        staged_sync.operate(core, self.folder, 'accept', 'small.lua')
        self.assertIn(b'changed', (self.target/'small.lua').read_bytes())

    def test_same_content_is_low_even_for_binary(self):
        self.commit(self.dev, 'binary.bin', b'\x00same')
        self.commit(self.target, 'binary.bin', b'\x00same', 'release')
        core = self.start()
        entry = staged_sync.operate(core, self.folder, 'stage', 'binary.bin')
        self.assertEqual(entry['risk']['level'], 'low')

    def test_large_change_and_new_file_are_high(self):
        core = self.start()
        entry = staged_sync.operate(core, self.folder, 'stage', 'a.txt')
        self.assertEqual(entry['risk']['level'], 'high')  # one of three lines
        self.commit(self.dev, 'new.lua', b'new')
        core = self.start()
        entry = staged_sync.operate(core, self.folder, 'stage', 'new.lua')
        self.assertEqual(entry['risk']['level'], 'high')

    def test_local_change_after_assessment_stops_batch(self):
        core, entry = self.small_change()
        (self.target/'small.lua').write_bytes(b'human edit')
        with self.assertRaisesRegex(RuntimeError, '本地文件.*变化'):
            staged_sync.operate(core, self.folder, 'accept-low', 'small.lua')
        self.assertEqual((self.target/'small.lua').read_bytes(), b'human edit')

    def test_missing_or_stale_assessment_cannot_batch_accept(self):
        core, entry = self.small_change()
        ledger = self.folder/'review.json'
        state = json.loads(ledger.read_text())
        state['items']['small.lua']['risk']['candidateHash'] = 'stale'
        core.write_json(ledger, state)
        with self.assertRaisesRegex(RuntimeError, '低风险评估'):
            staged_sync.operate(core, self.folder, 'accept-low', 'small.lua')
        state['items']['small.lua'].pop('risk')
        core.write_json(ledger, state)
        with self.assertRaisesRegex(RuntimeError, '低风险评估'):
            staged_sync.operate(core, self.folder, 'accept-low', 'small.lua')
        updated = staged_sync.operate(core, self.folder, 'assess', 'small.lua')
        self.assertEqual(updated['risk']['level'], 'low')
        self.assertEqual(core.fingerprint(str(self.target)), [])
