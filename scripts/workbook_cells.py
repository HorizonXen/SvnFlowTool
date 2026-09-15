"""OOXML cell/sheet merge retaining the Release package and translating shared indexes."""
from decimal import Decimal, InvalidOperation
import copy, io, posixpath, zipfile, hashlib, re, functools, bisect
try:
    import workbook_dom as DOM
except ImportError:
    from xml.dom import minidom as DOM

M='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
C='http://schemas.openxmlformats.org/package/2006/content-types'

@functools.lru_cache(maxsize=512)
def expanded_name(name):
    return tuple(name[1:].split('}',1)) if name.startswith('{') else (None,name)

@functools.lru_cache(maxsize=4096)
def leaf_content(tag,text):
    namespace,local=expanded_name(tag)
    return namespace,local,(text,) if text and (local in ('t','v','f') or text.strip()) else ()

def children(n,tag=None):
    if hasattr(n,'e'):
        return [DOM.Node(x) for x in n.e if isinstance(x.tag,str) and (tag is None or x.tag.rsplit('}',1)[-1]==tag)]
    return [x for x in n.childNodes if x.nodeType==x.ELEMENT_NODE and (tag is None or x.localName==tag)]
def first(n,tag):
    if hasattr(n,'e'):
        child=n.e.find('{*}'+tag)
        return DOM.Node(child) if child is not None else None
    return next((x for x in n.childNodes if x.nodeType==x.ELEMENT_NODE and x.localName==tag),None)
def _native_sig(e):
    if not isinstance(e.tag,str):return e.text
    if not len(e) and not e.attrib and (e.text is None or len(e.text)<=256):
        namespace,tag,content=leaf_content(e.tag,e.text)
        return namespace,tag,[],content
    namespace,tag=expanded_name(e.tag)
    attrs=[]
    for name,value in e.attrib.items():
        ns,key=expanded_name(name)
        if ns=='http://www.w3.org/XML/1998/namespace' and key=='space':continue
        if name.startswith('xmlns'):continue
        if namespace==M and tag=='f' and not ns and key=='ca':continue
        attrs.append((ns or '',key,value))
    values=[]
    if e.text and (tag in ('t','v','f') or e.text.strip()):values.append(e.text)
    for child in e:
        values.append(_native_sig(child))
        if child.tail and (tag in ('t','v','f') or child.tail.strip()):values.append(child.tail)
    return namespace,tag,sorted(attrs),tuple(values)

def sig(n):
    if n is None:return None
    if hasattr(n,'e'):return _native_sig(n.e)
    if n.nodeType!=n.ELEMENT_NODE:return n.nodeValue
    attrs=sorted((n.attributes.item(i).namespaceURI or '',n.attributes.item(i).localName,n.attributes.item(i).value) for i in range(n.attributes.length) if not n.attributes.item(i).name.startswith('xmlns') and not (n.attributes.item(i).namespaceURI=='http://www.w3.org/XML/1998/namespace' and n.attributes.item(i).localName=='space') and not (n.namespaceURI==M and n.localName=='f' and not n.attributes.item(i).namespaceURI and n.attributes.item(i).localName=='ca'))
    return (n.namespaceURI,n.localName,attrs,tuple(sig(c) for c in n.childNodes if c.nodeType!=c.TEXT_NODE or n.localName in ('t','v','f') or c.data.strip()))
def number_col(s):
    value=0
    for c in s:value=value*26+ord(c)-64
    return value

def translate(formula,origin,destination):
    a=re.fullmatch(r'([A-Z]+)(\d+)',origin);b=re.fullmatch(r'([A-Z]+)(\d+)',destination)
    dx=number_col(b[1])-number_col(a[1]);dy=int(b[2])-int(a[2])
    def shift(m):
        col=number_col(m[2])+(0 if m[1] else dx);row=int(m[4])+(0 if m[3] else dy)
        if col<1 or row<1:raise ValueError('共享公式引用越界')
        out=''
        while col:col,r=divmod(col-1,26);out=chr(65+r)+out
        return m[1]+out+m[3]+str(row)
    pieces=re.split(r'("(?:[^"]|"")*")',formula)
    for i in range(0,len(pieces),2):pieces[i]=re.sub(r'(?<![A-Za-z0-9_])([$]?)([A-Z]{1,3})([$]?)(\d+)(?![A-Za-z0-9_(])',shift,pieces[i])
    return ''.join(pieces)

class Book:
    def __init__(self,data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:self.parts={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
        if any(n.startswith('_xmlsignatures/') for n in self.parts):raise ValueError('签名工作簿需单独处理')
        self.retain_cells=False;self.cell_cache={};self.signature_cache=None;self.sheet_signatures={};self.phase=None
        self.style_cache={};self.import_cache={};self.merge_style_cache={};self.docs={};self.workbook=self.doc('xl/workbook.xml');self.rels=self.doc('xl/_rels/workbook.xml.rels');self.types=self.doc('[Content_Types].xml')
        self.styles=self.doc('xl/styles.xml') if 'xl/styles.xml' in self.parts else None
        self.strings=children(self.doc('xl/sharedStrings.xml').documentElement,'si') if 'xl/sharedStrings.xml' in self.parts else []
        self.sheets={}
        relations={n.getAttribute('Id'):n for n in children(self.rels.documentElement)}
        for s in self.workbook.getElementsByTagNameNS(M,'sheet'):
            rel=relations[s.getAttributeNS(R,'id')];path=posixpath.normpath(posixpath.join('xl',rel.getAttribute('Target'))).lstrip('/')
            if rel.getAttribute('Target').startswith('/'):path=rel.getAttribute('Target').lstrip('/')
            self.sheets[s.getAttribute('name')]=(s,rel,path)
    def doc(self,path):
        if path not in self.docs:self.docs[path]=DOM.parseString(self.parts[path])
        return self.docs[path]
    def style(self,index):
        index=str(index)
        if index not in self.style_cache:self.style_cache[index]=self._style(index)
        return self.style_cache[index]
    def _style(self,index):
        if self.styles is None:return None
        return self._style_node(children(first(self.styles.documentElement,'cellXfs'))[int(index)])
    def _style_node(self,node):
        groups={n.localName:n for n in children(self.styles.documentElement)}
        x=node.cloneNode(True)
        refs=[]
        for attr,group in [('fontId','fonts'),('fillId','fills'),('borderId','borders')]:
            i=int(x.getAttribute(attr) or '0');refs.append((group,sig(children(groups[group])[i])));x.removeAttribute(attr) if x.hasAttribute(attr) else None
        n=x.getAttribute('numFmtId') or '0'
        custom=next((v.getAttribute('formatCode') for v in children(groups.get('numFmts',self.styles.createElement('empty'))) if v.getAttribute('numFmtId')==n),None)
        if x.hasAttribute('numFmtId'):x.removeAttribute('numFmtId')
        # xfId points to named style inheritance, which may be renumbered on save.
        inheritance=None
        if x.hasAttribute('xfId'):
            i=int(x.getAttribute('xfId'));x.removeAttribute('xfId')
            if 'cellStyleXfs' in groups:inheritance=self._style_node(children(groups['cellStyleXfs'])[i])
        return (sig(x),tuple(refs),custom or n,inheritance)
    def cells(self,name):
        if self.retain_cells and name in self.cell_cache:return self.cell_cache[name]
        if hasattr(self.doc(self.sheets[name][2]),'e'):return self._native_cells(name)
        doc=self.doc(self.sheets[name][2]);result={};shared={}
        nodes=doc.getElementsByTagNameNS(M,'c')
        for c in nodes:
            f=first(c,'f')
            if f is not None and f.getAttribute('t')=='shared' and f.firstChild:shared[f.getAttribute('si')]=(c.getAttribute('r'),f.firstChild.nodeValue)
        for position,c in enumerate(nodes):
            if self.phase and position%10000==0:self.phase('解析工作表 '+name+' · '+str(position)+' 个单元格')
            f=first(c,'f')
            n=c.cloneNode(True) if c.getAttribute('t')=='s' or (f is not None and f.getAttribute('t')=='shared') else c
            address=n.getAttribute('r')
            if n.getAttribute('t')=='s':
                v=first(n,'v')
                if v is None or v.firstChild is None:
                    n.removeAttribute('t')
                    if v is not None:n.removeChild(v)
                else:
                    idx=int(v.firstChild.nodeValue);n.removeChild(v);n.setAttribute('t','inlineStr')
                    inline=doc.createElementNS(M,'is')
                    for child in self.strings[idx].childNodes:inline.appendChild(child.cloneNode(True))
                    n.appendChild(inline)
            inline=first(n,'is')
            if inline is not None and not inline.getElementsByTagNameNS(M,'rPh') and first(inline,'phoneticPr') is not None:
                # An unused phonetic font index is save metadata, not visible text.
                n=n.cloneNode(True);inline=first(n,'is')
                for metadata in list(children(inline,'phoneticPr')):inline.removeChild(metadata)
            f=first(n,'f')
            if f is not None and f.getAttribute('t')=='shared':
                origin,formula=shared[f.getAttribute('si')]
                for attr in ('t','si','ref'):
                    if f.hasAttribute(attr):f.removeAttribute(attr)
                while f.firstChild:f.removeChild(f.firstChild)
                f.appendChild(doc.createTextNode(translate(formula,origin,address)))
            # Normalize numeric storage without rounding long integer IDs.
            if n.getAttribute('t') in ('','n') and first(n,'f') is None:
                v=first(n,'v');canonical=None
                if v is not None and v.firstChild:
                    try:
                        number=Decimal(v.firstChild.nodeValue)
                        if number.is_finite():
                            canonical=format(number,'f') if number else '0'
                            if '.' in canonical:canonical=canonical.rstrip('0').rstrip('.')
                    except InvalidOperation:pass
                if n.getAttribute('t')=='n' or (canonical is not None and canonical!=v.firstChild.nodeValue):
                    n=n.cloneNode(True)
                    if n.hasAttribute('t'):n.removeAttribute('t')
                    if canonical is not None:
                        v=first(n,'v')
                        while v.firstChild:v.removeChild(v.firstChild)
                        v.appendChild(doc.createTextNode(canonical))
            result[address]=n
        if self.retain_cells:self.cell_cache[name]=result
        return result
    def _native_cells(self,name):
        """The same normalization as cells(), directly on the native XML tree.

        Only changed cells are copied. Source XML remains immutable; normalized
        strings/formulas/numbers are cached separately for subsequent passes.
        """
        doc=self.doc(self.sheets[name][2]);nodes=list(doc.e.iter('{'+M+'}c'))
        result={};shared={};strings={}
        def value(node):
            if node is None:return None
            if node.text:return node.text
            child=DOM.Node(node).firstChild
            return child.nodeValue if child is not None else None
        for c in nodes:
            f=c.find('{*}f')
            if f is not None and f.get('t')=='shared' and (f.text or len(f)):
                shared[f.get('si','')]=(c.get('r',''),value(f))
        for position,c in enumerate(nodes):
            if self.phase and position%10000==0:self.phase('解析工作表 '+name+' · '+str(position)+' 个单元格')
            f=c.find('{*}f')
            n=copy.deepcopy(c) if c.get('t')=='s' or (f is not None and f.get('t')=='shared') else c
            address=n.get('r','')
            if n.get('t')=='s':
                v=n.find('{*}v');text=value(v)
                if v is None or not (v.text or len(v)):
                    n.attrib.pop('t',None)
                    if v is not None:n.remove(v)
                else:
                    index=int(text);n.remove(v);n.set('t','inlineStr')
                    if index not in strings:
                        inline=doc.createElementNS(M,'is')
                        for child in self.strings[index].childNodes:inline.appendChild(child.cloneNode(True))
                        strings[index]=inline.e
                    n.append(copy.deepcopy(strings[index]))
            inline=n.find('{*}is')
            if inline is not None and not any(True for _ in inline.iter('{'+M+'}rPh')) and inline.find('{*}phoneticPr') is not None:
                n=copy.deepcopy(n);inline=n.find('{*}is')
                for metadata in list(inline):
                    if isinstance(metadata.tag,str) and metadata.tag.rsplit('}',1)[-1]=='phoneticPr':inline.remove(metadata)
            f=n.find('{*}f')
            if f is not None and f.get('t')=='shared':
                origin,formula=shared[f.get('si','')]
                for attr in ('t','si','ref'):f.attrib.pop(attr,None)
                f.text=None
                for child in list(f):f.remove(child)
                f.text=translate(formula,origin,address)
            if n.get('t','') in ('','n') and f is None:
                v=n.find('{*}v');canonical=None;text=value(v)
                if v is not None and (v.text or len(v)):
                    try:
                        number=Decimal(text)
                        if number.is_finite():
                            canonical=format(number,'f') if number else '0'
                            if '.' in canonical:canonical=canonical.rstrip('0').rstrip('.')
                    except InvalidOperation:pass
                if n.get('t')=='n' or (canonical is not None and canonical!=text):
                    n=copy.deepcopy(n);n.attrib.pop('t',None)
                    if canonical is not None:
                        v=n.find('{*}v')
                        for child in list(v):v.remove(child)
                        v.text=canonical
            result[address]=DOM.Node(n)
        if self.retain_cells:self.cell_cache[name]=result
        return result
    def cell_value(self,cell):
        if cell is None:return None
        if hasattr(cell,'e'):
            e=cell.e
            namespace,tag=expanded_name(e.tag);attrs=[]
            formula=any(isinstance(c.tag,str) and c.tag.rsplit('}',1)[-1]=='f' for c in e)
            for name,value in e.attrib.items():
                ns,key=expanded_name(name)
                if name=='s' or name.startswith('xmlns') or (formula and key=='t'):continue
                attrs.append((ns or '',key,value))
            content=[]
            if e.text and e.text.strip():content.append(e.text)
            for child in e:
                if not (formula and isinstance(child.tag,str) and child.tag.rsplit('}',1)[-1]=='v'):content.append(_native_sig(child))
                if child.tail and child.tail.strip():content.append(child.tail)
            return ((namespace,tag,sorted(attrs),tuple(content)),self.style(e.get('s','0')))
        style=self.style(cell.getAttribute('s') or '0')
        attrs=sorted((cell.attributes.item(i).namespaceURI or '',cell.attributes.item(i).localName,cell.attributes.item(i).value) for i in range(cell.attributes.length) if cell.attributes.item(i).name!='s' and not cell.attributes.item(i).name.startswith('xmlns'))
        formula=first(cell,'f') is not None
        if formula:attrs=[v for v in attrs if v[1]!='t']
        content=tuple(sig(n) for n in cell.childNodes if (n.nodeType!=n.TEXT_NODE or n.data.strip()) and not (formula and n.nodeType==n.ELEMENT_NODE and n.localName=='v'))
        return ((cell.namespaceURI,cell.localName,attrs,content),style)
    def import_style(self,source,index):
        key=(id(source),str(index))
        if key not in self.import_cache:self.import_cache[key]=self._import_style(source,index)
        return self.import_cache[key]
    def _import_style(self,source,index):
        if self.styles is None or source.styles is None:
            if self.styles is not source.styles:raise ValueError('缺少样式表')
            return index
        target_groups={n.localName:n for n in children(self.styles.documentElement)};source_groups={n.localName:n for n in children(source.styles.documentElement)}
        def append(group,node):
            if group not in target_groups:
                target_groups[group]=self.styles.createElementNS(M,group)
                order=['numFmts','fonts','fills','borders','cellStyleXfs','cellXfs','cellStyles','dxfs','tableStyles','colors','extLst']
                following=next((n for n in children(self.styles.documentElement) if n.localName in order and order.index(n.localName)>order.index(group)),None)
                self.styles.documentElement.insertBefore(target_groups[group],following)
            parent=target_groups[group];items=children(parent)
            for i,item in enumerate(items):
                if sig(item)==sig(node):return i
            parent.appendChild(self.styles.importNode(node,True));parent.setAttribute('count',str(len(items)+1));return len(items)
        def xf(node):
            node=node.cloneNode(True)
            for attr,group in [('fontId','fonts'),('fillId','fills'),('borderId','borders')]:
                if node.hasAttribute(attr):node.setAttribute(attr,str(append(group,children(source_groups[group])[int(node.getAttribute(attr))])))
            n=node.getAttribute('numFmtId')
            custom=next((v for v in children(source_groups.get('numFmts',source.styles.createElement('empty'))) if v.getAttribute('numFmtId')==n),None)
            if custom is not None:
                items=children(target_groups.get('numFmts',self.styles.createElement('empty')));found=next((v for v in items if v.getAttribute('formatCode')==custom.getAttribute('formatCode')),None)
                if found is None:
                    found=custom.cloneNode(True);found.setAttribute('numFmtId',str(max([163]+[int(v.getAttribute('numFmtId')) for v in items])+1));append('numFmts',found)
                node.setAttribute('numFmtId',found.getAttribute('numFmtId'))
            return node
        node=xf(children(source_groups['cellXfs'])[int(index)])
        if node.hasAttribute('xfId'):
            node.setAttribute('xfId',str(append('cellStyleXfs',xf(children(source_groups['cellStyleXfs'])[int(node.getAttribute('xfId'))]))))
        return str(append('cellXfs',node))
    def release_sheet(self,name,save=False):
        self.cell_cache.pop(name,None)
        if name not in self.sheets:return
        path=self.sheets[name][2]
        doc=self.docs.pop(path,None)
        if doc is not None:
            if save:
                if hasattr(doc,'e'):
                    from workbook_sparse import prune
                    prune(doc.e)
                self.parts[path]=doc.toxml(encoding='utf-8')
            doc.unlink()
    def merge_style(self, before, after, ai, bi, ti):
        """Translate indexes, then apply authored style properties to Release."""
        key=(id(before),id(after),str(ai),str(bi),str(ti))
        if key not in self.merge_style_cache:
            self.merge_style_cache[key]=self._merge_style(before,after,ai,bi,ti)
        return self.merge_style_cache[key]
    def _merge_style(self, before, after, ai, bi, ti):
        if self.styles is None or before.styles is None or after.styles is None:
            raise ValueError('缺少样式表，无法解析作者修改的样式项')
        ai=self.import_style(before,ai);bi=self.import_style(after,bi)
        groups={n.localName:n for n in children(self.styles.documentElement)}
        xfs=children(groups['cellXfs'])
        a,b,t=[xfs[int(i)] for i in (ai,bi,ti)]
        # Font/fill/border indexes are references, not author-owned values.
        # Merge their XML properties before merging the remaining xf settings.
        a,b,t=[n.cloneNode(True) for n in (a,b,t)]
        resolved={}
        for attr,group in [('fontId','fonts'),('fillId','fills'),('borderId','borders'),('xfId','cellStyleXfs')]:
            if group not in groups:continue
            nodes=children(groups[group])
            av,bv,tv=[nodes[int(n.getAttribute(attr) or '0')] for n in (a,b,t)]
            if attr=='xfId':
                # Inherited style references are already translated by import_style.
                # Direct inherited style changes require the same component merge.
                merged=self._merge_inherited_style(av,bv,tv,groups)
            else:merged=merge_structure(av,bv,tv,True,allow_missing=True)
            resolved[attr]=self._append_style(group,merged)
            for n in (a,b,t):
                if n.hasAttribute(attr):n.removeAttribute(attr)
        result=merge_structure(a,b,t,True,allow_missing=True)
        for attr,index in resolved.items():result.setAttribute(attr,str(index))
        return str(self._append_style('cellXfs',result))
    def _merge_inherited_style(self,a,b,t,groups):
        a,b,t=[n.cloneNode(True) for n in (a,b,t)]
        resolved={}
        for attr,group in [('fontId','fonts'),('fillId','fills'),('borderId','borders')]:
            nodes=children(groups[group])
            values=[nodes[int(n.getAttribute(attr) or '0')] for n in (a,b,t)]
            resolved[attr]=self._append_style(group,merge_structure(*values,True,allow_missing=True))
            for n in (a,b,t):
                if n.hasAttribute(attr):n.removeAttribute(attr)
        result=merge_structure(a,b,t,True,allow_missing=True)
        for attr,index in resolved.items():result.setAttribute(attr,str(index))
        return result
    def _append_style(self,group,node):
        parent=first(self.styles.documentElement,group);items=children(parent)
        for i,item in enumerate(items):
            if sig(item)==sig(node):return i
        parent.appendChild(self.styles.importNode(node,True));parent.setAttribute('count',str(len(items)+1))
        return len(items)
    def save(self):
        for name,doc in self.docs.items():
            if name.startswith('xl/worksheets/') and hasattr(doc,'e'):
                from workbook_sparse import prune
                prune(doc.e)
            self.parts[name]=doc.toxml(encoding='utf-8')
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            # ZIP timestamps must not give identical internal projections a
            # different content identity on every pass.
            for n,v in self.parts.items():
                entry=zipfile.ZipInfo(n,date_time=(1980,1,1,0,0,0))
                entry.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(entry,v)
        return out.getvalue()

def cached_formula_value(cell):
    """Freeze the workbook's own saved result, without importing a Dev value."""
    if cell is None or first(cell,'f') is None:return cell
    f=first(cell,'f');address=cell.getAttribute('r')
    if (f.hasAttribute('t') or f.hasAttribute('ref')) and not (
        f.getAttribute('t')=='array' and f.getAttribute('ref').replace('$','')==address):
        raise ValueError(address+' 数组或跨单元格公式需要核对完整依赖')
    value=first(cell,'v');kind=cell.getAttribute('t')
    if value is None or (not value.firstChild and kind!='str'):
        raise ValueError(address+' 公式没有已保存的计算结果，请在 Excel 中重新计算并保存后重试')
    result=cell.cloneNode(True);result.removeChild(first(result,'f'))
    document=DOM.Document(result.e) if hasattr(result,'e') else result.ownerDocument
    # Cell metadata belongs to the formula (e.g. a dynamic array), not its value.
    if result.hasAttribute('cm'):result.removeAttribute('cm')
    value=first(result,'v')
    if kind=='str':
        content=''.join(n.nodeValue for n in value.childNodes if n.nodeType in (3,4))
        result.removeChild(value);result.setAttribute('t','inlineStr')
        inline=document.createElementNS(M,'is');text=document.createElementNS(M,'t')
        if content!=content.strip():text.setAttributeNS('http://www.w3.org/XML/1998/namespace','xml:space','preserve')
        text.appendChild(document.createTextNode(content));inline.appendChild(text);result.appendChild(inline)
    elif kind in ('','n'):
        try:
            number=Decimal(value.firstChild.nodeValue)
            if not number.is_finite():raise InvalidOperation
            content=format(number,'f') if number else '0'
            if '.' in content:content=content.rstrip('0').rstrip('.')
        except InvalidOperation:raise ValueError(address+' 公式的已保存数值无效')
        if result.hasAttribute('t'):result.removeAttribute('t')
        while value.firstChild:value.removeChild(value.firstChild)
        value.appendChild(document.createTextNode(content))
    elif kind not in ('b','e'):
        raise ValueError(address+' 公式计算结果类型无法转值：'+kind)
    return result

def formula_to_literal(before,after):
    return (before is not None and after is not None and first(before,'f') is not None
            and first(after,'f') is None and (first(after,'v') is not None or first(after,'is') is not None))

def merge_cell_content(a, b, t, history=(), prefer_source=False, *, document, scope_projection=False):
    """Apply only authored cell components; never import unchanged Dev context."""
    if prefer_source and formula_to_literal(a,b):
        a=cached_formula_value(a);t=cached_formula_value(t)
    def attrs(node):
        return {(n.namespaceURI, n.name): n.value for n in (node.attributes.item(i) for i in range(node.attributes.length))
                if n.name not in ('r', 's', 't') and not n.name.startswith('xmlns')}
    def elements(node, names): return tuple(sig(c) for c in children(node) if c.localName in names) if node is not None else None
    def value(node):
        if node is None:return None
        if first(node,'f') is not None:return ('formula-cache',)
        return (node.getAttribute('t'), elements(node, ('v','is')))
    def formula(node): return elements(node, ('f',))
    def choose(av, bv, tv, hv, label):
        if tv == bv: return False
        if av == bv and not any(tv == h and h != bv for h in hv): return False
        if tv != av and tv not in hv and not prefer_source: raise ValueError('单元格' + label + '冲突，无法隔离作者改动')
        return True
    value_changed = choose(value(a), value(b), value(t), [value(h) for h in history], '数值')
    formula_changed = choose(formula(a), formula(b), formula(t), [formula(h) for h in history], '公式')
    if value_changed and not prefer_source and a.getAttribute('t') == b.getAttribute('t') != t.getAttribute('t'):
        raise ValueError('单元格数值依赖不同的数据类型，不能带入未修改的源分支类型')
    if value_changed and formula(a) and formula(a) == formula(b):
        if prefer_source:value_changed=False # A recalculated cache is not an authored formula edit.
        else:raise ValueError('单元格缓存值依赖不同的公式，不能带入未修改的源分支公式')
    merged_text = None
    if value_changed and not prefer_source and all(node.getAttribute('t') == 'inlineStr' for node in (a,b,t)):
        def plain(node):
            if node is None or node.getAttribute('t') != 'inlineStr': return None
            inline=first(node,'is')
            if inline is None or len(children(inline)) != 1 or children(inline)[0].localName != 't': return None
            text=children(inline)[0]
            if any(c.nodeType not in (3,4) for c in text.childNodes): return None
            return ''.join(c.nodeValue for c in text.childNodes)
        strings=[plain(node) for node in (a,b,t)]
        if all(text is not None for text in strings):
            from file_sync import merge_text
            merged_text=merge_text(*(text.encode() for text in strings),latest=prefer_source,
                                   history=[plain(h).encode() for h in history if plain(h) is not None]).decode()
        elif value(t) != value(a) and value(t) not in [value(h) for h in history]:
            raise ValueError('富文本单元格存在交叉修改，无法隔离其他作者的内容或格式')
    merged_formula = None
    if formula_changed:
        # Pasting a value over a single-cell array removes its entire scope.
        # Multi-cell arrays (including a different Release scope) stay blocked.
        def single_array(node):
            f=first(node,'f')
            return f is not None and f.getAttribute('t')=='array' and f.getAttribute('ref').replace('$','')==node.getAttribute('r')
        removes_single_array=first(b,'f') is None and single_array(a)
        for node in (a,b,t):
            for f in children(node,'f'):
                if not (f.hasAttribute('t') or f.hasAttribute('ref')):continue
                if removes_single_array and node is not b and single_array(node):continue
                # A Dev-only scope mask may restore a previously frozen
                # single-cell array. The mask is never written to Release.
                if scope_projection and single_array(node):continue
                raise ValueError('数组或跨单元格公式需要核对完整依赖')
        formulas=[first(node,'f') for node in (a,b,t)]
        if not prefer_source and formulas[0] is not None and formulas[1] is not None and formulas[2] is None:
            raise ValueError('Release 缺少已有公式，不能带入未修改的源分支引用')
        if not prefer_source and all(node is not None for node in formulas):
            if attrs(formulas[0]) != attrs(formulas[1]): raise ValueError('公式属性发生变化，需要核对依赖')
            def formula_text(node):
                if any(c.nodeType not in (3,4) for c in node.childNodes): raise ValueError('公式结构无法隔离')
                return ''.join(c.nodeValue for c in node.childNodes)
            strings=[formula_text(node) for node in formulas]
            from file_sync import merge_text
            merged_formula=merge_text(*(text.encode() for text in strings),latest=prefer_source,
                history=[formula_text(first(h,'f')).encode() for h in history if h is not None and first(h,'f') is not None]).decode()
            if value_changed and merged_formula != strings[1]:
                raise ValueError('公式含 Release 独有修改，源分支缓存值不能直接迁移')
    result = t.cloneNode(True)
    aa,bb,tt = map(attrs,(a,b,t)); hh=[attrs(h) if h is not None else {} for h in history]
    for key in set(aa)|set(bb)|{key for h in hh for key in h}:
        if not choose(aa.get(key),bb.get(key),tt.get(key),[h.get(key) for h in hh],'属性'): continue
        namespace,name = key
        # Clearing an authored metadata reference needs no cross-package remap.
        # New/replaced references still cannot use a Dev-owned metadata index.
        if name in ('cm','vm') and key in bb:
            bf=first(b,'f')
            if scope_projection and name=='cm' and bf is not None and bf.getAttribute('t')=='array' and bf.getAttribute('ref').replace('$','')==b.getAttribute('r'):
                # Formula identity supplies the temporary mask; restoring a
                # foreign metadata index is unnecessary and could be invalid.
                continue
            raise ValueError('单元格元数据依赖无法隔离')
        if key in bb:
            if namespace: result.setAttributeNS(namespace,name,bb[key])
            else: result.setAttribute(name,bb[key])
        elif result.hasAttribute(name): result.removeAttribute(name)
    def replace(names):
        for node in list(children(result)):
            if node.localName in names: result.removeChild(node)
        order={'f':0,'v':1,'is':1,'extLst':2}
        for node in children(b):
            if node.localName not in names: continue
            following=next((v for v in children(result) if order.get(v.localName,2)>order.get(node.localName,2)),None)
            result.insertBefore(node.cloneNode(True),following)
    if value_changed:
        if b.hasAttribute('t'): result.setAttribute('t',b.getAttribute('t'))
        elif result.hasAttribute('t'): result.removeAttribute('t')
        replace(('v','is'))
        if merged_text is not None:
            # Keep the target's text container; only the author's text delta
            # is applied, including when both branches use shared strings.
            inline=first(t,'is').cloneNode(True)
            result.replaceChild(inline,first(result,'is')); text=first(inline,'t')
            while text.firstChild: text.removeChild(text.firstChild)
            text.appendChild(document.createTextNode(merged_text))
    if formula_changed:
        replace(('f',))
        if merged_formula is not None:
            formula_node=first(t,'f').cloneNode(True)
            result.replaceChild(formula_node,first(result,'f'))
            while formula_node.firstChild: formula_node.removeChild(formula_node.firstChild)
            formula_node.appendChild(document.createTextNode(merged_formula))
    other={n.localName for node in (a,b,t) for n in children(node)}-{'f','v','is'}
    for name in other:
        if choose(elements(a,(name,)),elements(b,(name,)),elements(t,(name,)),[elements(h,(name,)) for h in history],name):
            raise ValueError('单元格扩展内容无法隔离：'+name)
    return result

def config_cell_text(cell):
    if cell is None:return ''
    if hasattr(cell,'e'):
        # Match DOM child text (including tails), without wrapping every node.
        return ''.join(value for tag in ('v','t') for node in cell.e.iter('{'+M+'}'+tag)
                       for value in (node.text, *(child.tail for child in node)) if value)
    return ''.join(n.nodeValue for tag in ('v','t') for node in cell.getElementsByTagNameNS(M,tag) for n in node.childNodes if n.nodeType==3)
def config_layout(cells):
    text = config_cell_text
    rows={}
    for address,cell in cells.items():
        rows.setdefault(int(re.search(r'\d+',address)[0]),{})[re.match(r'[A-Z]+',address)[0]]=cell
    declaration=next((number for number,row in sorted(rows.items()) if any(re.fullmatch(r'\*{1,2}[A-Za-z_][A-Za-z_0-9]*',text(c)) for c in row.values())),None)
    if declaration is None:return None
    header={col:text(cell) for col,cell in rows[declaration].items()}
    # Metadata is recognized by content, not by assuming rows 3/4/5.
    meta={n:n-declaration for n in rows if n<=declaration}
    for number,row in sorted(rows.items()):
        if number<=declaration:continue
        values=[text(c) for c in row.values() if text(c)]
        if not values:continue
        types=all(re.fullmatch(r'(?:int|long|float|double|bool|boolean|string|enum[.,][A-Za-z_0-9.]+|~)(?:\[\])?',v,re.I) for v in values)
        keycols=[col for col,v in header.items() if v.startswith('*')]
        scopes=all(not text(row.get(col)) for col in keycols) and all(v in ('client','server','all','both') for v in values)
        directives=all(not text(row.get(col)) for col in keycols) and all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=.+',v) for v in values)
        if types or scopes or directives:meta[number]=number-declaration
        else:break
    return header,rows,meta

def empty_config_cell(cell):
    """Empty storage includes unformatted empty runs, never formulas or metadata."""
    if cell is None:return True
    if hasattr(cell,'e'):
        def native(node,tag):
            if node.tag!='{'+M+'}'+tag:return False
            allowed=('r','s','t') if tag=='c' else ()
            if any(key not in allowed and key!='{http://www.w3.org/XML/1998/namespace}space'
                   and not key.startswith('xmlns') for key in node.attrib):return False
            if tag=='c' and node.get('t','') not in ('','n','str','inlineStr'):return False
            if node.text and (tag in ('v','t') or node.text.strip()):return False
            permitted=('v','is') if tag=='c' else ('t','r') if tag=='is' else ('t',) if tag=='r' else ()
            for child in node:
                if not isinstance(child.tag,str):
                    if child.text:return False
                else:
                    local=expanded_name(child.tag)[1]
                    if local not in permitted or not native(child,local):return False
                if child.tail and (tag in ('v','t') or child.tail.strip()):return False
            return True
        return native(cell.e,'c')
    def empty(node,tag):
        namespace,name,attrs,content=sig(node)
        if namespace!=M or name!=tag:return False
        allowed={'c':{'r','s','t'},'v':set(),'is':set(),'t':set(),'r':set()}[tag]
        if any(ns or key not in allowed for ns,key,value in attrs):return False
        if tag=='c' and node.getAttribute('t') not in ('','n','str','inlineStr'):return False
        permitted={'c':{'v','is'},'is':{'t','r'},'r':{'t'},'v':set(),'t':set()}[tag]
        if any(isinstance(value,str) and value for value in content):return False
        return all(child.localName in permitted and empty(child,child.localName) for child in children(node))
    return empty(cell,'c')

def align_config_cells(a,b,t,ac,bc,tc):
    """Discover declared keys and match records/fields independently of row numbers."""
    # Sheet layout can change without any cell edit. No record identity is
    # needed to apply an empty cell delta, even on a sheet with duplicate IDs.
    if ac.keys()==bc.keys() and all(a.cell_value(ac[key])==b.cell_value(bc[key]) for key in ac):
        return ac,bc
    text = config_cell_text
    layout = config_layout
    layouts=[layout(c) for c in (ac,bc,tc)]
    if layouts[0] is None:
        if layouts[1] is not None:raise ValueError('新增主键声明，需要核对表结构')
        return ac,bc
    if any(v is None for v in layouts):raise ValueError('配置表主键声明缺失，不能按行号合入')
    (ah,all_a,am),(bh,all_b,bm),(th,all_t,tm)=layouts
    keys=[v for v in ah.values() if v.startswith('*')]
    if len(set(keys))!=len(keys) or any(list(h.values()).count(key)!=1 for key in keys for h in (ah,bh,th)):
        raise ValueError('配置表主键声明缺失或不唯一，不能按行号合入')
    def records(rows,header,meta):
        cols=[next(k for k,v in header.items() if v==key) for key in keys];ids={}
        for number,row in rows.items():
            if number in meta:continue
            key=tuple(text(row.get(col)) for col in cols)
            if not all(key):continue
            if key in ids:raise ValueError('配置 ID 重复：'+str(key)+'（第 '+str(ids[key][0])+'、'+str(number)+' 行）')
            ids[key]=(number,row)
        return ids
    ar,br,tr=[records(rows,h,meta) for h,rows,meta in layouts]
    def normalize(cell,address):
        # Aligned source cells are read-only; the actual write imports a copy.
        # Keep cloning when relocating, including single-cell array references.
        if cell.getAttribute('r')==address:
            f=first(cell,'f')
            if f is None or f.getAttribute('t')!='array' or f.getAttribute('ref').replace('$','')!=address or f.getAttribute('ref')==address:
                return cell
        n=cell.cloneNode(True)
        f=first(n,'f')
        if f is not None and f.getAttribute('t')=='array' and f.getAttribute('ref').replace('$','')==cell.getAttribute('r'):
            f.setAttribute('ref',address)
        n.setAttribute('r',address);return n
    def formula(cell):return first(cell,'f') if cell is not None else None
    def row_value(book,row):return {col:book.cell_value(normalize(cell,col+'1')) for col,cell in row.items()}
    def row_content(book,row):return {col:value[0] for col,value in row_value(book,row).items()}
    def unchanged_after_freeze(left,right):
        normalized={col:cached_formula_value(cell) if formula_to_literal(cell,right.get(col)) else cell for col,cell in left.items()}
        # Storage-only blanks do not make an otherwise untouched ID an edit.
        av,bv=[row_content(book,{col:cell for col,cell in row.items() if not empty_config_cell(cell)})
               for book,row in ((a,normalized),(b,right))]
        if av==bv:return True
        if ah!=bh:return False
        # This predicate is used only for an existing source ID absent from
        # the target. Clearing undeclared scratch columns does not require
        # creating that otherwise unchanged business record in Release.
        for col in set(av)|set(bv):
            if av.get(col)==bv.get(col):continue
            if ah.get(col) or bh.get(col):return False
            cell=right.get(col)
            if cell is not None and (text(cell) or formula(cell) is not None):
                # Copying an existing annotation into another undeclared
                # column does not introduce a business-record dependency.
                # Only exempt a previously empty cell containing plain text
                # identical to an unchanged undeclared peer on this exact ID.
                # New notes, formulas and declared-field edits still require
                # a target record; never manufacture a missing Release row.
                old=left.get(col)
                duplicated=(formula(cell) is None and cell.getAttribute('t') in ('s','inlineStr')
                    and (old is None or (not text(old) and formula(old) is None))
                    and any(peer!=col and not ah.get(peer) and not bh.get(peer)
                        and peer in av and av[peer]==bv.get(peer)
                        and formula(peer_cell) is None and text(peer_cell)==text(cell)
                        for peer,peer_cell in right.items()))
                if not duplicated:return False
        return True
    def keyless_content(book,row):
        # Excel/WPS may rewrite styles and materialize empty cells on save.
        # Those cells carry no record data and must not require an ID.
        return row_content(book,{col:cell for col,cell in row.items() if text(cell) or formula(cell) is not None})
    def has_key(row,header):
        return all(text(row.get(next(k for k,v in header.items() if v==key))) for key in keys)
    absent_keyless_deletions=None
    # A cleared auxiliary row can be identified by its complete content only
    # when it occurs exactly once in both source and target. Never search keyed
    # business records, guess a physical row, or use a partial value match.
    from collections import defaultdict
    def keyless_index(book,header,rows,meta):
        result=defaultdict(list)
        for number,row in rows.items():
            if number in meta or has_key(row,header):continue
            content=keyless_content(book,row)
            if content:result[repr(sorted(content.items()))].append((number,row))
        return result
    source_keyless=keyless_index(a,ah,all_a,am)
    target_keyless=keyless_index(t,th,all_t,tm)
    projection=getattr(t,'scope_projection',False)
    after_keyless=keyless_index(b,bh,all_b,bm) if projection else {}
    def deletions_already_absent():
        # Only prove absence when every remaining keyless Release row is
        # unchanged source context. An unknown/edited Release row is ambiguous.
        # Compare fields and content, never physical row numbers or styles.
        from collections import Counter
        def signatures(book,header,rows,meta):
            result=Counter()
            if len(set(header.values()))!=len(header) and not ah==bh==th:return None
            for number,row in rows.items():
                if number in meta or has_key(row,header):continue
                content=keyless_content(book,row)
                if content:
                    fields=[]
                    for col,value in content.items():
                        field=header[col] if header.get(col) and list(header.values()).count(header[col])==1 else col
                        fields.append((field,repr(value)))
                    result[tuple(sorted(fields))]+=1
            return result
        left,right,target=[signatures(book,*layout) for book,layout in zip((a,b,t),layouts)]
        return all(v is not None for v in (left,right,target)) and not (target-(left & right))
    # Ignore formatting-only changes outside records, but refuse real data edits.
    for number in set(all_a)|set(all_b):
        if number in am and number in bm:continue
        aa=all_a.get(number,{});bb=all_b.get(number,{})
        if not has_key(aa,ah) and not has_key(bb,bh) and keyless_content(a,aa)!=keyless_content(b,bb):
            left,right=keyless_content(a,aa),keyless_content(b,bb)
            if projection:
                # A scope mask must not invent record identity for a blank
                # separator merely because paste-values removed its formulas.
                # Compare only actual formula/literal pairs with their saved
                # values; two edited formulas are never reduced to caches.
                frozen_a={col:cached_formula_value(cell) if formula_to_literal(cell,bb.get(col)) else cell for col,cell in aa.items()}
                frozen_b={col:cached_formula_value(cell) if formula_to_literal(cell,aa.get(col)) else cell for col,cell in bb.items()}
                if keyless_content(a,frozen_a)==keyless_content(b,frozen_b):continue
            if projection and not left and right:
                # This only builds an in-memory Dev scope mask. Restoring an
                # exact, unique auxiliary block here makes its final absence a
                # deletion patch; actual Release merging still requires the
                # existing complete-content match, never a physical row guess.
                signature=repr(sorted(right.items()))
                if ah==bh==th and all(not bh.get(col) for col in right) and len(after_keyless[signature])==1 and not target_keyless.get(signature) and not any(formula(cell) is not None for cell in bb.values()):
                    key=('__scope_auxiliary__',number)
                    br[key]=(number,bb)
                    continue
            if left and not right:
                if absent_keyless_deletions is None:absent_keyless_deletions=deletions_already_absent()
                if absent_keyless_deletions:continue
                signature=repr(sorted(left.items()))
                matches=target_keyless.get(signature,[])
                # Undeclared auxiliary columns have no field identity. Require
                # the entire declaration to agree, including blank columns.
                if ah==bh==th and all(not ah.get(col) for col in left) and len(source_keyless[signature])==len(matches)==1 and not any(formula(cell) is not None for cell in aa.values()):
                    key=('__cleared_auxiliary__',number)
                    ar[key]=(number,aa);br[key]=(number,bb);tr[key]=matches[0]
                    continue
            changed=[col+str(number) for col in sorted(set(left)|set(right),key=number_col) if left.get(col)!=right.get(col)]
            raise ValueError('第 '+str(number)+' 行缺少配置 ID；实际变化位置 '+', '.join(changed[:8])+'，无法匹配 Release 记录；未按行号覆盖')
    # Match recognized metadata relative to the declaration, then by field.
    for mapping,rows,meta in ((ar,all_a,am),(br,all_b,bm),(tr,all_t,tm)):
        for number,role in meta.items():mapping[('__header__',role)]=(number,rows[number])
    out_a={};out_b={}
    # Resolve field names once per header, rather than scanning both headers
    # for every cell in every record. Duplicate/ambiguous fields stay blocked.
    def field_columns(header):
        result={}
        for col,field in header.items():result.setdefault(field,[]).append(col)
        return result
    target_fields=field_columns(th)
    source_fields={id(header):field_columns(header) for header in (ah,bh)}
    column_maps={}
    for header in (ah,bh):
        mapping={}
        for col,field in header.items():
            matches=target_fields.get(field,[]) if field else []
            if field and len(matches)==1 and len(source_fields[id(header)][field])==1:mapping[col]=matches[0]
            elif header.get(col)==th.get(col):mapping[col]=col
        column_maps[id(header)]=mapping
    next_row=max([5]+[number for number,row in all_t.items() if any(text(cell) or formula(cell) is not None for cell in row.values())])+1
    for key in dict.fromkeys([*ar,*br]):
        av=ar.get(key);bv=br.get(key);tv=tr.get(key)
        if tv is None:
            if bv is None:continue
            if av is not None:
                if unchanged_after_freeze(av[1],bv[1]):continue
                if projection and key[0] not in ('__header__','__cleared_auxiliary__','__scope_auxiliary__'):
                    # The keyed record was deleted later in Dev. Restore it
                    # only in the scope mask so the final patch deletes that
                    # exact ID from Release without touching adjacent records.
                    av=None
                else:raise ValueError('Release 缺少配置 ID '+str(key)+'，不能覆盖同一行的其他记录')
            if next_row>1048576:raise ValueError("新增记录超过 Excel 最大行数")
            row=next_row;next_row+=1
        else:row=tv[0]
        for record,header,out in ((av,ah,out_a),(bv,bh,out_b)):
            if record is None:continue
            for col,cell in record[1].items():
                field=header.get(col,'')
                target_col=column_maps[id(header)].get(col)
                if target_col is None and header.get(col)==th.get(col):target_col=col
                if target_col is None:
                    def field_cell(record,fields):
                        if record is None:return None
                        cols=[k for k,v in fields.items() if v==field] if field else [col]
                        return record[1].get(cols[0]) if len(cols)==1 else None
                    aa=field_cell(av,ah);bb=field_cell(bv,bh)
                    # Later Dev schemas can materialize empty cells in columns
                    # absent from Release. A missing cell and a plain blank
                    # carry no value to merge; never infer a column for them.
                    if ((not field or (not target_fields.get(field)
                            and all(len(source_fields[id(h)].get(field,[]))<=1 for h in (ah,bh))))
                            and empty_config_cell(aa) and empty_config_cell(bb)):
                        continue
                    va=a.cell_value(normalize(aa,'A1')) if aa is not None else None
                    vb=b.cell_value(normalize(bb,'A1')) if bb is not None else None
                    # A nonexistent Release field has no formatting to update.
                    # Unchanged data must not create that foreign schema field.
                    if (va[0] if va else None)==(vb[0] if vb else None):continue
                    raise ValueError('字段无法匹配：'+field+'，不能按列号覆盖')
                address=target_col+str(row)
                if first(cell,'f') is not None and cell.getAttribute('r')!=address:
                    other=av[1].get(col) if av else None
                    if av is None or bv is None or (sig(formula(other))!=sig(formula(bv[1].get(col))) and not formula_to_literal(other,bv[1].get(col))):
                        f=first(cell,'f')
                        single=not (f.hasAttribute('t') or f.hasAttribute('ref')) or (f.getAttribute('t')=='array' and f.getAttribute('ref').replace('$','')==cell.getAttribute('r'))
                        if not (projection and single):
                            raise ValueError('配置 ID '+str(key)+' 的公式位置变化，需要核对引用')
                out[address]=normalize(cell,address)
    return out_a,out_b

def patch(before,after,local,prefer_source=False,accepted=(),scope_projection=False,session=None):
    source=session.source if session is not None else Book
    a,b=source(before),source(after)
    # A mutable destination must never alias a cached source, even if equal.
    t=Book(local);history=[source(v) for v in accepted]
    t.scope_projection=scope_projection
    notes=patch_books(a,b,t,prefer_source,history,phase=session.phase if session is not None else None)
    output=t.save();Book(output)
    return output,notes

def patch_books(a,b,t,prefer_source=False,history=(),retain=False,phase=None):
    notes=[]
    t.signature_cache=None
    # Source objects can be reclaimed between revisions; don't cache their ids.
    t.import_cache.clear();t.merge_style_cache.clear()
    original_sheet_order=list(t.sheets)
    scoped_names=[(n,original_sheet_order[int(n.getAttribute('localSheetId'))]) for n in t.workbook.getElementsByTagNameNS(M,'definedName') if n.hasAttribute('localSheetId') and int(n.getAttribute('localSheetId'))<len(original_sheet_order)]
    for name in dict.fromkeys([*a.sheets,*b.sheets,*(n for h in history for n in h.sheets)]):
        if phase:phase('比较作者改动 · '+name)
        if name in a.sheets and name in b.sheets and not history:
            raw_equal=raw_sheet_equal(a,b,name)
            if raw_equal or (retain and sheet_signature(a,name,phase)==sheet_signature(b,name,phase)):continue
        t.sheet_signatures.pop(name,None)
        if name not in b.sheets and (name in a.sheets or any(name in h.sheets for h in history)):
            if name in t.sheets:
                def sheet_values(book):return {key:book.cell_value(value) for key,value in book.cells(name).items()} if name in book.sheets else None
                if not prefer_source and sheet_values(t) not in [sheet_values(v) for v in (a,*history)]:raise ValueError('删除的工作表与 Release 冲突：'+name)
                sheet,rel,path=t.sheets.pop(name);sheet.parentNode.removeChild(sheet);rel.parentNode.removeChild(rel);t.parts.pop(path,None);t.docs.pop(path,None);t.cell_cache.pop(name,None)
                for n in list(children(t.types.documentElement)):
                    if n.getAttribute('PartName')=='/'+path:n.parentNode.removeChild(n)
                notes.append('删除工作表 '+name)
            continue
        if name not in b.sheets:continue
        if name not in t.sheets:
            if name in a.sheets:
                left,right=a.cells(name),b.cells(name)
                if all((a.cell_value(left.get(k)) or (None,))[0]==(b.cell_value(right.get(k)) or (None,))[0] for k in set(left)|set(right)):continue
                raise ValueError('Release 缺少修改中的工作表：'+name)
            sheet,rel,sourcepath=b.sheets[name]
            # New sheets may reference drawings/comments. Copy only the dependency graph of this authored sheet.
            copied={}
            def copy_part(path):
                if path in copied:return copied[path]
                base,ext=posixpath.splitext(path);dest=base+'-author-'+hashlib.sha256(b.parts[path]).hexdigest()[:12]+ext;copied[path]=dest
                t.parts[dest]=b.parts[path]
                for n in children(b.types.documentElement):
                    if n.getAttribute('PartName')=='/'+path:
                        n=n.cloneNode(True);n.setAttribute('PartName','/'+dest);t.types.documentElement.appendChild(t.types.importNode(n,True))
                rp=posixpath.join(posixpath.dirname(path),'_rels',posixpath.basename(path)+'.rels')
                if rp in b.parts:
                    rd=DOM.parseString(b.parts[rp])
                    for r in children(rd.documentElement):
                        if r.getAttribute('TargetMode')=='External':continue
                        src=posixpath.normpath(posixpath.join(posixpath.dirname(path),r.getAttribute('Target'))).lstrip('/')
                        r.setAttribute('Target',posixpath.relpath(copy_part(src),posixpath.dirname(dest)))
                    t.parts[posixpath.join(posixpath.dirname(dest),'_rels',posixpath.basename(dest)+'.rels')]=rd.toxml(encoding='utf-8')
                return dest
            path=copy_part(sourcepath);sheet=t.workbook.importNode(sheet,True);rel=t.rels.importNode(rel,True)
            rid='rIdAuthor'+hashlib.sha256(name.encode()).hexdigest()[:12];sheet.setAttributeNS(R,'r:id',rid);sheet.setAttribute('sheetId',str(max([0]+[int(s[0].getAttribute('sheetId')) for s in t.sheets.values()])+1));rel.setAttribute('Id',rid);rel.setAttribute('Target',posixpath.relpath(path,'xl'))
            t.workbook.getElementsByTagNameNS(M,'sheets')[0].appendChild(sheet);t.rels.documentElement.appendChild(rel);t.sheets[name]=(sheet,rel,path)
            # Normalize every cell in a new sheet below, including strings and styles.
            tdoc=t.doc(path)
            for c in list(tdoc.getElementsByTagNameNS(M,'c')):c.parentNode.removeChild(c)
        ac=a.cells(name) if name in a.sheets else {};bc=b.cells(name);tc=t.cells(name);hc=[h.cells(name) if name in h.sheets else {} for h in history]
        if prefer_source and not history and not any(first(c,'f') is not None for c in bc.values()) and any(formula_to_literal(c,bc.get(address)) for address,c in ac.items()):
            # A whole-sheet paste-values operation is applied to each branch's
            # own cached results before comparing authored value changes.
            # Keep source Books immutable: replay reuses them across revisions.
            try:
                ac={address:cached_formula_value(c) for address,c in ac.items()}
                frozen={address:cached_formula_value(c) for address,c in tc.items() if first(c,'f') is not None}
            except ValueError as error:raise ValueError(name+'!'+str(error)) from error
            target_doc=t.doc(t.sheets[name][2])
            for cell in list(target_doc.getElementsByTagNameNS(M,'c')):
                address=cell.getAttribute('r')
                if address in frozen:
                    node=target_doc.importNode(frozen[address],True);cell.parentNode.replaceChild(node,cell);tc[address]=node
            if frozen:
                message=name+'：按 Release 已保存的计算结果转值 '+str(len(frozen))+' 个公式'
                notes.append(message)
                if phase:phase(message)
        if prefer_source and not history and name in a.sheets:
            try:ac,bc=align_config_cells(a,b,t,ac,bc,tc)
            except ValueError as error:raise ValueError(name+'：'+str(error)) from error
        doc=t.doc(t.sheets[name][2]);data=first(doc.documentElement,'sheetData');count=0
        actual={c.getAttribute('r'):c for c in doc.getElementsByTagNameNS(M,'c')}
        # Removing a shared-formula master must not leave unchanged followers dangling.
        for address,cell in list(actual.items()):
            formula=first(cell,'f')
            if formula is not None and formula.getAttribute('t')=='shared':
                expanded=doc.importNode(tc[address],True);cell.parentNode.replaceChild(expanded,cell);actual[address]=expanded
        rows={r.getAttribute('r'):r for r in children(data,'row')}
        row_order=sorted(map(int,rows));column_indexes={}
        blank_scope_maps=False
        for address in sorted(set(ac)|set(bc)|{key for h in hc for key in h},key=lambda v:(int(re.search(r'\d+',v)[0]),number_col(re.match(r'[A-Z]+',v)[0]))):
            av,bv=a.cell_value(ac.get(address)),b.cell_value(bc.get(address))
            if av==bv and not history:continue
            if ((av is None or bv is None or av[0]!=bv[0])
                    and empty_config_cell(ac.get(address)) and empty_config_cell(bc.get(address))):
                # Re-encoding/materializing an empty cell is not a value edit.
                # Keep the source styles so genuine formatting changes remain
                # isolated, but never clear a later author's value in this field.
                if not blank_scope_maps:
                    ac=dict(ac);bc=dict(bc);blank_scope_maps=True
                for mapping in (ac,bc):
                    original=mapping.get(address)
                    empty=doc.createElementNS(M,'c');empty.setAttribute('r',address)
                    if original is not None and original.hasAttribute('s'):empty.setAttribute('s',original.getAttribute('s'))
                    mapping[address]=empty
                av,bv=a.cell_value(ac[address]),b.cell_value(bc[address])
                if av==bv:continue
            tv=t.cell_value(tc.get(address));hv=[h.cell_value(c.get(address)) for h,c in zip(history,hc)]
            if tv==bv or (av==bv and not any(tv==v and v!=bv for v in hv)):continue
            if av is not None and bv is not None and tv is not None:
                change_content=av[0]!=bv[0] or any(v is not None and tv[0]==v[0] and v[0]!=bv[0] for v in hv)
                change_style=av[1]!=bv[1] or any(v is not None and tv[1]==v[1] and v[1]!=bv[1] for v in hv)
                for component,change in enumerate((change_content,change_style)):
                    if change and tv[component] not in (av[component],bv[component]) and not any(v is not None and tv[component]==v[component] for v in hv) and not prefer_source:raise ValueError(name+'!'+address+' 单元格冲突')
            else:
                change_content=change_style=True
                if av is not None and bv is not None and tv is None:
                    if not prefer_source:raise ValueError(name+'!'+address+' Release 缺少已有单元格，无法隔离源分支内容与格式')
                    empty=doc.createElementNS(M,'c');empty.setAttribute('r',address);tc[address]=empty
                    tv=t.cell_value(empty)
                    change_content=av[0]!=bv[0];change_style=av[1]!=bv[1]
                if tv!=av and tv not in hv and not prefer_source:raise ValueError(name+'!'+address+' 单元格冲突')
            old=actual.get(address)
            source=bc.get(address)
            if source is not None:
                content=source if change_content else tc[address]
                if change_content and av is not None and bv is not None and tv is not None:
                    try:content=merge_cell_content(ac[address],bc[address],tc[address],[h.get(address) for h in hc],prefer_source,document=doc,scope_projection=getattr(t,'scope_projection',False))
                    except ValueError as error:raise ValueError(name+'!'+address+'：'+str(error)) from error
                n=doc.importNode(content,True)
                if change_style and prefer_source and av is not None and tv is not None:
                    index=t.merge_style(a,b,ac[address].getAttribute('s') or '0',source.getAttribute('s') or '0',tc[address].getAttribute('s') or '0')
                else:index=t.import_style(b,source.getAttribute('s') or '0') if change_style else tc[address].getAttribute('s') or '0'
                n.setAttribute('s',index)
                rownum=re.search(r'\d+',address)[0];row=rows.get(rownum)
                if row is None:
                    row=doc.createElementNS(M,'row');row.setAttribute('r',rownum);rows[rownum]=row
                    index=bisect.bisect_right(row_order,int(rownum))
                    following=rows[str(row_order[index])] if index<len(row_order) else None
                    data.insertBefore(row,following);row_order.insert(index,int(rownum))
                column=number_col(re.match(r'[A-Z]+',address)[0])
                if old is not None:
                    old.parentNode.replaceChild(n,old)
                    if rownum in column_indexes:column_indexes[rownum][1][column]=n
                else:
                    if rownum not in column_indexes:
                        nodes={number_col(re.match(r'[A-Z]+',c.getAttribute('r'))[0]):c for c in children(row,'c')}
                        column_indexes[rownum]=(sorted(nodes),nodes)
                    indexes,nodes=column_indexes[rownum];index=bisect.bisect_right(indexes,column)
                    following=nodes[indexes[index]] if index<len(indexes) else None
                    row.insertBefore(n,following);indexes.insert(index,column);nodes[column]=n
            elif old is not None:
                old.parentNode.removeChild(old)
                rownum=re.search(r'\d+',address)[0]
                if rownum in column_indexes:
                    indexes,nodes=column_indexes[rownum];column=number_col(re.match(r'[A-Z]+',address)[0])
                    indexes.remove(column);nodes.pop(column,None)
            count+=1
        if name in a.sheets:
            # Row and worksheet structure changes are distinct from cell values.
            ad=a.doc(a.sheets[name][2]);bd=b.doc(b.sheets[name][2])
            for tag in ('mergeCells','autoFilter','dataValidations','sheetProtection','pageMargins','pageSetup','printOptions'):
                av,bv,tv=[first(v.documentElement,tag) for v in (ad,bd,doc)]
                result=merge_structure(av,bv,tv,prefer_source)
                if sig(result)!=sig(tv):
                    if tv is not None:
                        if result is None:doc.documentElement.removeChild(tv)
                        else:doc.documentElement.replaceChild(doc.importNode(result,True),tv)
                    elif result is not None:insert_sheet_structure(doc,doc.importNode(result,True))
                    notes.append(name+'：迁移 '+tag+' 结构变化')
        if count:
            dimension=first(doc.documentElement,'dimension')
            if dimension is not None:doc.documentElement.removeChild(dimension) # optional, Excel computes used range
            notes.append(name+'：迁移 '+str(count)+' 个单元格（含公式转值）')
        # DOM nodes form cycles. Finish and release each worksheet before opening the next.
        if not retain:
            t.release_sheet(name,save=True)
            for book in (a,b,*history):
                if not getattr(book,'immutable_source',False):book.release_sheet(name)
        t.cell_cache.pop(name,None)
        # Sources retain normalized cells for equality checks and patch reuse.
        # Do not clear dictionaries owned by a source Book.
    for node,name in scoped_names:
        if name not in t.sheets:node.parentNode.removeChild(node)
        else:node.setAttribute('localSheetId',str(list(t.sheets).index(name)))
    # Recalculate after formula edits, retaining all other Release-only package parts.
    for name in list(t.parts):
        if name=='xl/calcChain.xml':t.parts.pop(name);t.docs.pop(name,None)
    for parent in (t.rels.documentElement,t.types.documentElement):
        for n in list(children(parent)):
            if n.getAttribute('Type').endswith('/calcChain') or n.getAttribute('PartName')=='/xl/calcChain.xml':parent.removeChild(n)
    calc=first(t.workbook.documentElement,'calcPr')
    if calc is not None:calc.setAttribute('fullCalcOnLoad','1')
    return notes

def restore_row(candidate, baseline, name, number, source_number=None):
    """Restore a row from the review baseline without shifting other rows."""
    if not isinstance(number,int) or not 1 <= number <= 1048576:raise ValueError('行号无效')
    source_number = number if source_number is None else source_number
    target=Book(candidate);source=Book(baseline) if baseline is not None else None
    if name not in target.sheets:raise ValueError('待合入副本中没有此工作表')
    doc=target.doc(target.sheets[name][2]);data=first(doc.documentElement,'sheetData')
    # Expand shared formulas before replacing their possible master row.
    normalized=target.cells(name)
    for cell in list(doc.getElementsByTagNameNS(M,'c')):
        formula=first(cell,'f')
        if formula is not None and formula.getAttribute('t')=='shared':
            cell.parentNode.replaceChild(doc.importNode(normalized[cell.getAttribute('r')],True),cell)
    old=next((r for r in children(data,'row') if r.getAttribute('r')==str(number)),None)
    original=None
    if source is not None and name in source.sheets:
        original=next((r for r in source.doc(source.sheets[name][2]).getElementsByTagNameNS(M,'row') if r.getAttribute('r')==str(source_number)),None)
    if original is not None:
        row=doc.importNode(original,True)
        row.setAttribute('r',str(number))
        if row.hasAttribute('s'):row.setAttribute('s',target.import_style(source,row.getAttribute('s')))
        cells=source.cells(name)
        for cell in list(children(row,'c')):
            replacement=doc.importNode(cells[cell.getAttribute('r')],True)
            replacement.setAttribute('s',target.import_style(source,replacement.getAttribute('s') or '0'))
            address = re.sub(r'\d+$',str(number),cell.getAttribute('r'))
            if source_number != number and first(replacement,'f') is not None:
                replacement = cached_formula_value(replacement)
            replacement.setAttribute('r',address)
            row.replaceChild(replacement,cell)
        if old is not None:data.replaceChild(row,old)
        else:data.insertBefore(row,next((r for r in children(data,'row') if int(r.getAttribute('r'))>number),None))
    elif old is not None:data.removeChild(old)
    dimension=first(doc.documentElement,'dimension')
    if dimension is not None:doc.documentElement.removeChild(dimension)
    target.parts.pop('xl/calcChain.xml',None)
    for parent in (target.rels.documentElement,target.types.documentElement):
        for n in list(children(parent)):
            if n.getAttribute('Type').endswith('/calcChain') or n.getAttribute('PartName')=='/xl/calcChain.xml':parent.removeChild(n)
    calc=first(target.workbook.documentElement,'calcPr')
    if calc is None:
        calc=target.workbook.createElementNS(M,'calcPr');target.workbook.documentElement.appendChild(calc)
    calc.setAttribute('fullCalcOnLoad','1')
    return target.save()

# XML structures whose child identities are explicit can be merged independently.
def insert_sheet_structure(doc, node):
    """SpreadsheetML worksheet children have a strict sequence in Excel.

    Insert only the new metadata node; moving sheetData unnecessarily is
    expensive and must never reorder cells or rewrite their values.
    """
    order = ('sheetPr dimension sheetViews sheetFormatPr cols sheetData '
             'sheetCalcPr sheetProtection protectedRanges scenarios autoFilter '
             'sortState dataConsolidate customSheetViews mergeCells phoneticPr '
             'conditionalFormatting dataValidations hyperlinks printOptions '
             'pageMargins pageSetup headerFooter rowBreaks colBreaks '
             'customProperties cellWatches ignoredErrors smartTags drawing '
             'legacyDrawing legacyDrawingHF picture oleObjects controls '
             'webPublishItems tableParts extLst').split()
    rank = {tag: index for index, tag in enumerate(order)}
    if node.namespaceURI != M or node.localName not in rank:
        raise ValueError('未知工作表结构，无法确定 Excel 节点顺序')
    following = next((child for child in children(doc.documentElement)
                      if child.namespaceURI == M and child.localName in rank
                      and rank[child.localName] > rank[node.localName]), None)
    doc.documentElement.insertBefore(node, following)


def validation_content_signature(node):
    """Ignore only Excel revision bookkeeping and an explicit false default."""
    if node is None:return None
    copy=node.cloneNode(True)
    validations=([copy] if copy.localName=='dataValidation' else
                 list(copy.getElementsByTagNameNS(M,'dataValidation')))
    for validation in validations:
        for i in reversed(range(validation.attributes.length)):
            attr=validation.attributes.item(i)
            if (attr.namespaceURI=='http://schemas.microsoft.com/office/spreadsheetml/2014/revision'
                    and attr.localName=='uid'):
                validation.removeAttribute(attr.name)
        if validation.getAttribute('showDropDown') in ('0','false'):
            validation.removeAttribute('showDropDown')
    return sig(copy)


def merge_structure(a,b,t,prefer_source=False,allow_missing=False):
    if (a is not None and b is not None and a.namespaceURI==b.namespaceURI==M
            and a.localName==b.localName and a.localName in ('dataValidations','dataValidation')
            and validation_content_signature(a)==validation_content_signature(b)):
        # A save-only rewrite has no delta. Keep Release's own ranges/rules.
        return t
    if sig(t)==sig(b) or sig(a)==sig(b):return t
    if sig(t)==sig(a):return b
    if a is None or b is None or t is None:
        if a is not None and b is not None and t is None:
            if not allow_missing:raise ValueError('Release 缺少已有工作表结构，不能带入未修改的源分支上下文')
            # Empty target property: copy only changed attributes/children.
            t=b.cloneNode(False)
            for child in list(t.childNodes):t.removeChild(child)
            for i in reversed(range(t.attributes.length)):t.removeAttribute(t.attributes.item(i).name)
            return merge_structure(a,b,t,prefer_source,allow_missing)
        if prefer_source:return b
        raise ValueError('工作表结构冲突')
    if (a.namespaceURI,a.localName)!=(b.namespaceURI,b.localName) or (a.namespaceURI,a.localName)!=(t.namespaceURI,t.localName):raise ValueError('工作表结构类型不同')
    out=t.cloneNode(True)
    def attrs(n):return {n.attributes.item(i).name:n.attributes.item(i).value for i in range(n.attributes.length)}
    aa,bb,tt=map(attrs,(a,b,t))
    for key in aa.keys()|bb.keys():
        if aa.get(key)==bb.get(key):continue
        if not prefer_source and tt.get(key) not in (aa.get(key),bb.get(key)):raise ValueError('工作表属性存在交叉修改，无法隔离：'+key)
        if key in bb:out.setAttribute(key,bb[key])
        elif out.hasAttribute(key):out.removeAttribute(key)
    def mapping(n):
        result={};counts={}
        for c in children(n):
            identity=next(((k,c.getAttribute(k)) for k in ('r','ref','sqref','name','Id','id','min') if c.hasAttribute(k)),None)
            if identity is None:
                index=counts.get(c.localName,0);counts[c.localName]=index+1;identity=('ordinal',index)
            key=(c.namespaceURI,c.localName,identity)
            if key in result:raise ValueError('工作表结构键重复')
            result[key]=c
        return result
    am,bm,tm=map(mapping,(a,b,t));om=mapping(out)
    if not am and not bm and not tm:
        text=lambda node:tuple(sig(c) for c in node.childNodes)
        if text(a)!=text(b):
            if not prefer_source and text(t) not in (text(a),text(b)):raise ValueError('工作表文本存在交叉修改，无法隔离')
            for c in list(out.childNodes):out.removeChild(c)
            for c in b.childNodes:out.appendChild(c.cloneNode(True))
        return out
    for key in dict.fromkeys([*am,*bm]):
        merged=merge_structure(am.get(key),bm.get(key),tm.get(key),prefer_source,allow_missing)
        if key in om:
            if merged is None:out.removeChild(om[key])
            else:out.replaceChild(merged.cloneNode(True),om[key])
        elif merged is not None:out.appendChild(merged.cloneNode(True))
    return out

def _signature_native(doc):
    if hasattr(doc,'e'):return doc.e
    import xml.etree.ElementTree as E
    return E.fromstring(doc.toxml(encoding='utf-8'))


def raw_sheet_equal(a,b,name):
    """Prove identical sheet XML still resolves to identical strings and styles.

    Only source Books may use this shortcut: mutable targets can have newer
    documents than their original ZIP parts. Unreferenced global additions
    cannot change this sheet, but every referenced index is checked.
    """
    if a.parts[a.sheets[name][2]]!=b.parts[b.sheets[name][2]]:return False
    styles=a.parts.get('xl/styles.xml')==b.parts.get('xl/styles.xml')
    strings=a.parts.get('xl/sharedStrings.xml')==b.parts.get('xl/sharedStrings.xml')
    if styles and strings:return True
    doc=_signature_native(a.doc(a.sheets[name][2]));q=lambda tag:'{'+M+'}'+tag
    style_ids={'0'};string_ids=set()
    for cell in doc.iter(q('c')):
        if not styles:style_ids.add(cell.get('s','0'))
        if not strings and cell.get('t')=='s':
            v=cell.find(q('v'))
            if v is not None and (v.text or len(v)):
                if len(v):return False
                string_ids.add(int(v.text))
    if not styles:
        style_ids.update(row.get('s') for row in doc.iter(q('row')) if row.get('s') is not None)
        style_ids.update(col.get('style') for col in doc.iter(q('col')) if col.get('style') is not None)
        if any(a.style(index)!=b.style(index) for index in style_ids):return False
    if not strings and any(sig(a.strings[index])!=sig(b.strings[index]) for index in string_ids):return False
    return True

def _signature_tree(book,n,structure=False):
    if n is None:return None
    q=lambda tag:'{'+M+'}'+tag
    attrs=dict(n.attrib)
    if structure and n.tag==q('row') and 's' in attrs:attrs['s']=repr(book.style(attrs['s']))
    if structure and n.tag==q('col') and 'style' in attrs:attrs['style']=repr(book.style(attrs['style']))
    nested=() if structure and n.tag==q('row') else tuple(_signature_tree(book,c,structure) for c in n if isinstance(c.tag,str))
    return (n.tag,tuple(sorted((k,v) for k,v in attrs.items() if k!='{http://www.w3.org/XML/1998/namespace}space')),n.text if n.tag in (q('t'),q('v'),q('f')) else (n.text or '').strip(),nested)

def sheet_signature(book,name,phase=None,label=''):
    if name in book.sheet_signatures:return book.sheet_signatures[name]
    if phase:phase('读取'+label+' · '+name)
    descriptor,_,path=book.sheets[name]
    cells=book.cells(name);digest=hashlib.sha256();style_digests={}
    for position,address in enumerate(sorted(cells)):
        if phase and position%10000==0:phase('核对'+label+' · '+name+' · '+str(position)+' 个单元格')
        cell=cells[address]
        if not children(cell) and book.style(cell.getAttribute('s') or '0')==book.style('0'):continue
        content,style=book.cell_value(cell);index=cell.getAttribute('s') or '0'
        if index not in style_digests:style_digests[index]=hashlib.sha256(repr(style).encode()).digest()
        digest.update(repr(content).encode());digest.update(style_digests[index]);digest.update(b'\0')
    doc=_signature_native(book.doc(path));q=lambda tag:'{'+M+'}'+tag
    structure=tuple(_signature_tree(book,n,True) for n in doc if isinstance(n.tag,str) and n.tag not in (q('dimension'),q('sheetViews')))
    result=(name,descriptor.getAttribute('state') if descriptor.hasAttribute('state') else 'visible',digest.digest(),structure)
    book.sheet_signatures[name]=result
    return result

@functools.lru_cache(maxsize=6)
def logical_signature(data):
    return book_signature(Book(data))

def book_signature(book,phase=None,label=''):
    if book.signature_cache is not None:return book.signature_cache
    p=book.parts;q=lambda tag:'{'+M+'}'+tag
    wb=_signature_native(book.workbook);rels={n.get('Id'):n for n in _signature_native(book.rels) if isinstance(n.tag,str)}
    sheets=tuple(sheet_signature(book,name,phase,label) for name in book.sheets)
    ignored={v[2] for v in book.sheets.values()}|{'xl/styles.xml','xl/sharedStrings.xml','xl/workbook.xml','xl/_rels/workbook.xml.rels','docProps/core.xml','docProps/app.xml','xl/calcChain.xml','[Content_Types].xml'}
    other=tuple(sorted((n,v) for n,v in p.items() if n not in ignored))
    names=_signature_tree(book,wb.find(q('definedNames')))
    settings=tuple(_signature_tree(book,n) for n in wb if isinstance(n.tag,str) and n.tag not in (q('sheets'),q('bookViews'),q('calcPr'),q('fileVersion'),q('definedNames')))
    external=tuple(sorted((n.get('Id'),n.get('Type'),n.get('Target'),n.get('TargetMode')) for n in rels.values() if not n.get('Type','').endswith(('/worksheet','/styles','/sharedStrings','/calcChain'))))
    book.signature_cache=(sheets,names,other,settings,external)
    return book.signature_cache

def books_equal(a,b,phase=None):
    if list(a.sheets)!=list(b.sheets):return False
    for name in a.sheets:
        if sheet_signature(a,name,phase)!=sheet_signature(b,name,phase):return False
    return book_signature(a)==book_signature(b)


class WorkbookMergeSession:
    """Bounded read-only parsing cache for one file's Dev scope projections.

    The pinned Dev tip survives revisions; at most two other snapshots remain
    cached. Mutable destinations are always separate Books. No cache survives
    the plan, so cancellation/errors cannot contaminate subsequent operations.
    """
    def __init__(self,pinned,phase=None):
        from collections import OrderedDict, Counter
        self.pinned=hashlib.sha256(pinned).digest() if pinned is not None else None
        self.books=OrderedDict();self.phase=phase;self.equalities={}
        self.history_snapshots={};self.metrics=Counter()
        self.projections=OrderedDict();self.projection_bytes=0;self.projection_limit=64*1024*1024
    def project(self,before,after,target,compute):
        import time
        key=tuple(hashlib.sha256(value).digest() if value is not None else None for value in (before,after,target))
        if key in self.projections:
            if self.phase:self.phase('复用已核验的作者改动范围')
            self.metrics['projection_hits']+=1
            self.projections.move_to_end(key)
            return self.projections[key]
        start=time.monotonic();result=compute()
        self.metrics['projection_builds']+=1
        self.metrics['projection_seconds']+=time.monotonic()-start
        size=len(result) if result is not None else 0
        if size<=self.projection_limit:
            while self.projections and (self.projection_bytes+size>self.projection_limit or len(self.projections)>=32):
                _,old=self.projections.popitem(last=False)
                self.projection_bytes-=len(old) if old is not None else 0
            self.projections[key]=result;self.projection_bytes+=size
        return result
    def source(self,data):
        key=hashlib.sha256(data).digest()
        if key not in self.books:
            self.metrics['source_builds']+=1
            if self.phase:self.phase('解析并缓存 Excel 版本')
            book=Book(data);book.retain_cells=True;book.immutable_source=True;book.phase=self.phase
            self.books[key]=book
        else:self.metrics['source_hits']+=1
        self.books.move_to_end(key)
        while len(self.books)>3:
            victim=next(k for k in self.books if k!=self.pinned)
            del self.books[victim]
        return self.books[key]
    def signature(self,data):
        return book_signature(self.source(data),self.phase)
    def equal(self,left,right):
        key=tuple(sorted((hashlib.sha256(left).digest(),hashlib.sha256(right).digest())))
        if key not in self.equalities:
            self.equalities[key]=books_equal(self.source(left),self.source(right),self.phase)
            if len(self.equalities)>64:self.equalities.pop(next(iter(self.equalities)))
        return self.equalities[key]
    def clear(self):
        self.books.clear();self.equalities.clear()
        self.history_snapshots.clear();self.projections.clear();self.projection_bytes=0


class WorkbookReplay:
    """One Release document across verified revisions; serialize only at finish."""
    def __init__(self,baseline,phase=None,session=None):
        self.baseline=baseline;self.raw=baseline;self.target=None;self.dirty=False
        self.same_cache=None;self.phase=phase;self.sources={};self.session=session
    def source(self,data):
        key=hashlib.sha256(data).digest()
        if self.session is not None and key in self.session.books:
            return self.session.source(data)
        if key not in self.sources:
            book=Book(data);book.retain_cells=True;book.phase=self.phase
            self.sources[key]=book
            while len(self.sources)>2:self.sources.pop(next(iter(self.sources)))
        return self.sources[key]
    def current(self):
        if self.target is None and self.raw is not None:
            self.target=Book(self.raw);self.target.retain_cells=True;self.target.phase=self.phase
        return self.target
    def reset(self,data):
        self.raw=data;self.target=None;self.dirty=False
    def apply(self,before,after):
        self.same_cache=None
        if (not self.dirty and self.raw==after) or before==after:return
        if after is None or before is None or (not self.dirty and self.raw==before):
            self.reset(after);return
        t=self.current()
        if t is None:raise ValueError('文件新增/删除与目标状态不一致')
        a,b=self.source(before),self.source(after)
        if books_equal(t,b,self.phase) or books_equal(a,b,self.phase):return
        patch_books(a,b,t,True,retain=True,phase=self.phase)
        self.dirty=True
    def same(self):
        if not self.dirty and self.raw==self.baseline:return True
        t=self.current()
        if t is None or self.baseline is None:return t is None and self.baseline is None
        if self.same_cache is None:
            original=Book(self.baseline);original.phase=self.phase
            self.same_cache=books_equal(t,original,self.phase)
        return self.same_cache
    def finish(self):
        self.sources.clear()  # Free historical XML before final baseline verification.
        if self.same():return self.baseline
        if not self.dirty:return self.raw
        if self.phase:self.phase('保存最终待合入副本')
        output=self.target.save();Book(output)
        return output
