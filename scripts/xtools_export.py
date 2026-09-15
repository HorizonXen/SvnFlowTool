import contextlib
import ast
from platform_lock import try_lock
import hashlib
import json
import pathlib
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET

import file_sync
import staged_sync
from workbook_cells import Book
from workbook_inspect import semantic_cells
import lua_sync


def verify_export_config(core, report, *, local):
    if report.get('mode') != 'workspace-export':
        return core.verify_config(report)
    if not local:
        raise RuntimeError('目录导出记录不能用于合入导出。')
    expected = report['config']
    if core.load_workspace_export_config(expected['target']) != expected:
        raise RuntimeError('导出工作副本的配置或 SVN 身份已改变，请重新打开配置导出。')
    return expected


def initialize_workspace(core, folder, target):
    folder = pathlib.Path(folder).resolve()
    if (folder / 'report.json').exists():
        report = json.loads((folder / 'report.json').read_text())
        if report.get('mode') != 'workspace-export' or pathlib.Path(report['config']['target']).resolve() != pathlib.Path(target).resolve():
            raise RuntimeError('导出记录不属于当前工作副本。')
        verify_export_config(core, report, local=True)
        return
    config = core.load_workspace_export_config(target)
    folder.mkdir(parents=True, exist_ok=True)
    core.write_json(folder / 'report.json', dict(mode='workspace-export', config=config))


@contextlib.contextmanager
def desktop_metadata_ignored():
    """Finder view-state files are not export inputs or generated artifacts.

    Keep this desktop policy scoped to this operation; the shared exporter
    continues to own all configuration, toolchain and output validation.
    """
    import xtools_bridge
    original = xtools_bridge.tree
    def configuration_tree(root):
        return {path: digest for path, digest in original(root).items()
                if pathlib.PurePosixPath(path).name != '.DS_Store'}
    xtools_bridge.tree = configuration_tree
    try:
        yield
    finally:
        xtools_bridge.tree = original


@contextlib.contextmanager
def context(core, folder, *, local=False):
    folder = pathlib.Path(folder).resolve()
    report = json.loads((folder / 'report.json').read_text())
    config = verify_export_config(core, report, local=local)
    root = pathlib.Path(config['target']).resolve()
    identity = hashlib.sha256(str(root).encode()).hexdigest()
    with contextlib.ExitStack() as stack:
        for location in (folder / 'operation.lock', pathlib.Path(tempfile.gettempdir()) / ('svnflow-sync-' + identity + '.lock')):
            lock = stack.enter_context(location.open('a'))
            try:
                try_lock(lock)
            except BlockingIOError:
                raise RuntimeError('当前工作副本有其他任务运行，不能同时导出')
        ledger = folder / 'review.json'
        state = json.loads(ledger.read_text()) if ledger.exists() else {}
        if state.get('pending') or (not local and state.get('reportHash') != file_sync.report_hash(report)):
            raise RuntimeError('合入尚未完成或报告发生变化')
        if local:
            state = dict(reportHash=file_sync.report_hash(report), items={})
        yield folder, report, config, root, state


def read_lua(path):
    prefix, node, suffix = lua_sync.parse(pathlib.Path(path).read_bytes())
    prefix = re.sub(r'--[^\n]*', '', prefix).strip()
    suffix = re.sub(r'--[^\n]*', '', suffix).strip()
    declaration = re.fullmatch(r'local\s+([A-Za-z_][A-Za-z_0-9]*)\s*=', prefix)
    if not ((declaration and suffix == 'return ' + declaration[1]) or (prefix == 'return' and not suffix)):
        raise ValueError('Lua 包含未核验的可执行上下文')

    def literal(raw):
        if raw in ('true', 'false', 'nil'):
            return {'true': True, 'false': False, 'nil': None}[raw]
        match = re.fullmatch(r'\[(=*)\[([\s\S]*)\]\1\]', raw)
        if match:
            return match[2]
        if raw.startswith(('"', "'")):
            if re.search(r"""\\(?![\\\"'nrtabfv])""", raw):
                raise ValueError('尚未支持的 Lua 字符串转义，禁止猜测')
            return ast.literal_eval(raw)
        if re.fullmatch(r'[+-]?\d+', raw):
            return int(raw)
        if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', raw):
            return float(raw)
        raise ValueError('无法独立解析 Lua 字面量')

    def convert(current):
        if current.children is None:
            return literal(current.raw)
        result = {}
        for (kind, raw), child in current.children.items():
            key = raw if kind == 'name' else literal(raw)
            if isinstance(key, bool) or key is None:
                raise ValueError('配置 Lua 键不能是布尔值或 nil')
            if key in result:
                raise ValueError('Lua 解码后存在重复键')
            result[key] = convert(child)
        return result
    return convert(node)


def export_semantic_cells(path):
    """Normalize the converter's reverse-enum declaration marker, in memory only.

    xlsTools enum.go strips one trailing '$' when registering the forward enum.
    Keep the independent field verifier aligned without editing source workbooks
    or weakening its missing-definition / conflicting-value checks.
    """
    sheets = semantic_cells(path)
    # Mark match-enum dependencies for the shared verifier's enum discovery.
    # The normalized spelling is internal; the workbook bytes remain unchanged.
    for sheet in sheets:
        for address, cell in sheet['cells'].items():
            if not address.endswith('3') or re.sub('[A-Z]', '', address) != '3':
                continue
            kind = cell.get('value', '')
            if isinstance(kind, str) and re.fullmatch(r'match:[A-Za-z_0-9, ]+\s*\n(?:default|defalut):string', kind):
                first, fallback = kind.split('\n')
                names = [name.strip() for name in first[6:].split(',')]
                cell['value'] = 'match:' + ','.join('enum.' + name for name in names) + '\n' + fallback
    if not re.search(r'(?:枚举|enum).*\.xlsx$', pathlib.Path(path).name, re.I):
        return sheets
    for sheet in sheets:
        cells = sheet['cells']
        rows = {}
        for address, cell in cells.items():
            match = re.fullmatch(r'([A-Z]+)(\d+)', address)
            if match:
                rows.setdefault(int(match[2]), {})[match[1]] = cell
        for number, row in sorted(rows.items()):
            header = {str(cell.get('value', '')).lstrip('*'): col for col, cell in row.items()}
            if not {'enumname', 'key', 'ckey', 'value'} <= header.keys():
                continue
            for index, item in rows.items():
                cell = item.get(header['enumname'])
                if index >= number + 3 and cell and isinstance(cell.get('value'), str):
                    cell['value'] = cell['value'].strip(' ').removesuffix('$')
            break
    return sheets


def semantics(value):
    import xtools_bridge
    original = xtools_bridge.typed_value
    def typed(raw, kind, enum_maps=None):
        if re.fullmatch(r'list\((int|long|float|double|string)\)', kind or ''):
            # xlsTools parseCellList accepts comma-separated values with optional
            # brackets (TrimPrefix / TrimSuffix), then trims each element.
            # Keep scalar validation and the complete output comparison intact.
            body = '' if raw is None else str(raw).strip()
            if body:
                raw = '[' + body.removeprefix('[').removesuffix(']') + ']'
        if isinstance(kind, str) and kind.startswith('match:enum.'):
            first, fallback = kind.split('\n')
            label = str(raw or '').strip(' ')
            for name in first[6:].split(','):
                mapping = (enum_maps or {}).get(name[5:])
                if mapping is None:
                    raise ValueError('缺少独立枚举定义：' + name)
                if label in mapping:
                    return original(label, name, enum_maps)
            if fallback not in ('default:string', 'defalut:string'):
                raise ValueError('尚无独立动态类型解析规则：' + kind)
            return original(raw, 'string', enum_maps)
        return original(raw, kind, enum_maps)
    xtools_bridge.typed_value = typed
    try:
        return xtools_bridge.verify_fields(value, read_workbook=export_semantic_cells, read_lua=read_lua, read_sheet_names=lambda path: list(Book(path.read_bytes()).sheets))
    finally:
        xtools_bridge.typed_value = original


def latest_path(folder, local):
    return folder / ('xtools-local-latest.json' if local else 'xtools-latest.json')


def local_workbook(core, root, path):
    if not path.lower().endswith('.xlsx'):
        raise RuntimeError('请选择 .xlsx 格式的 Excel：' + path)
    target = staged_sync.safe_path(root, path)
    if not target.is_file():
        raise RuntimeError('所选 Excel 不存在：' + path)
    result = core.run('status', '--xml', '--', str(target) + '@')
    for entry in ET.fromstring(result.stdout).findall('.//entry'):
        wc = entry.find('wc-status')
        if wc is not None and (wc.get('item') in {'conflicted', 'obstructed', 'missing', 'deleted', 'replaced', 'incomplete', 'external'} or wc.get('props') == 'conflicted' or wc.get('tree-conflicted') == 'true' or wc.get('switched') == 'true'):
            raise RuntimeError('所选 Excel 存在冲突或异常状态：' + path)
    return target.read_bytes()


def prepare(core, folder, paths=None, *, local=False):
    from xtools_bridge import prepare as build

    with desktop_metadata_ignored(), context(core, folder, local=local) as (folder, report, config, root, state):
        identity = core.info(str(root))
        latest_path(folder, local).unlink(missing_ok=True)
        requested = None if paths is None else set(paths)
        if local and requested is None:
            raise RuntimeError('请选择本地 Excel')
        if requested is not None:
            if not requested or len(requested) != len(paths):
                raise RuntimeError('请选择不重复的已合入 Excel')
            for path in requested:
                entry = state['items'].get(path, {})
                if not local and (entry.get('status') != 'accepted' or entry.get('same') or not path.lower().endswith('.xlsx')):
                    raise RuntimeError('所选文件不是本批已合入且发生变化的 Excel：' + path)
        workbooks = {}
        local_hashes = {}
        for path in sorted(requested or []) if local else []:
            data = local_workbook(core, root, path)
            local_hashes[path] = hashlib.sha256(data).hexdigest()
            workbooks[path] = [name for name in Book(data).sheets if not name.startswith('~')]
        for path, entry in state['items'].items():
            if requested is not None and path not in requested:
                continue
            if entry['status'] != 'accepted' or entry.get('same') or not path.lower().endswith('.xlsx'):
                continue
            expected = staged_sync.reviewed_bytes(folder, entry, 'candidate', '待合入')
            target = staged_sync.safe_path(root, path)
            if expected is None:
                raise RuntimeError('删除的配置须先确认关联产物清理：' + path)
            if target.read_bytes() != expected:
                raise RuntimeError('Excel 在合入后发生变化，请重新核对：' + path)
            workbooks[path] = [name for name in Book(expected).sheets if not name.startswith('~')]
        if not workbooks:
            raise RuntimeError('本批没有已确认且发生变化的 Excel')
        result = build(root, workbooks, folder / 'xtools' / uuid.uuid4().hex)
        verify_export_config(core, report, local=local)
        if core.info(str(root)) != identity:
            raise RuntimeError('候选生成期间 SVN 身份或版本变化')
        result['identity'] = identity
        result['reportHash'] = state['reportHash']
        result['message'] = '导出候选已生成；未写入 Release。'
        value = json.loads(pathlib.Path(result['receipt']).read_text())
        if local:
            observed = {row['path']: row['sha256'] for row in value['workbooks']}
            if observed != local_hashes or any(hashlib.sha256(local_workbook(core, root, path)).hexdigest() != digest for path, digest in local_hashes.items()):
                raise RuntimeError('Excel 在生成期间发生变化，请保存后重新生成')
            result['localWorkbooks'] = local_hashes
        proof = semantics(value)
        result['fields'] = proof['fields']
        result['dependencies'] = proof.get('merge_dependencies', [])
        result['ignoredRows'] = proof.get('ignored_rows', [])
        result['outputs'] = value['files']
        result['message'] = '双构建及独立全字段核验通过；请查看输出差异后确认写入，尚未提交 SVN。'
        core.write_json(latest_path(folder, local), result)
        return result


def publish(core, folder, digest, *, resume=False, local=False):
    from xtools_bridge import publish as apply, sha256_file

    with desktop_metadata_ignored(), context(core, folder, local=local) as (folder, report, config, root, state):
        latest = json.loads(latest_path(folder, local).read_text())
        if latest.get('sha256') != digest or latest.get('reportHash') != state['reportHash']:
            raise RuntimeError('当前确认不属于这批候选')
        receipt = pathlib.Path(latest['receipt'])
        if receipt.name != 'receipt.json' or receipt.parent.parent != folder / 'xtools' or receipt.resolve() != receipt:
            raise RuntimeError('候选回执路径不属于当前合入批次')
        if sha256_file(receipt) != digest:
            raise RuntimeError('候选回执与确认哈希不同')
        value = json.loads(receipt.read_text())
        if local and latest.get('localWorkbooks') != {row['path']: row['sha256'] for row in value['workbooks']}:
            raise RuntimeError('本地 Excel 候选范围发生变化')
        for row in ([] if local else value['workbooks']):
            entry = state['items'].get(row['path'])
            if not entry or entry['status'] != 'accepted' or entry['candidateHash'] != row['sha256']:
                raise RuntimeError('已合入 Excel 的确认记录发生变化')
        def guard():
            if local:
                for path, expected in latest['localWorkbooks'].items():
                    if hashlib.sha256(local_workbook(core, root, path)).hexdigest() != expected:
                        raise RuntimeError('Excel 在生成后发生变化，请保存后重新生成：' + path)
            verify_export_config(core, report, local=local)
            if core.info(str(root)) != latest['identity']:
                raise RuntimeError('目标 SVN 身份或版本变化，请重新生成候选')
        guard()
        targets = [row['target'] for row in value['files']]
        # Local conversion is based on current disk inputs. Remote freshness is
        # a merge/commit concern; keep local conflict and hash checks in both modes.
        result = core.run('status', '--xml', *([] if local else ['-u']), '--', *(p + '@' for p in targets))
        for entry in ET.fromstring(result.stdout).findall('.//entry'):
            wc, remote = entry.find('wc-status'), entry.find('repos-status')
            if wc is not None and (wc.get('item') in {'conflicted', 'obstructed', 'missing', 'deleted', 'replaced'} or wc.get('props') not in {'none', 'normal'} or wc.get('tree-conflicted') == 'true' or wc.get('switched') == 'true'):
                raise RuntimeError('输出存在冲突、属性变化或异常状态：' + entry.get('path', ''))
            if remote is not None and (remote.get('item') not in {None, 'none', 'normal'} or remote.get('props') not in {None, 'none', 'normal'}):
                raise RuntimeError('输出在 SVN 远端有新版本，请先核对')
        published = apply(receipt, digest, root, semantic_check=semantics, guard=guard, resume=resume)
        latest['status'] = published['status']
        latest['publishedWorkbooks'] = {row['path']: row['sha256'] for row in value['workbooks']}
        latest['message'] = 'Lua、pmdata 已写入本地工作副本并完成写后核验；尚未提交 SVN。'
        latest['fields'] = published['semantic_verification']['fields']
        core.write_json(latest_path(folder, local), latest)
        return latest


def export(core, folder, paths=None, *, local=False):
    """One explicit export action generates, verifies and publishes its own receipt."""
    candidate = prepare(core, folder, paths, local=local)
    return publish(core, folder, candidate['sha256'], local=local)
