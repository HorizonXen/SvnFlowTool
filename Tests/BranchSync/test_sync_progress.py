import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from sync_progress import SyncProgress


class ProgressTests(unittest.TestCase):
    def test_events_keep_occurrence_time_and_monotonic_elapsed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': 'clock'}):
            with patch('sync_progress.time.monotonic', return_value=100):
                progress = SyncProgress(temporary, 'stage')
            with patch('sync_progress.time.monotonic', return_value=163.4), patch('sync_progress.time.time', return_value=1700000063.4):
                progress.phase('第一步')
            with patch('sync_progress.time.monotonic', return_value=165), patch('sync_progress.time.time', return_value=1700000065):
                progress.phase('第二步')
            events = json.loads((pathlib.Path(temporary)/'activity-clock.json').read_text())['events']
            self.assertEqual([event['elapsed'] for event in events], [63.4, 65])
            self.assertEqual([event['timestamp'] for event in events], [1700000063.4, 1700000065])

    def test_revision_counts_and_stdout_protocol(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': 'test'}):
            folder = pathlib.Path(temporary)
            (folder/'report.json').write_text(json.dumps({'fileItems':[{'path':'a.xlsx','revisions':[8,2,8]}]}))
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink):
                progress = SyncProgress(folder, 'stage', 'a.xlsx')
                progress.revision('a.xlsx', 8)
                progress.phase('合并表格')
                def run(*args):
                    self.assertEqual(json.loads((folder/'activity-test.json').read_text())['phase'], '下载文件内容')
                    return b'unchanged result'
                self.assertEqual(progress.wrap(run)('cat'), b'unchanged result')
            self.assertEqual(sink.getvalue(), '')
            value = json.loads((folder/'activity-test.json').read_text())
            self.assertEqual((value['revisionIndex'],value['revisionTotal']), (2,2))
            self.assertEqual(value['phase'], '合并表格')
            self.assertEqual(value['commands'],1)

    def test_runner_failure_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': 'failure'}):
            progress = SyncProgress(temporary,'stage')
            def fail(*args): raise RuntimeError('SVN failure')
            with self.assertRaisesRegex(RuntimeError, 'SVN failure'): progress.wrap(fail)('cat')
            self.assertEqual(progress.state['commands'],0)

    def test_telemetry_io_failure_does_not_block_operation(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': 'io'}):
            target = pathlib.Path(temporary)/'not-a-directory'; target.write_text('occupied')
            progress = SyncProgress(target,'accept')
            self.assertEqual(progress.wrap(lambda *args: 'ok')('update'), 'ok')

    def test_legacy_mode_does_not_emit_new_files(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': ''}):
            SyncProgress(temporary,'preview').phase('compute')
            self.assertEqual(list(pathlib.Path(temporary).iterdir()), [])

    def test_event_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'SVNFLOW_PROGRESS_TOKEN': 'bounded'}):
            progress = SyncProgress(temporary,'stage')
            for i in range(100): progress.phase(str(i))
            self.assertEqual(len(progress.state['events']), 40)
            self.assertEqual(progress.state['events'][-1]['message'],'99')

class SupervisorTests(unittest.TestCase):
    def test_cancel_stops_blocking_worker_and_its_child(self):
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            worker = root/'worker.py'
            # The child ignores TERM and inherits the output pipe. A parent-only
            # cancellation would leave communicate() hanging for 60 seconds.
            worker.write_text("import pathlib,subprocess,sys,time\n"
                              "subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'])\n"
                              "pathlib.Path(__file__).with_suffix('.ready').touch()\ntime.sleep(60)\n")
            env = dict(os.environ, SVNFLOW_PROGRESS_TOKEN='cancel-test')
            script = pathlib.Path(__file__).resolve().parents[2]/'scripts/sync_progress.py'
            process = subprocess.Popen([sys.executable,str(script),str(worker),'authors','--folder',temporary],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                deadline = time.monotonic()+5
                while not worker.with_suffix('.ready').exists() and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertTrue(worker.with_suffix('.ready').exists())
                started = time.monotonic()
                (root/'cancel-cancel-test').touch()
                output, error = process.communicate(timeout=4)
                self.assertEqual(process.returncode,130,error)
                self.assertLess(time.monotonic()-started,3)
                self.assertEqual(json.loads((root/'activity-cancel-test.json').read_text())['status'],'cancelled')
                self.assertEqual(output,b'')
            finally:
                if process.poll() is None: process.kill(); process.wait()

    def test_remaining_check_can_be_cancelled_before_launch(self):
        from sync_progress import supervise
        with tempfile.TemporaryDirectory() as temporary:
            pathlib.Path(temporary, 'cancel-stop').touch()
            self.assertEqual(supervise([sys.executable, 'nonexistent.py', 'remaining-diff'], temporary, 'stop'), 130)
            self.assertEqual(supervise([sys.executable, 'nonexistent.py', 'authors'], temporary, 'stop'), 130)
            self.assertEqual(supervise([sys.executable, 'nonexistent.py', 'scope-preview'], temporary, 'stop'), 130)
            self.assertEqual(supervise([sys.executable, 'nonexistent.py', 'scope-check'], temporary, 'stop'), 130)

    def test_write_actions_cannot_enter_supervisor(self):
        from sync_progress import supervise
        for action in ('accept','accept-low','apply','withdraw-row'):
            with self.assertRaises(ValueError):
                supervise([sys.executable,'nonexistent.py',action],'.','test')

    def test_cancel_bypasses_ordinary_error_handlers(self):
        from sync_progress import SyncCancelled
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, SVNFLOW_PROGRESS_TOKEN='stop'):
            progress = SyncProgress(temporary,'assess')
            pathlib.Path(temporary,'cancel-stop').touch()
            with self.assertRaises(SyncCancelled):
                try: progress.phase('长计算后')
                except Exception: self.fail('cancellation must not become a risk reason')

    def test_success_preserves_worker_stdout(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            worker=pathlib.Path(temporary,'worker.py');worker.write_text('print(\'{"ok": true}\')')
            script=pathlib.Path(__file__).resolve().parents[2]/'scripts/sync_progress.py'
            result=subprocess.run([sys.executable,str(script),str(worker),'stage','--folder',temporary],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'ok':True})
