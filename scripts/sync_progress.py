"""Per-command, atomic progress side channel; stdout remains the result protocol."""
import json
import os
import pathlib
import threading
import time


class SyncCancelled(BaseException):
    """Must not be downgraded to a merge conflict by broad Exception handlers."""


class SyncProgress:
    def __init__(self, folder, action, path=None):
        self.folder = pathlib.Path(folder)
        self.token = os.environ.get('SVNFLOW_PROGRESS_TOKEN', '')
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.state = dict(token=self.token, action=action, path=path or '', phase='准备运行环境',
                          revision=0, revisionIndex=0, revisionTotal=0, commands=0, events=[])
        self.revisions = []
        try:
            report = json.loads((self.folder/'report.json').read_text())
            item = next(i for i in report.get('fileItems', []) if i['path'] == path)
            self.revisions = sorted(set(item['revisions']))
        except (OSError, ValueError, KeyError, StopIteration):
            pass
        self.state['revisionTotal'] = len(self.revisions)
        self.log('操作：'+action+'；文件：'+(path or ''))
        self.emit()

    def emit(self):
        if not self.token: return  # Legacy callers keep their existing progress protocol.
        with self.lock:
            self.state['elapsed'] = round(time.monotonic()-self.started, 1)
            self.state['updatedAt'] = time.time()
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                target = self.folder/('activity-'+self.token+'.json')
                temporary = target.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.state, ensure_ascii=False))
                temporary.replace(target)
            except OSError:
                pass  # Telemetry failure must never alter merge/write semantics.

    def phase(self, title):
        if self.token and self.state['action'] in ('stage','regenerate','scope-preview','scope-check','catalog','assess','remaining-diff','authors') and (self.folder/('cancel-'+self.token)).exists():
            raise SyncCancelled('已取消生成；未写入 Release，已生成的副本仍保留')
        with self.lock:
            self.state['phase'] = title
            events = self.state['events']
            if not events or events[-1]['message'] != title:
                events.append(dict(elapsed=round(time.monotonic()-self.started, 1),
                                   timestamp=time.time(), message=title))
                self.log(title)
                del events[:-40]
            self.emit()

    def log(self, message):
        if not self.token:return
        try:
            self.folder.mkdir(parents=True,exist_ok=True)
            with (self.folder/('operation-'+self.token+'.log')).open('a') as out:
                out.write(f"[{time.monotonic()-self.started:.1f}s] {message}\n")
        except OSError:pass

    def finish(self, error=None):
        with self.lock:
            self.state['status']='cancelled' if isinstance(error, SyncCancelled) else 'failed' if error is not None else 'completed'
            self.state['error']=str(error) if error is not None else ''
            self.state['phase']=('失败：'+str(error)) if error is not None else '完成'
            self.state['logFile']='operation-'+self.token+'.log'
            self.log(self.state['phase'])
            if error is not None:
                import traceback
                self.log(traceback.format_exc())
            self.emit()

    def item(self, path):
        with self.lock:
            active = self.state.setdefault('activePaths', [])
            if path not in active: active.append(path)
            self.emit()

    def remaining(self, result):
        with self.lock:
            self.state['remaining'] = json.loads(json.dumps(result))
            completed = set(result['noDiffPaths']) | set(result['differentPaths']) | set(result['errors'])
            self.state['activePaths'] = [p for p in self.state.get('activePaths', []) if p not in completed]
            self.emit()

    def files(self, completed, total):
        with self.lock:
            self.state.update(filesCompleted=completed, filesTotal=total)
            self.emit()

    def metrics(self, path, values):
        with self.lock:
            self.state.setdefault('performance', {})[path] = values
            self.emit()

    def revision(self, path, revision):
        with self.lock:
            self.state.update(path=path, revision=revision,
                              revisionIndex=self.revisions.index(revision)+1 if revision in self.revisions else 0)
            self.phase('校验提交作者 · r'+str(revision))

    def wrap(self, runner):
        titles = {'info': '核对分支与版本', 'log': '读取 SVN 提交记录', 'cat': '下载文件内容',
                  'proplist': '读取 SVN 文件属性', 'status': '检查本地文件状态',
                  'update': '更新已确认文件', 'propset': '写入已确认属性',
                  'propdel': '移除已确认属性', 'add': '登记新增文件', 'delete': '登记删除文件'}
        def run(*args, **kwargs):
            previous = self.state['phase']
            self.phase(titles.get(str(args[0]), '执行 SVN 操作'))
            try:
                result = runner(*args, **kwargs)
                with self.lock:
                    self.state['commands'] += 1
                return result
            finally:
                self.phase(previous)
        return run


def supervise(command, folder, token):
    """Cancel preparation even inside an uninstrumented calculation or SVN read.

    The worker owns a separate process group so its read-only SVN children cannot
    keep stdout pipes open after cancellation. Confirmed write actions are refused.
    """
    import signal
    import subprocess
    if len(command) < 3 or command[2] not in ('stage','regenerate', 'scope-preview','scope-check','catalog', 'assess', 'remaining-diff', 'authors'):
        raise ValueError('取消监控仅适用于生成副本和读取范围')
    marker = pathlib.Path(folder)/('cancel-'+token)
    def cancelled():
        return bool(token) and marker.exists()
    if cancelled():
        return 130
    process = subprocess.Popen(command, start_new_session=True)
    while process.poll() is None:
        if cancelled():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            # Include any descendants that survived their parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return 130
        time.sleep(.1)
    return process.returncode


if __name__ == '__main__':
    import sys
    arguments = sys.argv[1:]
    folder = pathlib.Path(arguments[arguments.index('--folder')+1])
    token = os.environ.get('SVNFLOW_PROGRESS_TOKEN', '')
    result = supervise([sys.executable, *arguments], folder, token)
    if result == 130:
        progress = SyncProgress(folder, arguments[1])
        progress.finish(SyncCancelled('已取消生成；未写入 Release，已生成的副本仍保留'))
        print('已取消生成；未写入 Release，已生成的副本仍保留', file=sys.stderr)
    sys.exit(result)
