"""Read-only workbook package comparison for the desktop inspector."""
import pathlib,sys,json,zipfile,hashlib,re,xml.etree.ElementTree as E
M='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
def canonical(node):
    return (node.tag,sorted(node.attrib.items()),node.text if node.text and node.text.strip() else '',[canonical(c) for c in node])
def inspect(left,right):
    from workbook_cells import Book
    ba,bb=Book(pathlib.Path(left).read_bytes()),Book(pathlib.Path(right).read_bytes())
    reasons=[]
    def add(location,old,new,kind):reasons.append(dict(location=location,old=old,new=new,kind=kind))
    with zipfile.ZipFile(left) as a,zipfile.ZipFile(right) as b:
        def read(z,n):return E.fromstring(z.read(n))
        def sheets(z):
            rel={r.get('Id'):r.get('Target') for r in read(z,'xl/_rels/workbook.xml.rels')}
            return {s.get('name'):('xl/'+rel[s.get(R+'id')] if not rel[s.get(R+'id')].startswith('/') else rel[s.get(R+'id')][1:]) for s in read(z,'xl/workbook.xml').find(M+'sheets')}
        sa,sb=sheets(a),sheets(b)
        sheetparts=set(sa.values())|set(sb.values())
        for name in sorted(sa.keys()|sb.keys()):
            if name not in sa or name not in sb:add(name,'存在' if name in sa else '不存在','存在' if name in sb else '不存在','工作表');continue
            x,y=read(a,sa[name]),read(b,sb[name]);cx={c.get('r'):c for c in x.iter(M+'c')};cy={c.get('r'):c for c in y.iter(M+'c')}
            storage=styles=0
            for addr in cx.keys()&cy.keys():
                if cx[addr].get('t','n')!=cy[addr].get('t','n'):
                    storage+=1
                    if storage<=20:
                        labels={'s':'共享字符串','inlineStr':'单元格内字符串','n':'数值','b':'布尔值','str':'公式字符串','e':'错误值'}
                        add(name+'!'+addr,labels.get(cx[addr].get('t','n'),cx[addr].get('t','n')),labels.get(cy[addr].get('t','n'),cy[addr].get('t','n')),'单元格存储类型')
                if ba.style(cx[addr].get('s','0'))!=bb.style(cy[addr].get('s','0')):styles+=1
            if storage>20:add(name,str(storage)+' 处存储类型变化','仅列出前 20 处','存储结构')
            if styles:add(name,'原样式引用',str(styles)+' 处实际样式变化（已忽略编号变化）','样式')
            def structure(n):return [canonical(c) for c in n if c.tag not in (M+'sheetData',M+'dimension')]
            if structure(x)!=structure(y):add(name,'原工作表设置','视图、布局或其他工作表设置变化','工作表设置')
        for n in sorted(set(a.namelist())|set(b.namelist())):
            if n.endswith('/') or n in sheetparts:continue
            if n not in a.namelist() or n not in b.namelist():add(n,'存在' if n in a.namelist() else '不存在','存在' if n in b.namelist() else '不存在','文件组成');continue
            x,y=a.read(n),b.read(n)
            if x==y:continue
            if n.endswith(('.xml','.rels')):
                try:
                    if canonical(E.fromstring(x))==canonical(E.fromstring(y)):continue
                except E.ParseError:pass
            if n=='xl/workbook.xml':
                ca,cb=E.fromstring(x).find(M+'calcPr'),E.fromstring(y).find(M+'calcPr')
                if (ca.attrib if ca is not None else {}) != (cb.attrib if cb is not None else {}):
                    def calculation(c):return '打开时重新计算' if c is not None and c.get('fullCalcOnLoad')=='1' else '其他计算设置：'+str(c.attrib if c is not None else {})
                    add('工作簿计算设置',calculation(ca),calculation(cb),'计算或工作簿设置')
                    wa,wb=E.fromstring(x),E.fromstring(y)
                    for w in (wa,wb):
                        c=w.find(M+'calcPr')
                        if c is not None:w.remove(c)
                    if canonical(wa)==canonical(wb):continue
            kind='样式' if n=='xl/styles.xml' else '计算或工作簿设置' if n=='xl/workbook.xml' else '其他组成部分'
            add(n,'基础版本','内容变化，未计入单元格差异',kind)
        if not reasons and pathlib.Path(left).read_bytes()!=pathlib.Path(right).read_bytes():add('文件封装','原始封装','XML 排版、压缩或条目顺序变化','存储结构')
    return reasons
def stored_last_row(raw):
    """Use persisted row/cell/layout records, never Excel's cached dimension.

    A dimension or whole-column validation alone can describe the infinite grid.
    Explicit empty rows, formatted cells and merged areas are real worksheet layout.
    """
    root=E.fromstring(raw);last=0;implicit_row=0
    def number(value):
        match=re.fullmatch(r'(?:\$?[A-Za-z]{1,3}\$?)?([1-9][0-9]*)',value or '')
        if not match:return 0
        row=int(match[1])
        if row>1048576:raise ValueError('工作表行号超出 Excel 范围')
        return row
    for row in root.iter(M+'row'):
        implicit_row=number(row.get('r')) or implicit_row+1
        last=max(last,implicit_row)
    for cell in root.iter(M+'c'):last=max(last,number(cell.get('r')))
    for merge in root.iter(M+'mergeCell'):
        for address in (merge.get('ref') or '').split(':'):last=max(last,number(address))
    return last

def semantic_cells(path):
    """Use the merge reader for display too: shared strings/formulas and numeric spelling."""
    from workbook_cells import Book,first
    book=Book(pathlib.Path(path).read_bytes());result=[];formats={}
    def text(node):
        if node is None:return ''
        return ''.join(c.nodeValue for c in node.childNodes if c.nodeType in (3,4))
    def visible_text(node):
        if node is None:return ''
        if node.localName=='rPh':return ''
        if node.localName=='t':return text(node)
        return ''.join(visible_text(c) for c in node.childNodes if c.nodeType==c.ELEMENT_NODE)
    for name in book.sheets:
        cells={}
        for address,cell in book.cells(name).items():
            formula=text(first(cell,'f'));kind=cell.getAttribute('t') or 'n'
            if kind=='inlineStr':
                value=visible_text(first(cell,'is'));kind='text'
            else:value=text(first(cell,'v'))
            if value or formula:
                style=cell.getAttribute('s') or '0'
                if style not in formats:
                    formats[style]=hashlib.sha256(json.dumps(book.style(style),ensure_ascii=False).encode()).hexdigest()
                cells[address]=dict(value=value,formula=formula,type=kind,format=formats[style])
        result.append(dict(name=name,cells=cells,lastRow=stored_last_row(book.parts[book.sheets[name][2]])))
    return result
if __name__=='__main__':
    result=semantic_cells(sys.argv[2]) if sys.argv[1]=='--cells' else inspect(sys.argv[1],sys.argv[2])
    print(json.dumps(result,ensure_ascii=False))
