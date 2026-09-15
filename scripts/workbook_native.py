"""Native Excel finalization of an already isolated Release-based patch.

Adapted from numericalagent/tools/excel/svn_excel_writeback.py: edit typed
cells, delete entire rows bottom-up, save with Excel, then verify before publish.
Only rows emptied by this merge are removed; existing blank layout is retained.
No openpyxl save, whole-Dev copy, or fallback that silently leaves deletion holes.
"""
import bisect
import hashlib
import io
from platform_lock import try_lock
import json
import math
import pathlib
import re
import subprocess
import tempfile
import zipfile
import sys
from workbook_cells import Book, config_layout, config_cell_text, first, children, M

VERSION = 3


def register_style_bases(data):
    """Give imported anonymous base XFs a stable identity before Excel saves.

    Merge can append cellStyleXfs without a matching cellStyle. Excel discards
    those anonymous bases and rebinds surviving cellXfs to unrelated named
    styles. Register hidden names; never alter the actual base or cell format.
    """
    book = Book(data)
    if book.styles is None: return data
    root = book.styles.documentElement
    bases, formats = first(root, 'cellStyleXfs'), first(root, 'cellXfs')
    if bases is None or formats is None: return data
    named = first(root, 'cellStyles')
    existing = children(named) if named is not None else []
    registered = {n.getAttribute('xfId') for n in existing}
    needed = {n.getAttribute('xfId') for n in children(formats) if n.hasAttribute('xfId')} - registered
    if not needed: return data
    if named is None:
        named = book.styles.createElementNS(M, 'cellStyles')
        following = next((n for n in children(root) if n.localName in ('dxfs', 'tableStyles', 'colors', 'extLst')), None)
        root.insertBefore(named, following)
    used = {n.getAttribute('name') for n in existing}
    for index in sorted(needed, key=int):
        if not 0 <= int(index) < len(children(bases)):
            raise ValueError('样式继承引用无效：' + index)
        name = 'SvnFlow_' + index
        while name in used: name += '_'
        style = book.styles.createElementNS(M, 'cellStyle')
        for key, value in (('name', name), ('xfId', index), ('hidden', '1')):
            style.setAttribute(key, value)
        named.appendChild(style); used.add(name)
    named.setAttribute('count', str(len(children(named))))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in book.parts.items():
            archive.writestr(name, book.styles.toxml(encoding='utf-8') if name == 'xl/styles.xml' else value)
    return output.getvalue()


def saved_cell_value(book, cell):
    """Ignore calculation dirtiness, never formula text, array extent or style.

    SpreadsheetML ca/aca request recalculation and may change on Excel save.
    They are not part of the expression; cached results are already excluded
    by Book.cell_value. Keep this normalization local to native-save checks.
    """
    normalized = cell.cloneNode(True)
    formula = first(normalized, 'f')
    if formula is not None:
        for attr in ('ca', 'aca'):
            if formula.hasAttribute(attr): formula.removeAttribute(attr)
    return book.cell_value(normalized)


def saved_xml_equal(before, after):
    """Directional, save-only equivalence; unknown XML remains exact.

    Excel fills font family metadata, drops legacy charset on named Unicode
    fonts, and serializes tints through a signed 16-bit fraction. Keep text,
    run boundaries, named fonts, colors and all other attributes exact.
    """
    if before == after: return True
    if not (isinstance(before, tuple) and isinstance(after, tuple)
            and len(before) == len(after) == 4 and before[:2] == after[:2]):
        return False
    ns, tag, left_attrs, left_children = before
    _, _, right_attrs, right_children = after
    if ns == M and tag in ('font', 'rPr'):
        name_tag = 'name' if tag == 'font' else 'rFont'
        def named(nodes, name):
            return next((n for n in nodes if isinstance(n, tuple) and n[:2] == (M, name)), None)
        name = named(left_children, name_tag)
        if name is not None and name == named(right_children, name_tag) and name[2]:
            family = named(right_children, 'family')
            if (named(left_children, 'family') is None and family is not None
                    and family[2] in [[('', 'val', str(n))] for n in range(6)] and not family[3]):
                right_children = tuple(n for n in right_children if n is not family)
            charset = named(left_children, 'charset')
            # Symbol charset (2), changed explicit charsets and unknown metadata
            # must never be normalized. Text is already Unicode in SpreadsheetML.
            if (charset is not None and charset[2] == [('', 'val', '134')]
                    and not charset[3] and named(right_children, 'charset') is None):
                left_children = tuple(n for n in left_children if n is not charset)
    if ns == M and tag in ('color', 'fgColor', 'bgColor'):
        left = {(n, k): v for n, k, v in left_attrs}
        right = {(n, k): v for n, k, v in right_attrs}
        a, b = left.get(('', 'tint')), right.get(('', 'tint'))
        if a is not None and b is not None:
            try:
                x, y = float(a), float(b)
                # Match the actual truncation path, not an arbitrary color tolerance.
                if (-1 <= x <= 1 and -1 <= y <= 1 and
                        (math.isclose(x, y, rel_tol=0, abs_tol=1e-15) or
                         math.isclose(math.trunc(x * 32767) / 32767, y, rel_tol=0, abs_tol=1e-15))):
                    right[('', 'tint')] = a
            except ValueError:
                pass
        left_attrs = sorted((n, k, v) for (n, k), v in left.items())
        right_attrs = sorted((n, k, v) for (n, k), v in right.items())
    return (left_attrs == right_attrs and len(left_children) == len(right_children)
            and all(saved_xml_equal(a, b) for a, b in zip(left_children, right_children)))


def saved_style_equal(before, after):
    if before == after: return True
    if before is None or after is None: return False
    xf_a, refs_a, number_a, base_a = before
    xf_b, refs_b, number_b, base_b = after
    if number_a != number_b or len(refs_a) != len(refs_b): return False
    if not all(ga == gb and saved_xml_equal(a, b)
               for (ga, a), (gb, b) in zip(refs_a, refs_b)): return False
    if not saved_style_equal(base_a, base_b): return False
    # Excel removes redundant applyFont=1 when the font equals its named base.
    # A different inherited font, explicit 0, or another apply flag still blocks.
    flag = ('', 'applyFont', '1')
    if (base_a is not None and base_b is not None and flag in xf_a[2]
            and not any(k == 'applyFont' for _, k, _ in xf_b[2])
            and saved_xml_equal(refs_a[0][1], base_a[1][0][1])
            and saved_xml_equal(refs_b[0][1], base_b[1][0][1])):
        xf_a = (*xf_a[:2], [a for a in xf_a[2] if a != flag], xf_a[3])
    return saved_xml_equal(xf_a, xf_b)


def payload(cell):
    return cell is not None and (first(cell, 'f') is not None or bool(config_cell_text(cell)))


def deletion_plan(baseline, candidate):
    source, target = Book(baseline), Book(candidate)
    result = {}
    for name in source.sheets.keys() & target.sheets.keys():
        old, new = config_layout(source.cells(name)), config_layout(target.cells(name))
        if old is None or new is None:
            continue
        if old[0] != new[0]:
            raise ValueError('原生行删除：字段声明变化，不能确认行身份：' + name)
        # A populated row becoming entirely empty is an explicit deletion. A
        # cleared field, keyless note, moved record, or pre-existing gap is not.
        deleted = [number for number, row in old[1].items()
                   if number not in old[2] and number not in new[2]
                   and any(payload(c) for c in row.values())
                   and not any(payload(c) for c in new[1].get(number, {}).values())]
        if deleted:
            result[name] = sorted(deleted)
    return result


def literal(value):
    if isinstance(value, bool): return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        value = str(value)
        if not re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', value):
            raise ValueError('无效数值')
        return value
    text = '' if value is None else str(value)
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '" & return & "').replace('\n', '" & linefeed & "') + '"'


def ranges(numbers):
    blocks = []
    for number in sorted(set(numbers)):
        if blocks and number == blocks[-1][1] + 1: blocks[-1][1] = number
        else: blocks.append([number, number])
    return list(reversed(blocks))


def script_for(targets):
    commands = []
    for target in targets:
        commands.append('set ws to worksheet ' + literal(target['sheet']) + ' of wb')
        for edit in target.get('edits', []):
            address = edit['address']
            if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*', address): raise ValueError('无效单元格地址')
            cell = 'range ' + literal(address) + ' of ws'
            kind = edit['value_type']
            if kind == 'text': commands.append('set number format of ' + cell + ' to "@"')
            if kind not in ('text', 'number', 'formula', 'blank', 'boolean'): raise ValueError('未知写入类型')
            prop = 'formula' if kind in ('formula', 'blank') else 'value'
            commands.append('set ' + prop + ' of ' + cell + ' to ' + literal(edit.get('new_value')))
        for start, end in ranges(target.get('delete_rows', [])):
            if not 1 <= start <= end <= 1048576: raise ValueError('无效删除行号')
            commands.append('delete range (entire row of (range ' + literal(f'A{start}:A{end}') + ' of ws)) shift shift up')
    return '\n'.join([
        'on run argv', 'set sourceFile to POSIX file (item 1 of argv)',
        'tell application id "com.microsoft.Excel"',
        'set oldAlerts to display alerts', 'set wb to missing value',
        'try', 'set display alerts to false',
        'set wb to open workbook workbook file name (item 1 of argv) update links 0',
        *commands,
        'save wb', 'close wb saving no', 'set display alerts to oldAlerts',
        'on error errorMessage number errorNumber',
        'if wb is not missing value then', 'try', 'close wb saving no', 'end try', 'end if',
        'set display alerts to oldAlerts', 'error errorMessage number errorNumber',
        'end try', 'end tell', 'end run'])


def apply_edits(file, targets):
    # Excel is a shared process: serialize native jobs, never kill or close user workbooks.
    with (pathlib.Path(tempfile.gettempdir()) / 'svnflow-native-excel.lock').open('a') as lock:
        try: try_lock(lock)
        except BlockingIOError: raise RuntimeError('Excel 原生写入正在运行，请稍后重试')
        result = subprocess.run(['osascript', '-', str(file)], input=script_for(targets),
                                capture_output=True, text=True, timeout=900)
        if result.returncode:
            raise RuntimeError('Excel 原生写入失败，未写入 Release：' + (result.stderr or result.stdout).strip())


def verify(candidate, actual, deleted):
    """Compare every surviving value/formula and style after physical row mapping."""
    before, after = Book(candidate), Book(actual)
    if list(before.sheets) != list(after.sheets): raise ValueError('Excel 保存后工作表发生变化')
    style_checks = {}
    for name in before.sheets:
        rows = deleted.get(name, [])
        def cells(book, move=False):
            result = {}
            for address, cell in book.cells(name).items():
                if not payload(cell): continue
                match = re.fullmatch(r'([A-Z]+)(\d+)', address); number = int(match[2])
                if move:
                    if number in rows: raise ValueError('拒绝删除含数据行：'+name+'!'+address)
                    number -= bisect.bisect_left(rows, number)
                # For formulas Excel legitimately updates references on row deletion.
                # Require manual handling until that result can be verified exactly.
                normalized = cell.cloneNode(True)
                normalized.setAttribute('r', match[1]+str(number))
                value = saved_cell_value(book, normalized)
                result[match[1]+str(number)] = value
            return result
        expected, observed = cells(before, True), cells(after)
        for address in sorted(expected.keys() | observed.keys(),
                              key=lambda a: (int(re.search(r'\d+$', a)[0]), a)):
            left, right = expected.get(address), observed.get(address)
            if left == right: continue
            values_match = left is not None and right is not None and saved_xml_equal(left[0], right[0])
            if values_match:
                key = (id(left[1]), id(right[1]))
                if key not in style_checks:
                    style_checks[key] = saved_style_equal(left[1], right[1])
                if style_checks[key]: continue
            reason = ('新增单元格' if left is None else '缺失单元格' if right is None
                      else '数据或公式变化' if not values_match else '样式变化')
            raise ValueError('Excel 原生保存后数据、公式或样式核验不一致：'
                             + name + '!' + address + '（' + reason + '）；未写入 Release')


def preserve_failure(candidate, actual, deleted, path, error):
    """Retain exact failed inputs outside the transient Excel sandbox folder."""
    root = pathlib.Path.home()/'Library/Application Support/SvnFlow/NativeSaveFailures'
    root.mkdir(parents=True, exist_ok=True)
    folder = pathlib.Path(tempfile.mkdtemp(prefix='failure-', dir=root))
    suffix = pathlib.PurePosixPath(path).suffix
    (folder/('candidate'+suffix)).write_bytes(candidate)
    (folder/('saved'+suffix)).write_bytes(actual)
    (folder/'failure.json').write_text(json.dumps({
        'version': VERSION, 'path': path, 'deletedRows': deleted, 'error': str(error),
        'candidateSHA256': hashlib.sha256(candidate).hexdigest(),
        'savedSHA256': hashlib.sha256(actual).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder


def finalize(baseline, candidate, path, phase=None):
    metadata = {'version': VERSION, 'sheets': {}, 'deletedRows': {}, 'skipped': ''}
    if baseline is None or candidate is None or baseline == candidate or not path.lower().endswith(('.xlsx', '.xlsm')):
        return candidate, metadata
    deleted = deletion_plan(baseline, candidate)
    if not deleted: return candidate, metadata
    if sys.platform != 'darwin':
        raise RuntimeError('此平台暂不支持通过 Microsoft Excel 原生删除整行；候选文件未写入。')
    if phase: phase('Excel 原生整行删除并保存 · ' + pathlib.PurePosixPath(path).name)
    # Only our uniquely named temporary copy is opened; the working copy stays untouched.
    temp_root = pathlib.Path.home()/'Library/Containers/com.microsoft.Excel/Data/tmp'
    if not temp_root.is_dir(): raise RuntimeError('未找到 Microsoft Excel 原生运行环境')
    with tempfile.TemporaryDirectory(prefix='svnflow-excel-', dir=temp_root) as folder:
        file = pathlib.Path(folder)/(pathlib.Path(folder).name + pathlib.PurePosixPath(path).suffix)
        file.write_bytes(register_style_bases(candidate))
        apply_edits(file, [{'sheet': name, 'delete_rows': rows} for name, rows in sorted(deleted.items())])
        actual = file.read_bytes()
        try:
            verify(candidate, actual, deleted)
        except ValueError as error:
            try:
                diagnostic = preserve_failure(candidate, actual, deleted, path, error)
            except OSError as storage_error:
                raise ValueError(str(error) + '；诊断副本保存失败：' + str(storage_error)) from error
            raise ValueError(str(error) + '；诊断副本：' + str(diagnostic)) from error
    metadata.update(sheets={name:len(rows) for name,rows in deleted.items()}, deletedRows=deleted)
    return actual, metadata
