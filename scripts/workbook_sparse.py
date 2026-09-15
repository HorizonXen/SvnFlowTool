"""Remove redundant worksheet XML without moving a single cell address."""
from lxml import etree as ET

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
Q = '{' + NS + '}'


def prune(root):
    data = root.find(Q + 'sheetData')
    if data is None:
        return 0
    removed = 0
    for row in list(data):
        if row.tag != Q + 'row':
            continue
        for cell in list(row):
            # Explicit styles (including s=0), metadata, strings, errors and
            # formulas are intentional. Only an implicit, empty numeric cell
            # is equivalent to an absent cell at the same address.
            if cell.tag != Q + 'c' or set(cell.attrib) - {'r', 't'} or cell.get('t', 'n') != 'n':
                continue
            if any(child.tag != Q + 'v' or child.attrib or len(child) or child.text not in (None, '') for child in cell):
                continue
            row.remove(cell)
            removed += 1
        # spans is a storage hint, not row height/visibility/formatting.
        if not len(row) and not (set(row.attrib) - {'r', 'spans'}):
            data.remove(row)
            removed += 1
    if removed:
        dimension = root.find(Q + 'dimension')
        if dimension is not None:
            root.remove(dimension)  # Optional; Excel derives it from retained cells.
    return removed


def compact_xml(data):
    root = ET.fromstring(data, parser=ET.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    return ET.tostring(root, encoding='utf-8') if prune(root) else data
