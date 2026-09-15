"""Conservative OOXML three-way patching; never copy a Dev snapshot over Release."""
import io
import zipfile
from xml.dom import minidom

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def signature(node):
    if node.nodeType == node.ELEMENT_NODE:
        attrs = sorted((node.attributes.item(i).namespaceURI or '', node.attributes.item(i).name,
                        node.attributes.item(i).value) for i in range(node.attributes.length))
        return (node.namespaceURI, node.localName, attrs,
                [signature(n) for n in node.childNodes if n.nodeType != n.TEXT_NODE or node.localName in ('t', 'v', 'f') or n.data.strip()])
    return (node.nodeType, node.nodeValue)

def worksheet_patch(before, after, local, name, prefer_source=False, accepted=()):
    docs = [minidom.parseString(data) for data in (before, after, local)]
    cells = []
    skeletons = []
    for doc in docs:
        mapping = {}
        for cell in list(doc.getElementsByTagNameNS(MAIN, 'c')):
            address = cell.getAttribute('r')
            if not address or address in mapping:
                raise ValueError('单元格地址缺失或重复')
            mapping[address] = cell
        cells.append(mapping)
        skeleton = doc.cloneNode(True)
        for cell in list(skeleton.getElementsByTagNameNS(MAIN, 'c')):
            cell.parentNode.removeChild(cell)
        skeletons.append(signature(skeleton.documentElement))
    if not (skeletons[0] == skeletons[1] == skeletons[2]):
        raise ValueError('工作表结构与 Release 分叉，无法隔离结构变化')
    sig = lambda cell: signature(cell) if cell is not None else None
    allowed = [{c.getAttribute('r'): c for c in minidom.parseString(data).getElementsByTagNameNS(MAIN, 'c')} for data in accepted]
    changes = 0
    for address in sorted(set(cells[0]) | set(cells[1]) | {key for value in allowed for key in value}):
        a, b, target = [mapping.get(address) for mapping in cells]
        if sig(target) == sig(b): continue
        if sig(a) == sig(b) and not any(sig(target) == sig(value.get(address)) for value in allowed): continue
        if sig(target) != sig(a) and not any(sig(target) == sig(value.get(address)) for value in allowed):
            # Replacing this whole cell would also copy unchanged source style,
            # formula or value components. Delegate divergent cells to the
            # component-aware workbook merger, even when author values win.
            raise ValueError('单元格 ' + address + ' 需要按数值、公式和样式分别隔离')
        # Shared/array formulas have dependencies beyond one cell.
        for cell in (a, b):
            if cell and any(f.hasAttribute('t') or f.hasAttribute('ref') for f in cell.getElementsByTagNameNS(MAIN, 'f')):
                raise ValueError('共享/数组公式需要整组核对：' + address)
        if target is not None:
            if b is None:
                target.parentNode.removeChild(target)
            else:
                target.parentNode.replaceChild(docs[2].importNode(b, True), target)
        else:
            row_number = ''.join(c for c in address if c.isdigit())
            row = next((r for r in docs[2].getElementsByTagNameNS(MAIN, 'row') if r.getAttribute('r') == row_number), None)
            if row is None:
                raise ValueError('新增行需要结构核对：' + address)
            def column(ref):
                value = 0
                for c in ref:
                    if c.isalpha(): value = value * 26 + ord(c.upper()) - 64
                return value
            following = next((n for n in row.childNodes if n.nodeType == n.ELEMENT_NODE and n.localName == 'c' and column(n.getAttribute('r')) > column(address)), None)
            row.insertBefore(docs[2].importNode(b, True), following)
        changes += 1
    return docs[2].toxml(encoding='utf-8'), changes

def patch_workbook(before, after, local, prefer_source=False, accepted=()):
    def unpack(data):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(set(archive.namelist())) != len(archive.namelist()):
                raise ValueError('Excel 包含重复部件')
            return {n: archive.read(n) for n in archive.namelist()}
    base, source, target = map(unpack, (before, after, local))
    if any(n.startswith('_xmlsignatures/') for n in set(base) | set(source) | set(target)):
        raise ValueError('签名工作簿需单独核对')
    history = [unpack(data) for data in accepted]
    result = dict(target)
    notes = []
    for name in sorted(set(base) | set(source) | {name for value in history for name in value}):
        a, b, t = base.get(name), source.get(name), target.get(name)
        if t == b: continue
        if a == b and not any(value.get(name) != b for value in history): continue
        worksheet = name.startswith('xl/worksheets/') and name.endswith('.xml')
        # Cell string/style indexes must have the same meaning on both branches.
        if worksheet and b is not None:
            for dependency in ('xl/sharedStrings.xml', 'xl/styles.xml', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'):
                if target.get(dependency) not in (base.get(dependency), source.get(dependency)):
                    raise ValueError(name + ' 的字符串、样式或工作表映射依赖不同')
        if t == a or (prefer_source and b is None) or any(t == value.get(name) for value in history):
            if b is None:
                result.pop(name, None)
                notes.append('删除部件 ' + name)
            else:
                result[name] = b
                notes.append('迁移部件增量 ' + name)
        elif worksheet and a is not None and b is not None and t is not None:
            result[name], count = worksheet_patch(a, b, t, name, prefer_source, [v[name] for v in history if name in v])
            notes.append(name + '：迁移 ' + str(count) + ' 个单元格变化（含公式转值）')
        elif a == b:
            continue
        else:
            raise ValueError(name + ' 与 Release 冲突；未复制 Dev 整文件')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in result.items(): archive.writestr(name, data)
    return output.getvalue(), notes
