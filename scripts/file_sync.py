"""Aggregate an author's changes into one final, independently reviewable file patch."""
import base64
import difflib
import hashlib
import json
import os
import pathlib
import re
import tempfile
import xml.etree.ElementTree as ET
from workbook_sync import patch_workbook


class SourceAnalysisCache:
    """One check's immutable source work; target replay and history stay live."""
    def __init__(self):
        self.identity=None;self.session=None
    def bind(self,config,item,latest,phase):
        identity=hashlib.sha256(json.dumps([config,item],sort_keys=True).encode()+
                                (latest or b'')).digest()
        if identity!=self.identity:
            self.clear()
            from workbook_cells import WorkbookMergeSession
            self.session=WorkbookMergeSession(latest,phase);self.identity=identity
        return self.session
    def clear(self):
        if self.session is not None:self.session.clear()
        self.session=None;self.identity=None


def group_files(records):
    groups = {}
    for record in sorted(records, key=lambda r: r['revision']):
        for changed in record['paths']:
            if changed.get('kind') == 'dir': continue
            path = changed['path']
            item = groups.setdefault(path, {'path': path, 'kind': changed.get('kind', 'file'), 'revisions': [], 'latestRevision': 0, 'message': '', 'date': ''})
            if record['revision'] not in item['revisions']: item['revisions'].append(record['revision'])
            item.update(latestRevision=record['revision'], message=record['message'], date=record['date'])
    return sorted(groups.values(), key=lambda item: item['path'])


def merge_text(before, after, local, latest=False, history=()):
    """Merge changed ranges; refine overlaps to tokens to exclude unrelated values on the same line."""
    base, right, left = [data.splitlines(keepends=True) for data in (before, after, local)]
    return b''.join(_merge_units(base, right, left, latest, history=[data.splitlines(keepends=True) for data in history]))


def _merge_units(base, right, left, latest=False, inline=False, history=()):
    def edits(value, side):
        result = []
        for tag, a, b, c, d in difflib.SequenceMatcher(None, base, value, autojunk=False).get_opcodes():
            if tag == 'equal': continue
            if tag == 'replace' and b-a == d-c:
                result.extend((a+i, a+i+1, [value[c+i]], side) for i in range(b-a))
            else: result.append((a,b,value[c:d],side))
        return result
    historical_edits = [edits(value, 'history') for value in history]
    desired = edits(right, 'right')
    if history:
        ranges = []
        for a, b, _, _ in sorted(desired + [e for changeset in historical_edits for e in changeset], key=lambda e: (e[0], e[1])):
            if ranges and a <= ranges[-1][1]: ranges[-1][1] = max(ranges[-1][1], b)
            else: ranges.append([a,b])
        masked = []
        for start, end in ranges:
            value, pos = [], start
            for a,b,replacement,_ in desired:
                if a >= start and b <= end:
                    value.extend(base[pos:a]); value.extend(replacement); pos=b
            value.extend(base[pos:end]); masked.append((start,end,value,'right'))
        desired = masked
    changes = sorted(edits(left, 'left') + desired, key=lambda e: (e[0], e[1]))
    groups = []
    for edit in changes:
        if not groups:
            groups.append([edit]); continue
        group = groups[-1]
        end = max(e[1] for e in group)
        # Insertion at a changed boundary is deliberately treated as overlapping.
        overlap = edit[0] < end or (edit[0] == end and (edit[0] == edit[1] or any(e[0] == e[1] == end for e in group)))
        if overlap: group.append(edit)
        else: groups.append([edit])
    result = []
    cursor = 0
    for group in groups:
        start, end = min(e[0] for e in group), max(e[1] for e in group)
        def render(side):
            output, pos = [], start
            for a, b, value, kind in group:
                if kind != side: continue
                output.extend(base[pos:a]); output.extend(value); pos = b
            output.extend(base[pos:end])
            return output
        historical_regions = []
        for changeset in historical_edits:
            relevant = [e for e in changeset if (e[0] < end and e[1] > start) or (e[0] == e[1] and start <= e[0] <= end)]
            if any(e[0] < start or e[1] > end for e in relevant): continue
            value, pos = [], start
            for x, y, replacement, _ in relevant:
                value.extend(base[pos:x]); value.extend(replacement); pos = y
            value.extend(base[pos:end]); historical_regions.append(value)
        a, b = render('left'), render('right')
        sides = {e[3] for e in group}
        if sides == {'left'}: value = a
        elif sides == {'right'} or a == b or a in historical_regions: value = b
        elif not inline and sum(map(len, a+b+base[start:end])) <= 65536:
            def tokens(lines):
                try: return re.findall(r'[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|\w+|\s+|[^\w\s]', b''.join(lines).decode('utf-8'))
                except UnicodeDecodeError: raise RuntimeError('非 UTF-8 文本存在交叉修改，无法安全隔离')
            value = [''.join(_merge_units(tokens(base[start:end]), tokens(b), tokens(a), latest, inline=True, history=[tokens(v) for v in historical_regions])).encode('utf-8')]
        elif b == base[start:end]: value = a
        elif latest:
            source = [e for e in group if e[3] == 'right']
            # A newer selected edit may replace an older selected value. Never
            # bring source context along to resolve a wider ambiguous overlap.
            if len(source) != 1 or source[0][0] != start or source[0][1] != end:
                raise RuntimeError('文本改动范围交叉，无法隔离其他作者的上下文')
            value = b
        else:
            raise RuntimeError('文本与 Release 冲突：第 ' + str(start + 1) + (' 个文本片段附近' if inline else ' 行附近'))
        result.extend(base[cursor:start]); result.extend(value); cursor = end
    result.extend(base[cursor:])
    return result


def same_data(a, b, path, workbook_session=None):
    if a == b: return True
    if a is None or b is None or not path.lower().endswith(('.xlsx', '.xlsm')): return False
    from workbook_cells import logical_signature
    try:
        if workbook_session is not None:return workbook_session.equal(a,b)
        signature=workbook_session.signature if workbook_session is not None else logical_signature
        return signature(a) == signature(b)
    except (KeyError, ValueError, IndexError, TypeError): pass
    import io, zipfile
    from xml.dom import minidom
    from workbook_sync import signature
    with zipfile.ZipFile(io.BytesIO(a)) as left, zipfile.ZipFile(io.BytesIO(b)) as right:
        if set(left.namelist()) != set(right.namelist()): return False
        for name in left.namelist():
            x, y = left.read(name), right.read(name)
            if x == y: continue
            if not name.endswith(('.xml', '.rels')): return False
            if signature(minidom.parseString(x).documentElement) != signature(minidom.parseString(y).documentElement): return False
    return True


def merge_data(before, after, local, path, latest=False, history=(), scope_projection=False,workbook_session=None):
    from galaxy_sync import supports, merge as merge_galaxy
    if supports(path) and all(value is not None for value in (before, after, local)):
        return merge_galaxy(before, after, local, latest, history)
    if same_data(local, after, path,workbook_session): return local
    if same_data(before, after, path,workbook_session) and not history: return local
    # Semantic equality must not turn an XLSX merge into a whole-file copy:
    # caches and storage details may differ while Release content is equal.
    workbook=path.lower().endswith(('.xlsx','.xlsm'))
    if local == before or (not workbook and (same_data(local, before, path) or any(same_data(local, value, path) for value in history))): return after
    if latest and after is None: return None
    if latest and before is None: return after
    if before is None or after is None or local is None:
        raise RuntimeError('文件新增/删除与目标状态不一致：' + path)
    if path.lower().endswith(('.xlsx', '.xlsm')):
        from workbook_cells import patch
        try:return patch(before,after,local,prefer_source=latest,accepted=[v for v in history if v is not None],scope_projection=scope_projection,session=workbook_session)[0]
        except Exception as detail:raise RuntimeError('Excel 无法安全合并：'+str(detail)) from detail
    binary = path.lower().endswith(('.xls', '.bin', '.bytes', '.png', '.jpg', '.jpeg', '.zip', '.dll', '.exe', '.pdf'))
    if binary or any(b'\x00' in data for data in (before, after, local)):
        raise RuntimeError('二进制文件存在不同内容，无法隔离作者改动：' + path)
    if path.lower().endswith('.lua'):
        from lua_sync import merge
        try: return merge(before, after, local, latest, [v for v in history if v is not None])
        except ValueError as error:
            if '字段冲突' in str(error): raise RuntimeError(str(error)) from error
    return merge_text(before, after, local, latest, [v for v in history if v is not None])


def properties(core, target, revision=None):
    args = ['proplist', '--xml', '--verbose']
    if revision is not None: args += ['-r', revision]
    result = core.run(*args, '--', target + '@' + (str(revision) if revision is not None else ''))
    return {p.get('name'): base64.b64decode(p.text or '') if p.get('encoding') == 'base64' else (p.text or '').encode() for p in ET.fromstring(result.stdout).findall('.//property')}


def merge_properties(before, after, local, latest=False, history=()):
    result = dict(local)
    for key in set(before) | set(after) | {key for value in history for key in value}:
        a, b, t = before.get(key), after.get(key), local.get(key)
        if t == b: continue
        if a == b and not any(t == h.get(key) for h in history): continue
        if key in ('svn:mergeinfo', 'svn:externals', 'svn:special'):
            raise RuntimeError('属性包含合并来源、外部依赖或符号链接，需单独核对：' + key)
        if t != a and not latest and not any(t == h.get(key) for h in history): raise RuntimeError('Release 属性冲突：' + key)
        if b is None: result.pop(key, None)
        elif latest and a is not None and t is not None and t != a:
            if b'\x00' in a+b+t: raise RuntimeError('二进制属性无法隔离作者改动：' + key)
            result[key] = merge_text(a,b,t,latest=True,history=[h[key] for h in history if key in h])
        else: result[key] = b
    return result


def report_hash(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def latest_scope_patches(before, after, current, merge):
    """Use an authored delta as a scope, taking values from the pinned Dev tip.

    Project both endpoints onto Dev, then restore Dev in each projection's
    changed positions. Both endpoints are needed when Dev reverted to the old
    value: an empty net diff must not lose the author's touched positions.
    The existing semantic mergers keep unrelated fields/components out.
    """
    if before == after:
        return
    if current is None:
        # A later deletion supersedes every earlier edit to this file.
        yield after if after is not None else before, None
        return
    if current == after:
        yield before, after
        return
    if current == before:
        yield after, before
        return
    for left, right in ((after, before), (before, after)):
        masked = merge(left, right, current)
        if masked != current:
            yield masked, current


def source_snapshot(core, source, revision):
    result = core.run('cat', '-r', revision, '--', source+'@'+str(revision), check=False)
    if result.returncode:
        error = result.stderr.decode('utf-8', 'replace')
        if any(code in error for code in ('E160013', 'W160013', 'W170000')):
            return None, {}
        raise RuntimeError(error)
    return result.stdout, properties(core, source, revision)



def validate_source_snapshot(core, config, path, expected_hash, expected_properties, revision=None):
    revision = revision if revision is not None else core.info(config['dev'], 'HEAD')['revision']
    data, props = source_snapshot(core, core.urlpath(config['dev'], path), revision)
    encoded = {k: base64.b64encode(v).decode() for k,v in props.items()}
    if data_hash(data) != expected_hash or encoded != expected_properties:
        raise RuntimeError('Dev 最新内容或属性在生成后已变化（可能包含他人恢复），请重新生成并核对；未写入 Release')
    return data, props

def build_plan(core, report, item, resolve_author=False, baseline=None):
    import time
    plan_started=time.monotonic()
    c, path = report['config'], item['path']
    selected_mode = c.get('scopeRevisions') is not None
    if selected_mode and (not c['scopeRevisions'] or not set(item['revisions']).issubset(c['scopeRevisions'])):
        raise RuntimeError('文件提交单号不属于本轮所选范围，请重新读取')
    target = pathlib.Path(c['target']) / path
    if not path or pathlib.PurePosixPath(path).is_absolute() or '..' in pathlib.PurePosixPath(path).parts or target.resolve() != pathlib.Path(c['target']).resolve() / path:
        raise RuntimeError('请选择普通文件；目录或符号链接需单独核对')
    if item['kind'] == 'dir': raise RuntimeError('目录级变化需单独核对；不会按目录带入其他文件')
    if target.exists() and not target.is_file(): raise RuntimeError('Release 目标不是普通文件')
    if baseline is None:
        if not target.parent.is_dir(): raise RuntimeError('Release 缺少父目录，请先核对目录依赖：' + str(target.parent))
        status = ET.fromstring(core.run('status', '--xml', '--verbose', '--depth', 'empty', '--', str(target)+'@').stdout).find('.//wc-status')
        if target.exists() and (status is None or status.get('item') not in ('normal', 'modified')):
            raise RuntimeError('文件未受版本控制或状态异常，未覆盖：' + path)
    source = core.urlpath(c['dev'], path)
    dev_latest, dev_props = source_snapshot(core, source, c['snapshot'])
    root = c.get('root') or core.info(c['dev'])['root']
    earliest = None
    synthesized = None
    base_props = None
    synthesized_props = {}
    history, property_history = [], []
    local = (target.read_bytes() if target.exists() else None) if baseline is None else baseline[0]
    local_props = (properties(core, str(target)) if local is not None else {}) if baseline is None else baseline[1]
    final, final_props = local, dict(local_props)
    replay=None;workbook_session=None;deletion_history=None
    if path.lower().endswith(('.xlsx','.xlsm')):
        from workbook_cells import WorkbookReplay, WorkbookMergeSession
        from workbook_history import DeletionHistory
        analysis=getattr(core,'source_analysis',None) if resolve_author else None
        workbook_session=(analysis.bind(c,item,dev_latest,getattr(core,'sync_phase',None)) if analysis is not None
                          else WorkbookMergeSession(dev_latest,getattr(core,'sync_phase',None)))
        deletion_history=DeletionHistory(core,c,path,workbook_session,min(item['revisions']))
        if resolve_author:replay=WorkbookReplay(local,getattr(core,'sync_phase',None),session=workbook_session)
    revisions = sorted(set(item['revisions']))
    for revision in revisions:
        if getattr(core,'sync_progress',None): core.sync_progress(path,revision)
        entry = ET.fromstring(core.run('log', '--xml', '-v', '-r', revision, c['dev']+'@'+str(c['snapshot'])).stdout).find('logentry')
        if entry is None or entry.findtext('author') != c['author']:
            raise RuntimeError('提交作者校验失败：r' + str(revision))
        changed = None
        for candidate in entry.findall('paths/path'):
            relative = core.relpath(candidate.text, c['dev'], root)
            if relative == path: changed = candidate
            if relative is not None and (relative == path or path.startswith(relative.rstrip('/') + '/') or relative == ''):
                if candidate.get('copyfrom-path') or candidate.get('action') == 'R':
                    raise RuntimeError('复制、移动或替换可能携带其他作者历史：' + path)
                if candidate.get('kind') == 'dir' and candidate.get('action') == 'M':
                    a = properties(core, core.urlpath(c['dev'], relative) if relative else c['dev'], revision-1)
                    b = properties(core, core.urlpath(c['dev'], relative) if relative else c['dev'], revision)
                    merge_properties(a, b, a)
        if changed is None or changed.get('kind') == 'dir': raise RuntimeError('提交不包含所选文件：r' + str(revision))
        action = changed.get('action')
        before = None if action == 'A' else core.run('cat', '-r', revision-1, '--', source+'@'+str(revision-1)).stdout
        after = None if action == 'D' else core.run('cat', '-r', revision, '--', source+'@'+str(revision)).stdout
        a = {} if before is None else properties(core, source, revision-1)
        b = {} if after is None else properties(core, source, revision)
        if base_props is None:
            earliest, synthesized, base_props, synthesized_props = before, before, a, dict(a)
            authored, authored_props = before, dict(a)
        if getattr(core, 'sync_phase', None): core.sync_phase('解析文件并汇总作者改动 · r' + str(revision))
        try:
            projected_before=deletion_history.prepare(before,after,revision,replay) if deletion_history else before
            merge = lambda x, y, t: merge_data(x, y, t, path, latest=True)
            if not resolve_author:
                # Strict merges still recognize previously applied authored
                # values, including values now superseded or reverted in Dev.
                authored = merge(before, after, authored)
                authored_props = merge_properties(a, b, authored_props, latest=True)
                history.append(authored)
                property_history.append(dict(authored_props))
            def project(x,y,t):
                compute=lambda:merge_data(x,y,t,path,latest=True,scope_projection=True,workbook_session=workbook_session)
                return workbook_session.project(x,y,t,compute) if workbook_session is not None else compute()
            patches = [(projected_before, after)] if selected_mode else latest_scope_patches(projected_before, after, dev_latest, project)
            for scoped_before, scoped_after in patches:
                if resolve_author:
                    if replay is not None: replay.apply(scoped_before, scoped_after)
                    else: final = merge(scoped_before, scoped_after, final)
                else:
                    synthesized = merge(scoped_before, scoped_after, synthesized)
                    history.append(synthesized)
            property_patches = [(a, b)] if selected_mode else latest_scope_patches(a, b, dev_props, lambda x,y,t: merge_properties(x,y,t,latest=True))
            for scoped_before, scoped_after in property_patches:
                if resolve_author:
                    final_props = merge_properties(scoped_before, scoped_after, final_props, latest=True)
                else:
                    synthesized_props = merge_properties(scoped_before, scoped_after, synthesized_props, latest=True)
                    property_history.append(dict(synthesized_props))
        except (RuntimeError,ValueError) as error:
            raise RuntimeError('r'+str(revision)+('：无法安全重放所选提交：' if selected_mode else '：无法安全提取作者改动范围内的 Dev 最新值：')+str(error)) from error
    if workbook_session is not None:
        # Reclaim the large trees before final target validation. Keep only
        # immutable projections and history summaries for the other target.
        workbook_session.books.clear();workbook_session.equalities.clear()
    if base_props is None: raise RuntimeError('文件没有目标作者提交')
    if getattr(core, 'sync_phase', None): core.sync_phase('将作者改动合入 Release 快照')
    if not resolve_author:
        final = merge_data(earliest, synthesized, local, path, history=history)
        final_props = merge_properties(base_props, synthesized_props, local_props, history=property_history)
    if getattr(core, 'sync_phase', None): core.sync_phase('核验最终内容与文件属性')
    if replay is not None:final=replay.finish()
    same = (replay.same() if replay is not None else same_data(final, local, path)) and final_props == local_props
    if same: final = local
    import deletion_guard
    guard = deletion_guard.check(local, final, dev_latest, path, getattr(core, 'sync_phase', None))
    deletion_guard.check_properties(local_props, final_props, dev_props, path)
    if workbook_session is not None:
        callback=getattr(core,'sync_metrics',None)
        if callback:callback(path,dict(workbook_session.metrics,planSeconds=round(time.monotonic()-plan_started,3)))
        if analysis is None:workbook_session.clear()
    return {'deletionGuard': guard, 'deletionHistory': deletion_history.evidence() if deletion_history else None, 'sourceHash': data_hash(dev_latest),
            'sourceProperties': {k: base64.b64encode(v).decode() for k,v in dev_props.items()},
            'path': path, 'data': final, 'properties': final_props, 'before': local, 'beforeProperties': local_props, 'same': same, 'revisions': revisions}


def describe(plan):
    versions = ', '.join('r' + str(r) for r in plan['revisions'])
    action = '内容相同，无需修改' if plan['same'] else '删除文件' if plan['data'] is None else '新增文件' if plan['before'] is None else '合并最终内容'
    output = f"文件：{plan['path']}\n最新提交：r{max(plan['revisions'])}\n汇总提交：{versions}\n结果：{action}\n同一文件只确认一次；不包含其他文件的修改。"
    compaction = plan.get('rowCompaction', {})
    if compaction.get('sheets'):
        output += '\n空行整理：'+ '；'.join(name+' 移除 '+str(count)+' 个空行位置' for name,count in compaction['sheets'].items())
    elif compaction.get('skipped'):
        output += '\n保留原行布局：'+compaction['skipped']
    if not plan['same'] and not plan['path'].lower().endswith(('.xlsx', '.xlsm')):
        before, after = plan['before'] or b'', plan['data'] or b''
        if b'\x00' not in before + after:
            try:
                diff = list(difflib.unified_diff(before.decode('utf-8').splitlines(), after.decode('utf-8').splitlines(), fromfile='Release 当前', tofile='合并后的最终内容', lineterm=''))
                output += '\n\n' + '\n'.join(diff[:160])
                if len(diff) > 160: output += '\n…差异较长，请在工作台查看完整文件。'
            except UnicodeDecodeError: pass
    return output



def compiled_engine_hash(root=None):
    root=pathlib.Path(root) if root is not None else pathlib.Path(__file__).parent
    modules=('workbook_dom','workbook_cells','workbook_history')
    binaries=sorted(path for name in modules for path in root.glob(name+'.*.so'))
    return hashlib.sha256(b''.join(path.name.encode()+path.read_bytes() for path in binaries)).digest()


def plan_engine_hash():
    root = pathlib.Path(__file__).parent
    return hashlib.sha256(compiled_engine_hash(root)+b''.join((root/name).read_bytes() for name in ('file_sync.py','workbook_sync.py','workbook_cells.py','workbook_history.py','workbook_dom.py','workbook_sparse.py','workbook_compact.py','workbook_native.py','lua_sync.py','galaxy_sync.py','deletion_guard.py'))).hexdigest()


def save_preview(core, folder, report, plan, resolve_author):
    cache = folder/'previews'/hashlib.sha256(plan['path'].encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    meta = {k:v for k,v in plan.items() if k not in ('data','before','properties','beforeProperties')}
    for key in ('data','before'):
        value=plan[key]
        meta[key+'Hash']=hashlib.sha256(value).hexdigest() if value is not None else None
        if value is not None:
            temp=cache/(key+'.tmp');temp.write_bytes(value);temp.replace(cache/key)
    for key in ('properties','beforeProperties'):
        meta[key]={name:base64.b64encode(value).decode() for name,value in plan[key].items()}
    meta.update(reportHash=report_hash(report),engineHash=plan_engine_hash(),resolveAuthor=resolve_author)
    core.write_json(cache/'plan.json',meta)


def load_preview(core, folder, report, item, resolve_author):
    cache=folder/'previews'/hashlib.sha256(item['path'].encode()).hexdigest()
    try:
        meta=json.loads((cache/'plan.json').read_text())
        if meta['reportHash']!=report_hash(report) or meta['engineHash']!=plan_engine_hash() or meta['resolveAuthor']!=resolve_author or meta['path']!=item['path'] or meta['revisions']!=sorted(set(item['revisions'])):return None
        plan={k:v for k,v in meta.items() if k not in ('reportHash','engineHash','resolveAuthor','dataHash','beforeHash')}
        for key in ('data','before'):
            value=(cache/key).read_bytes() if meta[key+'Hash'] is not None else None
            if (hashlib.sha256(value).hexdigest() if value is not None else None)!=meta[key+'Hash']:return None
            plan[key]=value
        for key in ('properties','beforeProperties'):
            plan[key]={name:base64.b64decode(value) for name,value in plan[key].items()}
        target=pathlib.Path(report['config']['target'])/item['path']
        if target.resolve()!=pathlib.Path(report['config']['target']).resolve()/item['path']:return None
        if (target.read_bytes() if target.exists() else None)!=plan['before']:return None
        if (properties(core,str(target)) if target.exists() else {})!=plan['beforeProperties']:return None
        return plan
    except (OSError,ValueError,KeyError,TypeError):return None

def operate_prepared(core, folder, report, state, current, action, path, resolve_author=False):
    if state.get('mode') != 'files-v2': raise RuntimeError('旧版按修订会话不能转为按文件执行，请先处理旧会话')
    if state.get('reportHash') != report_hash(report): raise RuntimeError('报告内容已变化，请保留旧会话并重新核对')
    item = next((f for f in report['fileItems'] if f['path'] == path), None)
    if item is None or path in state['doneFiles']: raise RuntimeError('文件无效或已经处理')
    ledger = folder/'session.json'
    if action == 'skip':
        state['doneFiles'].append(path); state.setdefault('skippedFiles', []).append(path)
        core.write_json(ledger, state); print('已跳过文件：' + path); return
    plan = load_preview(core,folder,report,item,resolve_author) if action == 'apply' else None
    if plan is None:
        plan = build_plan(core, report, item, resolve_author=resolve_author)
        if not plan['same']:
            from workbook_native import finalize
            plan['data'], plan['rowCompaction'] = finalize(plan['before'], plan['data'], path, getattr(core, 'sync_phase', None))
    output = describe(plan)
    if resolve_author: output += '\n冲突处理：所选作者改动位置取本批 Dev 最新快照值（包括他人后续修改），保留 Release 其他内容。'
    if action == 'preview':
        save_preview(core,folder,report,plan,resolve_author)
        print(output); return
    if action != 'apply': raise RuntimeError('无效的文件操作')
    if core.fingerprint(report['config']['target']) != current: raise RuntimeError('预演期间 Release 被修改，已停止')
    target = pathlib.Path(report['config']['target']) / path
    if (target.read_bytes() if target.exists() else None) != plan['before']:
        raise RuntimeError('文件在预演后被修改，已停止')
    dev_live, dev_props = validate_source_snapshot(core, report['config'], path, plan['sourceHash'], plan['sourceProperties'])
    if path.lower().endswith(('.xlsx','.xlsm')):
        from workbook_history import validate
        validate(core,report['config'],path,plan.get('deletionHistory'))
    import deletion_guard
    deletion_guard.check(plan['before'], plan['data'], dev_live, path, getattr(core, 'sync_phase', None))
    deletion_guard.check_properties(plan['beforeProperties'], plan['properties'], dev_props, path)
    save_backup(core, folder, report, plan)
    state['pending'] = {'file': path}; core.write_json(ledger, state)
    if not plan['same']:
        if plan['data'] is None:
            core.run('delete', '--', str(target)+'@')
        else:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.svnflow-', delete=False) as temp:
                temp.write(plan['data']); temporary = pathlib.Path(temp.name)
            try:
                if target.exists(): os.chmod(temporary, target.stat().st_mode & 0o777)
                else: os.chmod(temporary, 0o644)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            if plan['before'] is None: core.run('add', '--no-auto-props', '--', str(target)+'@')
            # Re-read after add because inherited automatic properties may exist.
            present = properties(core, str(target))
            for key in sorted(set(present) | set(plan['properties'])):
                if present.get(key) == plan['properties'].get(key): continue
                if key not in plan['properties']: core.run('propdel', key, '--', str(target)+'@')
                else:
                    with tempfile.NamedTemporaryFile() as value:
                        value.write(plan['properties'][key]); value.flush()
                        core.run('propset', key, '--file', value.name, '--', str(target)+'@')
    actual = target.read_bytes() if target.exists() else None
    if actual != plan['data'] or (properties(core, str(target)) if target.exists() else {}) != plan['properties']:
        raise RuntimeError('迁移后文件核验失败，请保留现场与自动备份：' + path)
    state.setdefault('verifiedFiles', {})[path] = {'sha256': data_hash(actual), 'properties': {k: base64.b64encode(v).decode() for k,v in plan['properties'].items()}}
    (folder/('file-'+hashlib.sha256(path.encode()).hexdigest()+'.log')).write_text(output)
    state['fingerprint'] = core.fingerprint(report['config']['target'])
    state.pop('pending'); state['doneFiles'].append(path)
    state.setdefault('results', {})[path] = 'same' if plan['same'] else 'applied'
    core.write_json(ledger, state)
    print(output + '\n已完成文件处理，尚未提交。')


def compact_accepted(data, path):
    if data is None or not path.lower().endswith('.xlsx'):
        return data, {'sheets': {}, 'skipped': ''}
    from workbook_compact import compact
    result, counts, skipped = compact(data)
    return result, {'sheets': counts, 'skipped': skipped}


def data_hash(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def save_backup(core, folder, report, plan):
    """Persist original content/properties before the first write; never overwrite an earlier backup."""
    backup = folder/'backups'/hashlib.sha256(plan['path'].encode()).hexdigest()
    backup.mkdir(parents=True, exist_ok=True)
    meta = backup/'original.json'
    if meta.exists():
        saved = json.loads(meta.read_text())
        original = (backup/'content').read_bytes() if saved['sha256'] is not None else None
        if saved['path'] != plan['path'] or saved['reportHash'] != report_hash(report) or data_hash(original) != saved['sha256']:
            raise RuntimeError('自动备份校验失败，未写入 Release')
        return
    if plan['before'] is not None: (backup/'content').write_bytes(plan['before'])
    core.write_json(meta, {'path': plan['path'], 'reportHash': report_hash(report), 'sha256': data_hash(plan['before']),
                          'mode': (pathlib.Path(report['config']['target'])/plan['path']).stat().st_mode & 0o777 if plan['before'] is not None else None,
                          'properties': {k: base64.b64encode(v).decode() for k,v in plan['beforeProperties'].items()}})


def verify_results(core, folder, report, state):
    if state.get('reportHash') != report_hash(report): raise RuntimeError('报告变化，不能核验旧会话')
    target = pathlib.Path(report['config']['target'])
    for path, expected in state.get('verifiedFiles', {}).items():
        file = target/path
        if file.resolve() != target.resolve()/path: raise RuntimeError('核验路径异常：' + path)
        actual = file.read_bytes() if file.exists() else None
        props = {k: base64.b64encode(v).decode() for k,v in (properties(core,str(file)) if file.exists() else {}).items()}
        if data_hash(actual) != expected['sha256'] or props != expected['properties']: raise RuntimeError('迁移结果已变化：' + path)
    if core.fingerprint(str(target)) != state['fingerprint']: raise RuntimeError('核验期间 Release 已变化，未出具通过报告')
    rows = ['# 分支迁移核验报告', '', '作者：' + report['config']['author'], '目标：' + str(target),
            '逐文件内容及属性核验：' + str(len(state.get('verifiedFiles', {}))) + ' 项。',
            '旧版会话未保存校验值的项目仅展示处理记录。',
            '原文件与属性保存在 backups 目录；未自动提交 SVN。', '', '| 文件 | 最新提交 | 状态 |', '| --- | --- | --- |']
    for item in report['fileItems']:
        path = item['path']
        status = '已跳过' if path in state.get('skippedFiles', []) else {'same':'内容相同','applied':'已迁移'}.get(state.get('results',{}).get(path),'待处理')
        rows.append('| ' + path.replace('|', r'\|') + ' | r' + str(item['latestRevision']) + ' | ' + status + ' |')
    (folder/'迁移核验报告.md').write_text('\n'.join(rows)+'\n')
    print('Release 状态核验通过；' + str(len(state.get('verifiedFiles', {}))) + ' 个文件内容及属性已核验。\n核验报告与自动备份：' + str(folder))
