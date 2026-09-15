"""Compact empty data rows in plain, formula-free keyed configuration books.

Run only after replay: intermediate row addresses still belong to revision metadata.
Unsupported reference-bearing features leave the book untouched, never half compacted.
"""
import bisect
import io
import re
import posixpath
import zipfile
from lxml import etree as E

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
Q = '{' + NS + '}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
CELL = r'(\$?[A-Z]{1,3})(\$?)([1-9][0-9]*)'
ADDRESS = re.compile('^'+CELL+'$')
TOKEN = re.compile(r'"(?:[^"]|"")*"|(?<![\w.])'+CELL+r'(?![\w.(])')
ALLOWED = set(('dimension sheetViews sheetFormatPr cols sheetData sheetCalcPr '
               'autoFilter sortState phoneticPr conditionalFormatting '
               'dataValidations printOptions pageMargins pageSetup headerFooter').split())

class Unsupported(ValueError):
    pass

class Rows:
    def __init__(self, deleted):
        self.deleted = sorted(deleted)
        self.lookup = set(deleted)
    def point(self, number):
        return max(1, number-bisect.bisect_left(self.deleted, number))
    def address(self, address):
        match = ADDRESS.fullmatch(address)
        if not match: raise Unsupported('非 A1 单元格引用：'+address)
        col, absolute, row = match.groups()
        return col+absolute+str(self.point(int(row)))
    def reference(self, reference):
        result = []
        for area in reference.split():
            ends = area.split(':')
            if len(ends)>2: raise Unsupported('复杂引用：'+area)
            matches = [ADDRESS.fullmatch(x) for x in ends]
            if not all(matches): raise Unsupported('复杂引用：'+area)
            first, last = int(matches[0][3]), int(matches[-1][3])
            if last < first: raise Unsupported('反向区域引用：'+area)
            if len(ends)==1:
                if first not in self.lookup: result.append(self.address(area))
                continue
            start = first
            while start in self.lookup and start<=last: start+=1
            end = last
            while end in self.lookup and end>=start: end-=1
            if end<start: continue
            start_text = matches[0][1]+matches[0][2]+str(self.point(start))
            end_text = matches[1][1]+matches[1][2]+str(self.point(end))
            result.append(start_text+':'+end_text)
        return ' '.join(result)
    def formula(self, formula):
        # Conditional-format and validation formulas only; qualified references
        # and structured references require Excel's full dependency machinery.
        outside = re.sub(r'"(?:[^"]|"")*"', '', formula)
        if any(x in outside for x in ('!', '[', ']', "'", ':')):
            raise Unsupported('复杂格式公式')
        def replace(match):
            if match[0].startswith('"'): return match[0]
            return match[1]+match[2]+str(self.point(int(match[3])))
        return TOKEN.sub(replace, formula)


def compact(data):
    """Return (workbook, per-sheet counts, skip reason). No change on unsupported input."""
    try:
        return _compact(data)
    except Unsupported as error:
        return data, {}, str(error)


def _compact(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = {n:archive.read(n) for n in archive.namelist()}
    parser=E.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)
    parse=lambda raw:E.fromstring(raw, parser)
    workbook=parse(parts['xl/workbook.xml'])
    rels={r.get('Id'):posixpath.normpath(posixpath.join('xl',r.get('Target'))).lstrip('/')
          for r in parse(parts['xl/_rels/workbook.xml.rels'])}
    strings=[]
    if 'xl/sharedStrings.xml' in parts:
        strings=[''.join(n.itertext()) for n in parse(parts['xl/sharedStrings.xml'])]
    def text(cell):
        if cell.get('t')=='s':
            v=cell.find(Q+'v')
            return strings[int(v.text)] if v is not None and v.text else ''
        return ''.join(x.text or '' for x in cell.iter() if x.tag in (Q+'v',Q+'t'))
    sheets={s.get('name'):(rels[s.get(REL+'id')],None) for s in workbook.find(Q+'sheets')}
    maps={};counts={}
    for name,(path,_) in list(sheets.items()):
        root=parse(parts[path]);sheets[name]=(path,root)
        if root.find('.//'+Q+'f') is not None: raise Unsupported('工作簿仍含单元格公式，保留原行位置')
        sheet_data=root.find(Q+'sheetData')
        if sheet_data is None: continue
        rows=list(sheet_data)
        if not any(text(c).startswith('*') for row in rows if int(row.get('r'))<=5 for c in row): continue
        if any(E.QName(child).namespace!=NS or E.QName(child).localname not in ALLOWED for child in root):
            raise Unsupported('工作表含尚未支持迁移的布局或扩展：'+name)
        relationship=posixpath.join(posixpath.dirname(path),'_rels',posixpath.basename(path)+'.rels')
        if relationship in parts and any(not r.get('Type','').endswith('/printerSettings') for r in parse(parts[relationship])):
            raise Unsupported('工作表含批注、图形或其他关联对象：'+name)
        meaningful={int(row.get('r')) for row in rows if any(text(c) or len(c)>1 or any(x.tag!=Q+'v' for x in c if x.tag!=Q+'is') for c in row)}
        # Keep rows 1–5 (declarations), and all keyless notes/content. Empty rows
        # within the used area, including unstored gaps, are physical deletions.
        last=max([5,*[int(row.get('r')) for row in rows]])
        deleted=set(range(6,last+1))-meaningful
        if not deleted: continue
        mapping=Rows(deleted);maps[name]=mapping;counts[name]=len(deleted)
        for row in list(sheet_data):
            number=int(row.get('r'))
            if number in deleted: sheet_data.remove(row);continue
            row.set('r',str(mapping.point(number)))
            for cell in row: cell.set('r',mapping.address(cell.get('r')))
        for node in list(root.iter()):
            if node.tag in (Q+'row',Q+'c'): continue
            if node.tag==Q+'dimension': root.remove(node);continue
            for attr in ('activeCell','topLeftCell'):
                if attr in node.attrib: node.set(attr,mapping.address(node.get(attr)))
            for attr in ('ref','sqref'):
                if attr not in node.attrib: continue
                updated=mapping.reference(node.get(attr))
                if updated: node.set(attr,updated)
                elif node.tag==Q+'selection': node.set(attr,mapping.address(node.get(attr).split()[0].split(':')[0]))
                else:
                    parent=node.getparent()
                    if parent is not None: parent.remove(node)
            if node.tag in (Q+'formula',Q+'formula1',Q+'formula2') and node.text:
                node.text=mapping.formula(node.text)
        validations=root.find(Q+'dataValidations')
        if validations is not None: validations.set('count',str(len(validations)))
    if not maps: return data,{},''
    for _, root in sheets.values():
        for node in root.iter():
            if node.tag in (Q+'formula',Q+'formula1',Q+'formula2') and node.text:
                Rows([]).formula(node.text)  # Also reject references from untouched sheets.
            if node.tag==Q+'cfvo' and node.get('type')=='formula':
                raise Unsupported('条件格式阈值含公式')
    if 'xl/vbaProject.bin' in parts or 'xl/calcChain.xml' in parts:
        raise Unsupported('工作簿含宏或计算依赖链')
    for node in workbook.findall(Q+'definedNames/'+Q+'definedName'):
        value=node.text or ''
        # Filter/print area names are absolute, sheet-qualified A1 ranges.
        match=re.fullmatch(r"(?:'((?:[^']|'')+)'|([^!]+))!(.+)",value)
        if not match: raise Unsupported('复杂命名范围')
        name=(match[1] or match[2]).replace("''", "'")
        if name in maps:
            updated=maps[name].reference(match[3])
            if not updated: raise Unsupported('命名范围完全落在空行中')
            node.text=value[:value.index('!')+1]+updated
    # Workbook-level features may hold references outside sheet XML.
    if any('/pivot' in n or '/charts/' in n or '/externalLinks/' in n or '/tables/' in n for n in parts):
        raise Unsupported('工作簿含跨部件数据引用')
    for name in maps:
        path,root=sheets[name];parts[path]=E.tostring(root,encoding='utf-8')
    parts['xl/workbook.xml']=E.tostring(workbook,encoding='utf-8')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in parts.items(): archive.writestr(name,raw)
    return output.getvalue(),counts,''
