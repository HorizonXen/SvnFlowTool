import fcntl
import pathlib
import tempfile
import threading
import types
import unittest

import test_sync  # Configure the repository script import path.
import staged_sync
from sync_progress import SyncCancelled


class OperationQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = pathlib.Path(self.temp.name) / 'operation.lock'
        self.owner = path.open('a')
        self.waiter = path.open('a')
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def tearDown(self):
        self.waiter.close()
        self.owner.close()
        self.temp.cleanup()

    def test_preparation_waits_until_owner_releases_lock(self):
        phases = []
        release = threading.Timer(.05, lambda: fcntl.flock(self.owner, fcntl.LOCK_UN))
        release.start()
        try:
            staged_sync.acquire_operation_lock(types.SimpleNamespace(sync_phase=phases.append),
                                               self.waiter, wait=True, timeout=2)
            self.assertTrue(phases)
            with self.assertRaises(BlockingIOError):
                fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            release.join()

    def test_queued_preparation_can_be_cancelled_without_stealing_lock(self):
        def cancel(_):
            raise SyncCancelled('cancelled')
        with self.assertRaises(SyncCancelled):
            staged_sync.acquire_operation_lock(types.SimpleNamespace(sync_phase=cancel), self.waiter, wait=True)
        with self.assertRaises(BlockingIOError):
            fcntl.flock(self.waiter, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_wait_timeout_retains_owner_lock(self):
        with self.assertRaisesRegex(RuntimeError, '其他合入任务'):
            staged_sync.acquire_operation_lock(types.SimpleNamespace(), self.waiter, wait=True, timeout=.01)
        with self.assertRaises(BlockingIOError):
            fcntl.flock(self.waiter, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_write_actions_do_not_wait_or_retry(self):
        def unexpected(_):
            self.fail('Write operation must not queue')
        with self.assertRaisesRegex(RuntimeError, '其他合入任务'):
            staged_sync.acquire_operation_lock(types.SimpleNamespace(sync_phase=unexpected), self.waiter)


if __name__ == '__main__':
    unittest.main()
