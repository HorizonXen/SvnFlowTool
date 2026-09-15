"""Build reviewable Release candidates without touching the working copy."""
import base64
import contextlib
import datetime as dt
from platform_lock import try_lock
import hashlib
import json
import os
import pathlib
import re
import tempfile
import time
import uuid
import shutil
import xml.etree.ElementTree as ET
import file_sync as files
import galaxy_sync
import deletion_guard

AUTHOR_ISOLATION_VERSION = 9


def include_local_changes(core, config, path, local, data, props):
    """Replay the WC delta onto a candidate with the existing semantic splitters.

    This is read-only. A differing working revision alone is not a local edit.
    Overlapping edits must never be silently resolved in favour of either side.
    """
    status = local['status']
    if (local['item'] not in ('normal', 'modified', 'none')
            or status.get('props') not in (None, 'none', 'normal', 'modified')
            or status.get('tree-conflicted') == 'true'
            or status.get('switched') == 'true'
            or 'svn:special' in local['properties']):
        raise RuntimeError('Release 状态不支持自动生成：' + local['item'])
    target = safe_path(config['target'], path)
    original = target.read_bytes() if target.exists() else None
    if files.data_hash(original) != local['hash']:
        raise RuntimeError('生成期间本地文件发生变化，请重新生成')
    dirty = local['item'] == 'modified' or status.get('props') == 'modified'
    if not dirty:
        return data, props, False
    metadata = core.info(str(target))
    if metadata['uuid'] != config['uuid'] or not core.same_repository_url(metadata['url'], core.urlpath(config['release'], path)):
        raise RuntimeError('Release 本地文件指向其他仓库位置')
    base = core.run('cat', '-r', 'BASE', '--', str(target)+'@').stdout
    base_props = files.properties(core, str(target), 'BASE')
    try:
        merged = files.merge_data(base, original, data, path)
        merged_props = files.merge_properties(base_props, decoded(local['properties']), props)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError('本地修改与待合入内容无法独立拆分：' + str(error)) from error
    if local_state(core, config, path) != local:
        raise RuntimeError('生成期间本地文件发生变化，请重新生成')
    return merged, merged_props, True


def normalize_directories(directories):
    """None means all; an empty selection never silently expands to all."""
    if directories is None: return None
    result = []
    for value in sorted(set(directories)):
        if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or any(p in ('', '.', '..') for p in value.split('/')):
            raise RuntimeError('请选择有效的分支内相对目录')
        if not any(value == parent or value.startswith(parent + '/') for parent in result): result.append(value)
    if not result: raise RuntimeError('请选择至少一个合并目录')
    return result


def in_directories(path, directories):
    return directories is None or any(path == d or path.startswith(d + '/') for d in directories)


def scope_preview(core, author, days):
    if not author.strip() or author != author.strip(): raise RuntimeError('请输入 SVN 作者账号')
    if not 1 <= days <= 365: raise RuntimeError('查询天数必须在 1 至 365 之间')
    config = dict(core.load_config())
    end = dt.datetime.now(dt.timezone.utc)
    stamp = lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ')
    start, end = stamp(end-dt.timedelta(days=days)), stamp(end)
    config.update(author=author, days=days, start=start, end=end,
                  snapshot=core.info(config['release'], 'HEAD')['revision'])
    tree = core.logs(config['dev'], start, end)
    rows = core.records(tree, config['dev'], config['root'], author, start, end)
    rows = [row for row in rows if row['revision'] <= config['snapshot']]
    return {'schema': 3, 'config': config, 'dev': rows, 'fileItems': files.group_files(rows)}


def scoped_report(report, directories, revisions=None):
    import copy
    result = copy.deepcopy(report)
    directories = normalize_directories(directories)
    total = sum(pathlib.PurePosixPath(i['path']).name.lower() != 'pmdata.bin' for i in report['fileItems'])
    selected = None
    if revisions is not None:
        if not revisions or any(type(r) is not int or r <= 0 for r in revisions):
            raise RuntimeError('请选择至少一条有效 SVN 提交记录')
        selected = set(revisions)
        if not selected.issubset({row['revision'] for row in report['dev']}):
            raise RuntimeError('提交记录不在当前作者和时间范围内，请重新读取')
    rows = []
    for row in result['dev']:
        if selected is not None and row['revision'] not in selected: continue
        row['paths'] = [p for p in row['paths'] if in_directories(p['path'], directories)]
        if row['paths']: rows.append(row)
    result['dev'] = rows
    result['fileItems'] = files.group_files(rows)
    count = sum(pathlib.PurePosixPath(i['path']).name.lower() != 'pmdata.bin' for i in result['fileItems'])
    result['config'].update(scopeDirectories=directories, scopeTotal=total, scopeExcluded=total-count)
    if selected is not None: result['config']['scopeRevisions'] = sorted(selected)
    return result


def catalog(core, folder, author, days, directories=None, preview=None, revisions=None):
    directories = normalize_directories(directories)
    if preview is None:
        report = scope_preview(core, author, days)
    else:
        report = json.loads(pathlib.Path(preview).read_text())
        live = core.load_config()
        if any(report['config'].get(k) != live.get(k) for k in ('dev', 'release', 'target', 'root', 'uuid')):
            raise RuntimeError('工作副本配置已变化，请重新读取文件清单')
        if report['config']['author'] != author or report['config']['days'] != days:
            raise RuntimeError('作者或时间已变化，请重新读取文件清单')
    report = scoped_report(report, directories, revisions)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'report.json').exists(): raise RuntimeError('请使用新的合入备份目录')
    core.write_json(folder/'report.json', report)
    core.render(report, folder)
    instructions = folder/'差异报告.md'
    text = instructions.read_text().split('## 使用方式')[0]
    instructions.write_text(text + '## 使用方式\n\n选择文件后点击“合入”，在软件目录生成待合入副本。对比窗口左侧为 Release SVN 快照，右侧为待合入内容。先评估风险；低风险可在外层全选确认，高风险需打开对比逐个确认，确认后才写入本地 Release，最后手动提交 SVN。\n\n待合入、Release快照、本地原件分别保存在本批目录下，review.json 记录确认进度。\n')
    core.write_json(folder/'review.json', {'mode': 'review-v1', 'items': {}, 'reportHash': files.report_hash(report)})
    return report


def scope_check(core, folder, author, days, directories=None, preview=None, revisions=None):
    """Check only the selected scope in a disposable report, without staging or WC writes."""
    if not revisions:
        raise RuntimeError('请选择至少一条 SVN 提交记录')
    catalog(core, folder, author, days, directories, preview, revisions)
    return remaining_diff(core, folder)


def safe_path(root, path):
    relative = pathlib.PurePosixPath(path)
    target = pathlib.Path(root)/path
    if not path or relative.is_absolute() or '..' in relative.parts or target.resolve() != pathlib.Path(root).resolve()/path:
        raise RuntimeError('文件路径越界或包含符号链接')
    return target


def remote(core, config, path, revision):
    url = core.urlpath(config['release'], path)
    result = core.run('info', '--xml', '-r', revision, '--', url+'@'+str(revision), check=False)
    if result.returncode:
        diagnostic = result.stderr.decode('utf-8', 'replace')
        if any(code in diagnostic for code in ('E160013', 'W160013', 'W170000')): return None, {}
        raise RuntimeError(diagnostic)
    entry = ET.fromstring(result.stdout).find('entry')
    if entry is None or entry.get('kind') != 'file': raise RuntimeError('Release 对照项不是普通文件：'+path)
    props = files.properties(core, url, revision)
    if 'svn:special' in props: raise RuntimeError('符号链接需单独核对：'+path)
    return core.run('cat', '-r', revision, '--', url+'@'+str(revision)).stdout, props


def encoded(props): return {key: base64.b64encode(value).decode() for key, value in props.items()}
def decoded(props): return {key: base64.b64decode(value) for key, value in props.items()}


def local_state(core, config, path):
    target = safe_path(config['target'], path)
    if target.exists() and not target.is_file(): raise RuntimeError('本地目标不是普通文件：'+path)
    data = target.read_bytes() if target.exists() else None
    result = core.run('status', '--xml', '--verbose', '--depth', 'empty', '--', str(target)+'@')
    status = ET.fromstring(result.stdout).find('.//wc-status')
    item = status.get('item') if status is not None else 'none'
    props = files.properties(core, str(target)) if item in ('normal','modified','added','replaced') and target.exists() else {}
    return {'hash': files.data_hash(data), 'properties': encoded(props), 'status': dict(status.attrib) if status is not None else {}, 'item': item}


def stage(core, folder, report, state, path):
    from revision_cache import reads
    with reads(core,folder.parent/'历史缓存',report['config'].get('uuid')):
        return _stage(core,folder,report,state,path)


def archive_candidate(core, folder, state, path):
    """Keep the previous reviewed bytes before replacing a candidate in this round."""
    entry = state['items'].get(path)
    if entry is None:
        return
    destination = folder/'副本历史'/uuid.uuid4().hex
    destination.mkdir(parents=True)
    archived = dict(entry)
    for key in ('candidate', 'baseline'):
        if entry.get(key):
            source = pathlib.Path(entry[key])
            if not source.is_file():
                raise RuntimeError('旧副本缺失，请检查备份后再生成')
            output = destination/(key + source.suffix)
            shutil.copy2(source, output)
            archived[key] = str(output)
    core.write_json(destination/'record.json', archived)
    del state['items'][path]
    core.write_json(folder/'review.json', state)


def backup_before_write(core, folder, path, original, local):
    """An immutable, independently addressable record for every attempted write."""
    identity = uuid.uuid4().hex
    destination = folder/'写入备份'/identity
    destination.mkdir(parents=True)
    before = destination/('原件' + pathlib.Path(path).suffix)
    if original is not None:
        with before.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    record = dict(id=identity, path=path, created=dt.datetime.now(dt.timezone.utc).isoformat(),
                  existed=original is not None, before=str(before) if original is not None else None,
                  local=local, status='prepared')
    core.write_json(destination/'record.json', record)
    return destination, record

def _stage(core, folder, report, state, path):
    # Pin both branches at generation time, not at the earlier list scan.
    report = dict(report, config=dict(report['config']))
    config = report['config']
    config['snapshot'] = core.info(config['release'], 'HEAD')['revision']
    if path in state['items']: raise RuntimeError('此文件已有待确认版本，请先核对该版本')
    if pathlib.PurePosixPath(path).name.lower() == 'pmdata.bin': raise RuntimeError('pmdata 请在 Release 使用 xtools 导出')
    item = next((item for item in report['fileItems'] if item['path'] == path), None)
    if item is None: raise RuntimeError('所选文件已不在作者改动列表中')
    before, props = remote(core, config, path, config['snapshot'])
    # Resolve the selected author's changed positions in the candidate only.
    # The human reviews the resulting differences before any working-copy write.
    plan = files.build_plan(core, report, item, resolve_author=True, baseline=(before, props))
    local = local_state(core, config, path)
    plan['data'], plan['properties'], includes_local = include_local_changes(
        core, config, path, local, plan['data'], plan['properties'])
    if includes_local:
        guarded_before, guarded_props, _ = include_local_changes(core, config, path, local, before, props)
        dev, dev_props = files.source_snapshot(core, core.urlpath(config['dev'], path), config['snapshot'])
        deletion_guard.check(guarded_before, plan['data'], dev, path, getattr(core, 'sync_phase', None))
        deletion_guard.check_properties(guarded_props, plan['properties'], dev_props, path)
    plan['same'] = files.same_data(before, plan['data'], path) and props == plan['properties']
    from workbook_native import finalize
    plan['data'], native = finalize(before, plan['data'], path, getattr(core, 'sync_phase', None))
    destination = safe_path(folder/'待合入', path)
    original = safe_path(folder/'Release快照', path)
    for output, data in ((destination, plan['data']), (original, before)):
        output.parent.mkdir(parents=True, exist_ok=True)
        if data is not None: output.write_bytes(data)
    if local_state(core, config, path) != local:
        raise RuntimeError('生成期间本地文件发生变化，请重新生成')
    entry = {'path': path, 'status': 'ready', 'revision': config['snapshot'],
             'authorIsolation': AUTHOR_ISOLATION_VERSION, 'nativeWrite': native,
             'deletionGuard': plan['deletionGuard'], 'deletionGuardVersion': deletion_guard.VERSION,
             'sourceHash': plan['sourceHash'], 'sourceProperties': plan['sourceProperties'],
             'deletionHistory': plan.get('deletionHistory'),
             'candidate': str(destination) if plan['data'] is not None else None,
             'baseline': str(original) if before is not None else None,
             'candidateHash': files.data_hash(plan['data']), 'baselineHash': files.data_hash(before),
             'properties': encoded(plan['properties']), 'beforeProperties': encoded(props),
             'local': local, 'includesLocalChanges': includes_local, 'same': plan['same'], 'revisions': plan['revisions'],
             'summary': files.describe(plan) + '\n合入规则：只覆盖所选作者改过的位置，各位置以该作者最后一次修改为准；其他位置保留 Release。'}
    if config.get('scopeRevisions') is not None:
        entry['summary'] = files.describe(plan) + '\n合入规则：按所选 SVN 提交单号逐次重放，仅修改所选记录涉及的位置；未选提交不带入。'
    if includes_local:
        entry['summary'] += '\n已自动拆分并保留本地修改；本次对比包含完整写入结果，确认后自动备份、更新此文件并写入。'
    if galaxy_sync.supports(path):
        entry['galaxyMergeVersion'] = galaxy_sync.RULE_VERSION
        entry['summary'] += '\n星系对象按 ID 对齐，逐字段重放作者改动；Release 独有对象及未改字段保留。'
    if path.lower().endswith(('.xlsx','.xlsm')):
        entry['summary'] += '\n整行删除：基于生成时的 Release 最新快照，仅删除本次合入清空的数据行；Excel 原生上移并保存后再核对，保留原有空白布局。'
        entry['summary'] += '\n公式转值：先使用 Release 自身已保存的计算结果转值，再合并实际数值修改；整页转值同步处理对应工作表。缺失 ID 仅有转值时无需补入，包含实际数值修改时仍需核对。'
    if plan['properties'] != props:
        entry['summary'] += '\nSVN 属性变化：\n' + '\n'.join(
            key + '：' + repr(props.get(key)) + ' → ' + repr(plan['properties'].get(key))
            for key in sorted(set(props)|set(plan['properties'])) if props.get(key) != plan['properties'].get(key))
    assess_risk(core, folder, report, entry)
    state['items'][path] = entry
    core.write_json(folder/'review.json', state)
    return entry


def assess_risk(core, folder, report, entry):
    """Fail closed; eligibility is bound to the exact reviewed bytes and properties."""
    import difflib
    before = reviewed_bytes(folder, entry, 'baseline', 'Release快照')
    after = reviewed_bytes(folder, entry, 'candidate', '待合入')
    reasons = []
    if entry.get('includesLocalChanges'):
        reasons.append('已保留本地修改，请确认完整写入结果')
    if entry['properties'] != entry['beforeProperties']:
        reasons.append('SVN 属性发生变化')
    if before != after:
        if before is None or after is None:
            reasons.append('新增或删除整个文件，需要核对依赖')
        elif entry['path'].lower().endswith(('.xlsx', '.xlsm', '.xls')):
            reasons.append('表格变化需要打开核对单元格、公式及结构')
        elif pathlib.PurePosixPath(entry['path']).suffix.lower() not in ('.txt','.lua','.cs','.json','.xml','.yaml','.yml','.md','.csv','.shader','.meta','.asset','.prefab','.unity','.mat','.controller','.anim','.compute','.cginc','.overridecontroller'):
            reasons.append('此文件类型需要人工确认')
        elif max(len(before), len(after)) > 2_000_000:
            reasons.append('文件较大，需要打开核对')
        else:
            try:
                if b'\x00' in before or b'\x00' in after: raise ValueError()
                old, new = before.decode('utf-8').splitlines(), after.decode('utf-8').splitlines()
                changed = sum(max(j-i, b-a) for tag,i,j,a,b in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes() if tag != 'equal')
                if changed > 80 or changed / max(len(old),len(new),1) > .3:
                    reasons.append('改动范围较大（超过 80 行或 30%）')
                if not reasons:
                    item = next(v for v in report['fileItems'] if v['path'] == entry['path'])
                    from revision_cache import reads
                    with reads(core, folder.parent/'历史缓存', report['config'].get('uuid')):
                        strict = files.build_plan(core, report, item, resolve_author=False,
                                                  baseline=(before, decoded(entry['beforeProperties'])))
                    if strict['data'] != after or encoded(strict['properties']) != entry['properties']:
                        reasons.append('作者覆盖结果与无冲突合并结果不同')
            except (UnicodeError, ValueError):
                reasons.append('非可核对的 UTF-8 文本，需要人工确认')
            except Exception as error:
                reasons.append('无冲突核验未通过：' + str(error))
    risk = dict(version=1, level='high' if reasons else 'low',
                reasons=reasons or ['内容及属性相同' if before == after else '小范围文本改动，无冲突合并结果一致'],
                candidateHash=entry['candidateHash'], baselineHash=entry['baselineHash'],
                properties=entry['properties'], beforeProperties=entry['beforeProperties'])
    entry['risk'] = risk
    return risk


def validate_low_risk(entry):
    risk = entry.get('risk') or {}
    if risk.get('version') != 1 or risk.get('level') != 'low' or any(
            risk.get(key) != entry[key] for key in ('candidateHash','baselineHash','properties','beforeProperties')):
        raise RuntimeError('此文件未通过当前副本的低风险评估，请打开对比逐个确认')


def reviewed_bytes(folder, entry, key, directory):
    if entry[key] is None:
        if entry[key+'Hash'] is not None: raise RuntimeError('待确认文件记录无效')
        return None
    expected = safe_path(folder/directory, entry['path'])
    if str(expected) != entry[key]: raise RuntimeError('待确认文件路径已改变')
    data = expected.read_bytes()
    if files.data_hash(data) != entry[key+'Hash']: raise RuntimeError('对比副本已被修改，请重新合入并确认')
    return data


def remaining_remote_revisions(core, folder, config, items, *, scoped=False):
    """Reuse pinned reads only after SVN proves the branch paths unchanged."""
    from urllib.parse import unquote
    import subprocess
    identity = [config.get('uuid'), config['dev'], config['release']]
    cache_file = folder.parent/'remaining-snapshots.json'
    try: previous = json.loads(cache_file.read_text())
    except (OSError, ValueError): previous = {}
    snapshot = config['snapshot']
    old = previous.get('snapshot')
    valid = (previous.get('identity') == identity and type(old) is int and old <= snapshot
             and (not scoped or old == snapshot))
    revisions = {}
    for branch in ('dev', 'release'):
        url = config[branch]
        changed = None
        if valid:
            if old == snapshot:
                changed = []
            else:
                if getattr(core, 'sync_phase', None): core.sync_phase('读取 '+branch+' 新版本变更范围')
                try:
                    result = core.run('diff', '--summarize', '--xml', '-r', f'{old}:{snapshot}',
                                      '--', url+'@'+str(snapshot), check=False)
                    if result.returncode == 0:
                        # Unknown paths invalidate reuse rather than assuming nothing changed.
                        changed = []
                        prefix = unquote(url).rstrip('/')+'/'
                        for node in ET.fromstring(result.stdout).findall('./paths/path'):
                            # We read explicit file properties, not inherited directory properties.
                            # Mergeinfo changes on ancestor directories do not change file inputs.
                            if node.get('kind') == 'dir' and node.get('item') in ('none', 'normal'): continue
                            path = unquote(node.text or '')
                            if path == prefix[:-1]: changed = None; break
                            if not path.startswith(prefix): changed = None; break
                            changed.append(path[len(prefix):].strip('/'))
                except (OSError, RuntimeError, ET.ParseError, subprocess.TimeoutExpired):
                    changed = None
        saved = previous.get('revisions', {}).get(branch, {}) if valid else {}
        revisions[branch] = {}
        for item in items:
            path = item['path']
            revision = saved.get(path)
            unchanged = changed is not None and not any(path == c or path.startswith(c+'/') for c in changed)
            revisions[branch][path] = revision if unchanged and type(revision) is int and 0 < revision <= snapshot else snapshot
    return revisions, cache_file, dict(identity=identity, snapshot=snapshot, revisions=revisions)


def remaining_local_reader(core, config, items):
    """Batch only this read-only scan's local queries; never persist WC evidence."""
    import subprocess
    responses = {}
    targets = [str(safe_path(config['target'], item['path'])) for item in items]
    status_args = ('status', '--xml', '--verbose', '--depth', 'empty', '--')
    props_args = ('proplist', '--xml', '--verbose', '--')
    for offset in range(0, len(targets), 64):
        chunk = targets[offset:offset+64]
        result = core.run(*status_args, *(path+'@' for path in chunk), check=False)
        # On any batch error, retain the existing per-file diagnostics.
        if result.returncode: continue
        tree = ET.fromstring(result.stdout)
        entries = {e.get('path'): e for e in tree.findall('.//entry')}
        property_targets = []
        for path in chunk:
            entry = entries.get(path)
            root = ET.Element('status')
            if entry is not None: ET.SubElement(root, 'target', path=path).append(entry)
            responses[status_args+(path+'@',)] = ET.tostring(root)
            state = entry.find('wc-status') if entry is not None else None
            if state is not None and state.get('item') in ('normal','modified','added','replaced') and pathlib.Path(path).is_file():
                property_targets.append(path)
        if not property_targets: continue
        result = core.run(*props_args, *(path+'@' for path in property_targets), check=False)
        if result.returncode: continue
        properties = {e.get('path'): e for e in ET.fromstring(result.stdout).findall('target')}
        for path in property_targets:
            root = ET.Element('properties')
            if path in properties: root.append(properties[path])
            responses[props_args+(path+'@',)] = ET.tostring(root)
    def run(*args, **kwargs):
        key = tuple(map(str, args))
        if key in responses:
            return subprocess.CompletedProcess(args, 0, responses[key], b'')
        return core.run(*args, **kwargs)
    return run


def remaining_diff(core, folder, paths=None):
    """Recompute authored changes against current Release; never alter review artifacts or the WC."""
    import concurrent.futures
    import copy
    import threading
    import types
    from revision_cache import reads
    folder = pathlib.Path(folder)
    with (folder/'operation.lock').open('a') as lock:
        try: try_lock(lock)
        except BlockingIOError: raise RuntimeError('合入任务正在运行，请稍后核验')
        report = json.loads((folder/'report.json').read_text())
        ledger = json.loads((folder/'review.json').read_text())
        if ledger.get('pending'): raise RuntimeError('存在未完成写入，请先检查现场')
        if ledger.get('reportHash') != files.report_hash(report): raise RuntimeError('报告已变化，请刷新后核验')
        items = [item for item in report['fileItems'] if pathlib.PurePosixPath(item['path']).name.lower() != 'pmdata.bin']
        if paths is not None:
            requested = set(paths)
            if not requested: raise RuntimeError('请选择需要核验的文件')
            if not requested.issubset({item['path'] for item in items}):
                raise RuntimeError('核验文件不在当前报告中，请刷新文件列表')
            items = [item for item in items if item['path'] in requested]
        current = copy.deepcopy(report)
        current['config']['snapshot'] = core.info(report['config']['release'], 'HEAD')['revision']
        config = current['config']
        result = dict(snapshot=config['snapshot'], noDiffPaths=[], differentPaths=[], errors={}, localIssues={}, localStates={}, localEvidence={},
                      reportDigest=hashlib.sha256((folder/'report.json').read_bytes()).hexdigest(), complete=False)
        saved_file = folder/'remaining-last.json'
        try: saved_result = json.loads(saved_file.read_text())
        except (OSError, ValueError): saved_result = {}
        if saved_result.get('reportDigest') != result['reportDigest']:
            saved_result = copy.deepcopy(result)
        # Hash only the shared merge engine, so source and installed app reuse identical evidence.
        modules = sorted(p for p in pathlib.Path(__file__).parent.glob('*.py')
                         if p.stem.startswith('workbook') or p.stem in ('file_sync', 'galaxy_sync', 'lua_sync', 'deletion_guard'))
        rule_hash = hashlib.sha256(b'remaining-v2' + files.compiled_engine_hash() + b''.join(p.read_bytes() for p in modules)).hexdigest()
        cache_file = folder.parent/'remaining-diff-cache.json'
        try: cache = json.loads(cache_file.read_text())
        except (OSError, ValueError): cache = {}
        cache_lock = threading.Lock()
        file_progress = getattr(core, 'sync_files', lambda completed, total: None)
        file_progress(0, len(items))
        if getattr(core, 'sync_phase', None): core.sync_phase('批量检查 Release 本地状态')
        local_reader = remaining_local_reader(core, config, items)
        revisions, snapshots_file, snapshots = remaining_remote_revisions(core, folder, config, items, scoped=paths is not None)
        def check(item):
            path = item['path']
            worker = types.SimpleNamespace(**vars(core))
            worker.source_analysis=files.SourceAnalysisCache()
            failed_read = [False]
            def tracked_read(*args, **kwargs):
                try:
                    reply=local_reader(*args, **kwargs)
                    if getattr(reply,'returncode',0):failed_read[0]=True
                    return reply
                except Exception:
                    failed_read[0]=True
                    raise
            worker.run = tracked_read
            local_issue = ''
            local = None
            local_result = 'error'
            if getattr(core, 'sync_item', None): core.sync_item(path)
            try:
                # Each reader has its own wrapper; no cross-thread mutation of core.run.
                with reads(worker, folder.parent/'历史缓存', config.get('uuid')):
                    if getattr(worker, 'sync_phase', None): worker.sync_phase('核验当前 Release 剩余差异 · ' + path)
                    before, props = remote(worker, config, path, revisions['release'][path])
                    local_issue = ''
                    try:
                        local = local_state(worker, config, path)
                        normal = (local['item'] in ('normal', 'none')
                                  and local['status'].get('props') in (None, 'none', 'normal')
                                  and local['status'].get('tree-conflicted') != 'true')
                        if not normal:
                            local_issue = 'Release 有本地修改或异常状态，请先核对本地差异。'
                        elif local['hash'] != files.data_hash(before) or local['properties'] != encoded(props):
                            local_issue = 'Release 工作副本与当前仓库版本不同，请先更新或核对版本。'
                    except Exception as error:
                        local_issue = '本地状态无法确认：' + str(error)
                    source, source_props = files.source_snapshot(worker, worker.urlpath(config['dev'], path), revisions['dev'][path])
                    identity = [rule_hash, config.get('uuid'), config['dev'], config['release'], config['author'], path,
                                item['revisions'], config.get('scopeRevisions'), files.data_hash(before), encoded(props), files.data_hash(source), encoded(source_props)]
                    # A restore followed by another deletion can leave identical
                    # bytes while changing the deletion's authorship history.
                    if path.lower().endswith(('.xlsx','.xlsm')):
                        from workbook_history import history_entries, digest
                        identity.append(digest(history_entries(worker,config,path,min(item['revisions'])-1,config['snapshot'])))
                    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                    with cache_lock: same = cache.get(key)
                    if isinstance(same, dict) and isinstance(same.get('error'), str):
                        raise RuntimeError(same['error'])
                    if type(same) is not bool:
                        # Exact source/target equality proves there can be no remaining authored delta.
                        try:
                            same = (config.get('scopeRevisions') is None and source == before and source_props == props) or files.build_plan(
                                worker, current, item, resolve_author=True, baseline=(before, props))['same']
                        except (RuntimeError, ValueError) as error:
                            message = str(error)
                            # These errors come from immutable merge inputs, not network/local state.
                            if not failed_read[0] and ('：无法安全提取作者改动范围内的 Dev 最新值：' in message or message.startswith('删除保护：')):
                                with cache_lock:
                                    cache[key] = {'error': message}
                                    core.write_json(cache_file, dict(list(cache.items())[-2000:]))
                            raise
                        with cache_lock:
                            cache[key] = same
                            core.write_json(cache_file, dict(list(cache.items())[-2000:]))
                    if local is not None:
                        safe_status = (local['item'] in ('normal', 'modified', 'added', 'deleted', 'none')
                                       and local['status'].get('props') in (None, 'none', 'normal', 'modified')
                                       and local['status'].get('tree-conflicted') != 'true'
                                       and local['status'].get('switched') != 'true'
                                       and 'svn:special' not in local['properties'])
                        if safe_status:
                            try:
                                target = safe_path(config['target'], path)
                                data = target.read_bytes() if target.exists() else None
                                if files.data_hash(data) != local['hash']:
                                    raise RuntimeError('核验期间本地文件发生变化，请重新核验。')
                                identity_path = target if local['item'] in ('normal', 'modified', 'added') else target.parent
                                metadata = core.info(str(identity_path))
                                relative = identity_path.relative_to(pathlib.Path(config['target'])).as_posix()
                                expected = config['release'] if relative == '.' else core.urlpath(config['release'], relative)
                                if metadata['uuid'] != config['uuid'] or not core.same_repository_url(metadata['url'], expected):
                                    raise RuntimeError('Release 本地文件指向其他仓库位置。')
                                local_props = decoded(local['properties'])
                                if data == before and local_props == props:
                                    local_same = same
                                else:
                                    # Register equality for this exact authored revision scope
                                    # and local content. SVN status, identity and deletion
                                    # history are still checked before reusing the result.
                                    local_key = hashlib.sha256(json.dumps(
                                        ['local-equality-v1', identity, str(target), local['hash'],
                                         local['properties']], sort_keys=True).encode()).hexdigest()
                                    with cache_lock: registered = cache.get(local_key)
                                    local_same = (registered is True
                                                  or (config.get('scopeRevisions') is None and data == source and local_props == source_props)
                                                  or files.build_plan(worker, current, item, resolve_author=True,
                                                                      baseline=(data, local_props))['same'])
                                    if local_same and registered is not True:
                                        if local_state(worker, config, path) != local:
                                            raise RuntimeError('核验期间本地文件发生变化，请重新核验。')
                                        with cache_lock:
                                            cache[local_key] = True
                                            core.write_json(cache_file, dict(list(cache.items())[-2000:]))
                                local_result = 'same' if local_same else 'different'
                                if local_same:
                                    local_issue = ''
                                elif local_issue:
                                    # Prove that preparation can preserve the WC delta;
                                    # a warning must not block a supported split write.
                                    plan = files.build_plan(worker, current, item, resolve_author=True,
                                                            baseline=(before, props))
                                    include_local_changes(worker, config, path, local,
                                                          plan['data'], plan['properties'])
                                    local_issue = ''
                            except Exception as error:
                                local_result = 'error'
                                local_issue = (local_issue + ' 本地内容核验未完成：' + str(error)).strip()
                        else:
                            local_result = 'blocked'
                        if local_state(core, config, path) != local:
                            raise RuntimeError('核验期间本地文件发生变化，请重新核验。')
                    return path, 'same' if same else 'different', '', local_issue, local_result, local
            except Exception as error:
                return path, 'error', '当前 Release 剩余差异核验未完成：' + str(error), local_issue, 'error', local
            finally:
                worker.source_analysis.clear()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(check, item) for item in items]
            for index, future in enumerate(concurrent.futures.as_completed(futures)):
                path, status, error, local_issue, local_result, local = future.result()
                result['localStates'][path] = local_result
                result['localEvidence'][path] = local
                file_progress(index+1, len(items))
                if status == 'same': result['noDiffPaths'].append(path)
                elif status == 'different': result['differentPaths'].append(path)
                else: result['errors'][path] = error
                if local_issue: result['localIssues'][path] = local_issue
                # Publish completed files immediately; one large workbook must not hold the list.
                for name in ('noDiffPaths', 'differentPaths'):
                    saved_result[name] = [p for p in saved_result[name] if p != path]
                saved_result.setdefault('localStates', {})[path] = local_result
                saved_result.setdefault('localEvidence', {})[path] = local
                saved_result['errors'].pop(path, None)
                saved_result.setdefault('localIssues', {}).pop(path, None)
                if status == 'same': saved_result['noDiffPaths'].append(path)
                elif status == 'different': saved_result['differentPaths'].append(path)
                else: saved_result['errors'][path] = error
                if local_issue: saved_result['localIssues'][path] = local_issue
                saved_result.update(snapshot=result['snapshot'], complete=False)
                core.write_json(saved_file, saved_result)
                core.write_json(folder/'remaining-diff.json', result)
                if getattr(core, 'sync_remaining', None): core.sync_remaining(result)
                if getattr(core, 'sync_phase', None): core.sync_phase(f'已核验 {index+1}/{len(items)} · {path}')
        result['noDiffPaths'].sort(); result['differentPaths'].sort()
        result['complete'] = True
        # A subset cannot replace branch-wide revision evidence for other files.
        if paths is None: core.write_json(snapshots_file, snapshots)
        core.write_json(folder/'remaining-diff.json', result)
        if paths is None:
            core.write_json(saved_file, result)
        else:
            all_paths = {item['path'] for item in report['fileItems'] if pathlib.PurePosixPath(item['path']).name.lower() != 'pmdata.bin'}
            covered = set(saved_result['noDiffPaths'] + saved_result['differentPaths']) | set(saved_result['errors'])
            saved_result['complete'] = all_paths.issubset(covered)
            core.write_json(saved_file, saved_result)
        return result


def repair_review(core, folder):
    """Materialize inherited ready entries before the UI opens their files.

    Old batches remain immutable. Never weaken reviewed_bytes' path/hash checks.
    This operation is entirely local and cannot write to a working copy.
    """
    folder = pathlib.Path(folder)
    if not (folder/'review.json').exists(): return []
    with (folder/'operation.lock').open('a') as lock:
        try: try_lock(lock)
        except BlockingIOError: raise RuntimeError('合入任务正在运行，请稍后重新打开')
        report = json.loads((folder/'report.json').read_text())
        state = json.loads((folder/'review.json').read_text())
        if state.get('mode') != 'review-v1' or state.get('reportHash') != files.report_hash(report):
            raise RuntimeError('合入报告已变化，请保留备份并重新合入')
        if state.get('pending'): return []  # Preserve interrupted-write evidence.
        failure_file = folder/'review-failures.json'
        failures = json.loads(failure_file.read_text()) if failure_file.exists() else {}
        repaired = []
        for path, entry in state['items'].items():
            # Only accepted records (including those invalidated by this check) can
            # recover. Ready/skipped records must still go through human confirmation.
            if entry.get('status') in ('accepted', 'invalidated'):
                try:
                    target = safe_path(report['config']['target'], path)
                    current_hash = files.data_hash(target.read_bytes() if target.exists() else None)
                    local = (local_state(core, report['config'], path)
                             if current_hash == entry['candidateHash'] else None)
                    if local is None or local['hash'] != entry['candidateHash']:
                        reason = 'Release 本地内容与原确认结果不同；内容恢复一致后将自动重新核验，也可重新生成副本并核对。'
                    elif (local['status'].get('tree-conflicted') == 'true'
                          or local['item'] == 'conflicted' or local['status'].get('props') == 'conflicted'):
                        reason = 'Release 存在 SVN 冲突，请解决冲突后重新核验。'
                    elif local['properties'] != entry['properties']:
                        reason = 'Release 本地属性与原确认结果不同，请核对属性；恢复一致后将自动重新核验。'
                    elif local['item'] not in (('deleted', 'none') if entry['candidateHash'] is None
                                              else ('normal', 'modified', 'added')):
                        reason = 'Release 当前 SVN 状态为 ' + local['item'] + '，不符合原确认结果，请处理后重新核验。'
                    else:
                        reason = None
                except (OSError, ValueError, KeyError, RuntimeError) as error:
                    reason = '无法核验 Release 当前合入结果：' + str(error)
                previous = (entry.get('status'), entry.get('preparationIssue'))
                if reason is None:
                    entry['status'] = 'accepted'
                    entry.pop('preparationIssue', None)
                    failures.pop(path, None)
                else:
                    entry['status'] = 'invalidated'
                    entry['preparationIssue'] = reason
                    failures[path] = reason
                if previous != (entry.get('status'), entry.get('preparationIssue')):
                    repaired.append(path)
                continue
            if entry.get('status') != 'ready': continue
            if failures.get(path, '').splitlines()[-1:] == ['本地文件在生成对比后已变化，请保留修改并重新合入']:
                try:
                    local = local_state(core, report['config'], path)
                    if local != entry.get('local') and same_reviewed_local(local, entry.get('local', {})):
                        failures.pop(path)
                        repaired.append(path)
                except (OSError, ValueError, KeyError, RuntimeError):
                    pass  # Unproven failures remain blocked; confirmation rechecks live history.
            pairs = [('candidate', '待合入'), ('baseline', 'Release快照')]
            if all(entry.get(key) is None or entry[key] == str(folder/directory/path) for key,directory in pairs):
                continue
            try:
                updated = materialize_review(folder, report, entry)
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                failures[path] = '待确认副本恢复失败：' + str(error)
                continue
            state['items'][path] = updated
            repaired.append(path)
            reason = failures.get(path, '')
            if '待确认文件路径已改变' in reason or reason.startswith('待确认副本恢复失败：'):
                failures.pop(path, None)
        # Saved results are display caches, never durable working-copy evidence.
        remaining_file = folder/'remaining-last.json'
        if remaining_file.exists():
            remaining = json.loads(remaining_file.read_text())
            covered = set(remaining.get('noDiffPaths', []) + remaining.get('differentPaths', [])) | set(remaining.get('errors', {}))
            stale = set()
            for path in covered:
                try:
                    evidence = remaining.get('localEvidence', {}).get(path)
                    if evidence is None or local_state(core, report['config'], path) != evidence:
                        stale.add(path)
                except (OSError, ValueError, RuntimeError):
                    stale.add(path)
            if stale:
                for key in ('noDiffPaths', 'differentPaths'):
                    remaining[key] = [p for p in remaining.get(key, []) if p not in stale]
                for key in ('errors', 'localIssues', 'localStates', 'localEvidence'):
                    remaining[key] = {p:v for p,v in remaining.get(key, {}).items() if p not in stale}
                remaining['complete'] = False
                core.write_json(remaining_file, remaining)
        if repaired: core.write_json(folder/'review.json', state)
        if failures or failure_file.exists(): core.write_json(failure_file, failures)
        return repaired


def materialize_review(folder, report, entry):
    import copy
    path = entry['path']
    pairs = [('candidate', '待合入'), ('baseline', 'Release快照')]
    roots = set()
    for key, directory in pairs:
        value = entry.get(key)
        if value is None:
            if entry[key+'Hash'] is not None: raise RuntimeError('待确认文件记录无效')
            continue
        source = pathlib.Path(value)
        root = source
        for _ in pathlib.PurePosixPath(path).parts: root = root.parent
        if root.name != directory: raise RuntimeError('待确认文件路径已改变')
        roots.add(root.parent)
        if safe_path(root, path) != source: raise RuntimeError('待确认文件路径已改变')
    if len(roots) != 1: raise RuntimeError('待合入副本与快照不属于同一批次')
    origin = roots.pop()
    if origin.resolve() == folder.resolve(): raise RuntimeError('待确认文件路径已改变')
    with (origin/'operation.lock').open('a') as lock:
        try: try_lock(lock)
        except BlockingIOError: raise RuntimeError('原批次正在操作，请稍后再试')
        old_report = json.loads((origin/'report.json').read_text())
        old_state = json.loads((origin/'review.json').read_text())
        if old_state.get('pending') or old_state.get('reportHash') != files.report_hash(old_report):
            raise RuntimeError('原批次未完成写入或报告已改变')
        if any(old_report['config'].get(k) != report['config'].get(k)
               for k in ('uuid','dev','release','target','author','days','scopeRevisions')):
            raise RuntimeError('原批次与当前分支或作者范围不一致')
        old_entry = old_state['items'].get(path)
        if old_entry != entry: raise RuntimeError('原批次确认记录已改变，请重新生成并核对')
        revisions = {v['path']: v['revisions'] for v in report['fileItems']}
        old_revisions = {v['path']: v['revisions'] for v in old_report['fileItems']}
        if path not in revisions or revisions[path] != old_revisions.get(path):
            raise RuntimeError('作者文件版本已改变，请重新生成并核对')
        outputs = []
        updated = copy.deepcopy(entry)
        for key, directory in pairs:
            data = reviewed_bytes(origin, entry, key, directory)
            if data is not None:
                destination = safe_path(folder/directory, path)
                outputs.append((destination, data))
                updated[key] = str(destination)
        # Preserve restoration data for both current and legacy row withdrawals.
        backup_name = hashlib.sha256(path.encode()).hexdigest()
        backups = safe_path(origin/'撤回前副本', backup_name)
        if backups.exists():
            for source in backups.glob('*.xlsx'):
                if not re.fullmatch(r'[0-9a-f]{64}\.xlsx', source.name): raise RuntimeError('复原备份记录无效')
                source = safe_path(origin/'撤回前副本', backup_name+'/'+source.name)
                data = source.read_bytes()
                if files.data_hash(data) != source.stem: raise RuntimeError('复原备份已改变')
                outputs.append((safe_path(folder/'撤回前副本', backup_name+'/'+source.name), data))
        for row in entry.get('withdrawnRows', []):
            digest = row.get('backupHash')
            if digest and not any(p.name == digest+'.xlsx' for p,_ in outputs):
                raise RuntimeError('找不到撤回前副本')
        field = safe_path(origin/'字段选择前副本', path)
        if field.parent.exists():
            for source in field.parent.iterdir():
                if not source.name.startswith(field.name+'.'): continue
                digest = source.name[len(field.name)+1:]
                if not re.fullmatch(r'[0-9a-f]{64}', digest): continue
                source = safe_path(origin/'字段选择前副本', path+'.'+digest)
                data = source.read_bytes()
                if files.data_hash(data) != digest: raise RuntimeError('字段选择备份已改变')
                outputs.append((safe_path(folder/'字段选择前副本', path+'.'+digest), data))
        # Validate every input and existing output before publishing any new path.
        for destination, data in outputs:
            if destination.exists() and destination.read_bytes() != data:
                raise RuntimeError('当前批次已有不同副本，请保留现场并重新核对')
        for destination, data in outputs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                    handle.write(data); temporary = pathlib.Path(handle.name)
                try: temporary.replace(destination)
                finally: temporary.unlink(missing_ok=True)
        return updated


def local_matches_candidate(local, entry):
    return (entry.get('candidateHash') is not None
            and local['item'] in ('normal', 'modified')
            and local['status'].get('props') in (None, 'none', 'normal', 'modified')
            and local['status'].get('tree-conflicted') != 'true'
            and local['hash'] == entry['candidateHash']
            and local['properties'] == entry['properties'])


def same_reviewed_local(current, reviewed):
    if current == reviewed:
        return True
    # SVN update can advance an unchanged file's working revision. All content,
    # properties and status flags must still match; never relax the in-write check.
    if current.get('item') != 'normal' or reviewed.get('item') != 'normal':
        return False
    old_status, new_status = dict(reviewed.get('status', {})), dict(current.get('status', {}))
    old_revision, new_revision = old_status.pop('revision', ''), new_status.pop('revision', '')
    if not str(old_revision).isdigit() or not str(new_revision).isdigit() or int(new_revision) < int(old_revision):
        return False
    return dict(current, status=new_status) == dict(reviewed, status=old_status)


def accept(core, folder, report, state, path):
    config = report['config']
    entry = state['items'].get(path)
    if entry is None or entry['status'] != 'ready': raise RuntimeError('文件未等待确认，不能重复写入')
    if entry.get('authorIsolation') != AUTHOR_ISOLATION_VERSION:
        raise RuntimeError('此副本使用旧版作者隔离规则，请重新点击合入生成并核对；未写入 Release')
    if galaxy_sync.supports(path) and entry.get('galaxyMergeVersion') != galaxy_sync.RULE_VERSION:
        raise RuntimeError('星系对象合并规则已更新，请重新生成并核对；旧副本已保留')
    if entry.get('deletionGuardVersion') != deletion_guard.VERSION or 'sourceHash' not in entry or 'sourceProperties' not in entry:
        raise RuntimeError('删除保护规则已更新，请重新生成并核对；旧副本已保留，未写入 Release')
    candidate = reviewed_bytes(folder, entry, 'candidate', '待合入')
    baseline = reviewed_bytes(folder, entry, 'baseline', 'Release快照')
    if entry.get('textReview'):
        import text_review
        text_review.verify_latest_choices(core,report,entry)
    target = safe_path(config['target'], path)
    if not target.parent.is_dir(): raise RuntimeError('Release 缺少父目录，请先核对目录依赖')
    parent = core.info(str(target.parent))
    relative = os.path.relpath(target.parent, config['target'])
    expected = config['release'] if relative == '.' else core.urlpath(config['release'], relative)
    if parent['uuid'] != config['uuid'] or not core.same_repository_url(parent['url'], expected):
        raise RuntimeError('Release 父目录指向其他仓库位置')
    local = local_state(core, config, path)
    if not same_reviewed_local(local, entry['local']): raise RuntimeError('本地文件在生成对比后已变化，请保留修改并重新合入')
    already_present = local_matches_candidate(local, entry)
    preserves_local = entry.get('includesLocalChanges') is True
    allowed_items = ('normal', 'modified', 'none') if preserves_local else ('normal', 'none')
    allowed_props = (None, 'none', 'normal', 'modified') if preserves_local else (None, 'none', 'normal')
    if not already_present and (local['item'] not in allowed_items or local['status'].get('props') not in allowed_props or local['status'].get('tree-conflicted') == 'true' or local['status'].get('switched') == 'true'):
        raise RuntimeError('此文件有本地修改或异常状态，请先保存处理；待合入副本已保留')
    if target.exists():
        metadata = core.info(str(target))
        if metadata['uuid'] != config['uuid'] or not core.same_repository_url(metadata['url'], core.urlpath(config['release'], path)):
            raise RuntimeError('Release 文件指向其他仓库位置')
    revision = core.info(config['release'], 'HEAD')['revision']
    live, live_props = remote(core, config, path, revision)
    if live != baseline or encoded(live_props) != entry['beforeProperties']:
        raise RuntimeError('Release 最新 SVN 内容已变化，请重新合入并核对新差异')
    if preserves_local:
        preserved, preserved_props, _ = include_local_changes(
            core, config, path, local, candidate, decoded(entry['properties']))
        if not files.same_data(preserved, candidate, path) or encoded(preserved_props) != entry['properties']:
            raise RuntimeError('确认内容未完整保留本地修改，请重新生成副本；未写入 Release')
    dev_live, dev_props = files.validate_source_snapshot(core, config, path, entry['sourceHash'], entry['sourceProperties'], revision)
    if path.lower().endswith(('.xlsx','.xlsm')):
        from workbook_history import validate
        validate(core,config,path,entry.get('deletionHistory'),revision)
    guard_baseline, guard_props = baseline, decoded(entry['beforeProperties'])
    if preserves_local:
        guard_baseline, guard_props, _ = include_local_changes(core, config, path, local, baseline, guard_props)
    deletion_guard.check(guard_baseline, candidate, dev_live, path, getattr(core, 'sync_phase', None))
    deletion_guard.check_properties(encoded(guard_props), entry['properties'], encoded(dev_props), path)
    if local_state(core, config, path) != local: raise RuntimeError('核对期间本地文件已变化，未写入')
    if already_present:
        entry['status'] = 'accepted'
        entry['acceptedExisting'] = True
        entry['summary'] += '\n已确认：Release 本地内容及属性与待合入结果一致，仅记录确认；未更新或覆盖文件，尚未提交 SVN。'
        core.write_json(folder/'review.json', state)
        return entry
    original = target.read_bytes() if target.exists() else None
    write_folder, write_record = backup_before_write(core, folder, path, original, local)
    backup = safe_path(folder/'本地原件', path)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if original is not None: backup.write_bytes(original)
    metadata = folder/'本地属性'/hashlib.sha256(path.encode()).hexdigest()
    metadata.parent.mkdir(parents=True, exist_ok=True)
    core.write_json(metadata.with_suffix('.json'), dict(local, path=path))
    if files.data_hash(original) != local['hash'] or local_state(core, config, path) != local:
        raise RuntimeError('备份期间本地文件已变化，未写入；请重新生成副本')
    state['pending'] = path
    core.write_json(folder/'review.json', state)
    if preserves_local:
        # The exact local delta is in the reviewed candidate and the durable
        # backup above. Clear only this file before update (binary SVN merging
        # cannot preserve independent workbook fields). Never recurse.
        core.run('revert', '--depth', 'empty', '--', str(target)+'@')
    # Update only the explicitly reviewed file, never the whole working copy.
    if target.exists() or baseline is not None:
        core.run('update', '--depth', 'empty', '--ignore-externals', '-r', revision, '--accept', 'postpone', '--', str(target)+'@', timeout=600)
    after_update = local_state(core, config, path)
    if after_update['item'] not in ('normal', 'none') or after_update['status'].get('tree-conflicted') == 'true' or after_update['hash'] != files.data_hash(baseline) or after_update['properties'] != entry['beforeProperties']:
        raise RuntimeError('文件更新后与已确认快照不符，请检查现场和备份；未自动重试')
    if candidate != baseline or entry['properties'] != entry['beforeProperties']:
        if candidate is None:
            if target.exists(): core.run('delete', '--', str(target)+'@')
        else:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.svnflow-', delete=False) as handle:
                handle.write(candidate); temporary = pathlib.Path(handle.name)
            try:
                os.chmod(temporary, target.stat().st_mode & 0o777 if target.exists() else 0o644)
                temporary.replace(target)
            finally: temporary.unlink(missing_ok=True)
            if baseline is None: core.run('add', '--no-auto-props', '--', str(target)+'@')
            current_props = files.properties(core, str(target))
            wanted = decoded(entry['properties'])
            for key in sorted(set(current_props)|set(wanted)):
                if current_props.get(key) == wanted.get(key): continue
                if key not in wanted: core.run('propdel', key, '--', str(target)+'@')
                else:
                    with tempfile.NamedTemporaryFile() as value:
                        value.write(wanted[key]); value.flush()
                        core.run('propset', key, '--file', value.name, '--', str(target)+'@')
    actual = target.read_bytes() if target.exists() else None
    actual_props = files.properties(core, str(target)) if actual is not None else {}
    if actual != candidate or encoded(actual_props) != entry['properties']: raise RuntimeError('写入核验失败，请保留现场与备份')
    entry['status'] = 'accepted'
    write_record['status'] = 'written'
    core.write_json(write_folder/'record.json', write_record)
    entry['writeBackup'] = str(write_folder/'record.json')
    state.pop('pending')
    core.write_json(folder/'review.json', state)
    return entry


def withdraw_row(core,folder,report,state,path,sheet,row):
    entry=state['items'].get(path)
    if entry is None or entry['status']!='ready' or entry.get('authorIsolation')!=AUTHOR_ISOLATION_VERSION:
        raise RuntimeError('此文件不能编辑，请重新生成待合入副本')
    if not path.lower().endswith(('.xlsx','.xlsm')):raise RuntimeError('仅支持表格行撤回')
    candidate=reviewed_bytes(folder,entry,'candidate','待合入')
    baseline=reviewed_bytes(folder,entry,'baseline','Release快照')
    if candidate is None:raise RuntimeError('删除文件候选不支持逐行撤回')
    from workbook_cells import restore_row
    withdrawn=entry.setdefault('withdrawnRows',[])
    previous=next((v for v in withdrawn if v['sheet']==sheet and v['row']==row),None)
    backups=folder/'撤回前副本'/hashlib.sha256(path.encode()).hexdigest()
    if previous is not None:
        digest=previous.get('backupHash')
        if digest:
            if not re.fullmatch(r'[0-9a-f]{64}',digest):raise RuntimeError('复原备份记录无效')
            source=backups/(digest+'.xlsx')
        else:
            # Legacy withdrawals stored complete snapshots before each operation.
            snapshots=sorted(backups.glob('*.xlsx'),key=lambda p:p.stat().st_mtime_ns)
            if not snapshots:raise RuntimeError('找不到撤回前副本，无法复原')
            source=snapshots[0]
        saved=source.read_bytes()
        if files.data_hash(saved)!=source.stem:raise RuntimeError('复原备份已改变，不能复原')
        data=restore_row(candidate,saved,sheet,row)
    else:
        deleted=entry.get('nativeWrite',{}).get('deletedRows',{}).get(sheet,[])
        source_row=row
        for removed in sorted(deleted):
            if removed<=source_row:source_row+=1
        data=restore_row(candidate,baseline,sheet,row,source_number=source_row)
    same=files.same_data(data,baseline,path) and entry['properties']==entry['beforeProperties']
    if same and baseline is not None:data=baseline
    destination=safe_path(folder/'待合入',path)
    backup=folder/'撤回前副本'/hashlib.sha256(path.encode()).hexdigest()/ (files.data_hash(candidate)+'.xlsx')
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():backup.write_bytes(candidate)
    with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as handle:
        handle.write(data);temporary=pathlib.Path(handle.name)
    try:temporary.replace(destination)
    finally:temporary.unlink(missing_ok=True)
    entry.pop('risk', None)
    entry['candidateHash']=files.data_hash(data)
    entry['same']=same
    if previous is not None:
        entry['withdrawnRows']=[v for v in withdrawn if not (v['sheet']==sheet and v['row']==row)]
        entry['summary']+='\n已复原：'+sheet+' 第 '+str(row)+' 行，恢复撤回前的待合入修改。'
    else:
        withdrawn.append({'sheet':sheet,'row':row,'backupHash':files.data_hash(candidate)})
        entry['summary']+='\n已撤回：'+sheet+' 第 '+str(row)+' 行，恢复为 Release 快照内容。'
    core.write_json(folder/'review.json',state)
    return entry


def acquire_operation_lock(core, lock, *, wait=False, timeout=120):
    """Queue cancellable preparation; never retry a working-copy write."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            try_lock(lock)
            return
        except BlockingIOError:
            if not wait or time.monotonic() >= deadline:
                raise RuntimeError('Release 有其他合入任务正在运行，请稍后再试')
            phase = getattr(core, 'sync_phase', None)
            if phase:
                phase('等待其他合入任务结束 · 正在排队，可取消')
            time.sleep(min(.2, max(0, deadline - time.monotonic())))


def operate(core, folder, action, path, sheet=None, row=None):
    folder = pathlib.Path(folder)
    report = json.loads((folder/'report.json').read_text())
    config = core.verify_config(report)
    with contextlib.ExitStack() as stack:
        identity = hashlib.sha256(str(pathlib.Path(config['target']).resolve()).encode()).hexdigest()
        for location in (folder/'operation.lock', pathlib.Path(tempfile.gettempdir())/('svnflow-sync-'+identity+'.lock')):
            lock = stack.enter_context(location.open('a'))
            acquire_operation_lock(core, lock, wait=action in ('stage', 'regenerate', 'assess'))
        state = json.loads((folder/'review.json').read_text())
        if state.get('mode') != 'review-v1' or state['reportHash'] != files.report_hash(report): raise RuntimeError('合入报告已变化，请保留备份并重新合入')
        if state.get('pending'): raise RuntimeError('上次写入未完成，请检查现场和备份；不会自动重试')
        if action == 'regenerate':
            archive_candidate(core, folder, state, path)
            return stage(core, folder, report, state, path)
        if action == 'stage': return stage(core, folder, report, state, path)
        if action == 'assess':
            entry = state['items'][path]
            if entry['status'] != 'ready': raise RuntimeError('文件不在待确认状态')
            assess_risk(core, folder, report, entry)
            core.write_json(folder/'review.json', state)
            return entry
        if action == 'accept-low':
            validate_low_risk(state['items'][path])
            return accept(core, folder, report, state, path)
        if action == 'accept': return accept(core, folder, report, state, path)
        if action in ('text-review','choose-text'):
            import text_review
            return text_review.load(core,folder,report,state,path) if action == 'text-review' else text_review.choose(core,folder,report,state,path,sheet,row)
        if action == 'withdraw-row': return withdraw_row(core,folder,report,state,path,sheet,row)
        if action == 'defer':
            entry = state['items'][path]
            if entry['status'] != 'ready': raise RuntimeError('文件不在待确认状态')
            entry['status'] = 'skipped'; core.write_json(folder/'review.json', state); return entry
        raise RuntimeError('未知合入操作')
