"""Audit deleted configuration rows against every subsequent SVN file revision.

A blank key never authorizes positional matching. A certified keyless deletion
can remove one exact Release row, or be a no-op when all remaining keyless rows
are known unchanged context. Intermediate restores are checked even when HEAD
has deleted the row again.
"""
from collections import Counter
import hashlib
import json
import functools
import xml.etree.ElementTree as ET
from workbook_cells import Book, config_layout, config_cell_text, empty_config_cell, first, sig, sheet_signature, M

VERSION = 2


def history_entries(core, config, path, start, end):
    if start >= end:return []
    source=core.urlpath(config['dev'],path)
    branch_log=False
    try:raw=core.run('log','--xml','-v','-r',f'{start+1}:{end}','--',source+'@'+str(end)).stdout
    except RuntimeError as error:
        if not any(code in str(error) for code in ('E160013','E200009')):raise
        # A deleted file has no peg at HEAD. Inspect its branch history instead.
        branch_log=True
        raw=core.run('log','--xml','-v','-r',f'{start+1}:{end}','--',config['dev']+'@'+str(end)).stdout
    result=[]
    for entry in ET.fromstring(raw).findall('logentry'):
        revision=int(entry.get('revision'))
        if not start < revision <= end:raise ValueError('删除历史核验：SVN 返回了范围外版本')
        changes=[]
        for node in entry.findall('paths/path'):
            relative=core.relpath(node.text,config['dev'],config['root'])
            if relative==path or (node.get('action')!='M' and relative is not None and (not relative or path.startswith(relative.rstrip('/')+'/'))):
                changes.append((relative,node.get('action'),node.get('copyfrom-path'),node.get('copyfrom-rev')))
        if not changes:
            if branch_log:continue
            raise ValueError('删除历史核验：无法确认提交中的文件路径')
        author=entry.findtext('author')
        if not author:raise ValueError('删除历史核验：提交作者缺失，不能证明无人修改')
        result.append(dict(revision=revision,author=author,changes=sorted(changes,key=repr)))
    return sorted(result,key=lambda item:item['revision'])


def digest(entries):
    return hashlib.sha256(json.dumps(entries,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def validate(core, config, path, evidence, revision=None):
    if not evidence or evidence.get('version')!=VERSION:
        raise RuntimeError('删除历史核验规则已更新，请重新生成副本；未写入 Release')
    if evidence.get('fromRevision') is None:return
    end=revision if revision is not None else core.info(config['dev'],'HEAD')['revision']
    if end < evidence['throughRevision'] or digest(history_entries(core,config,path,evidence['fromRevision'],end))!=evidence['historyHash']:
        raise RuntimeError('删除之后的 SVN 历史已变化（即使最终内容相同），请重新生成并核对；未写入 Release')


@functools.lru_cache(maxsize=32)
def duplicate_fields(fields):
    return frozenset(field for field,count in Counter(fields).items() if count>1)


def token(row, header):
    values=[]
    duplicates=duplicate_fields(tuple(header.values()))
    for col,cell in row.items():
        if empty_config_cell(cell):continue
        namespace,tag,attrs,content=sig(cell)
        attrs=[a for a in attrs if a[1] not in ('r','s') and a!=('','t','n')]
        field=header.get(col) or '@'+col
        if header.get(col) and field in duplicates:
            raise ValueError('删除历史核验：字段声明不唯一')
        values.append((field,repr((namespace,tag,attrs,content))))
    return tuple(sorted(values))


def inventory(book, name):
    if name not in book.sheets:return None
    layout=config_layout(book.cells(name))
    if layout is None:return None
    header,rows,meta=layout
    keys=sorted(v for v in header.values() if v.startswith('*'))
    if len(keys)!=len(set(keys)):raise ValueError('删除历史核验：主键声明不唯一')
    cols=[next(c for c,v in header.items() if v==k) for k in keys]
    keyed={};keyless={}
    for number,row in rows.items():
        if number in meta:continue
        identity=tuple(config_cell_text(row.get(c)) for c in cols)
        if all(identity):
            if identity in keyed:raise ValueError('删除历史核验：配置 ID 重复 '+str(identity))
            keyed[identity]=(number,row)
        else:
            value=token(row,header)
            if value:keyless.setdefault(value,[]).append((number,row))
    return dict(header=header,keys=keys,keyed=keyed,keyless=keyless,
                hasFormulas=any(first(cell,'f') is not None for row in rows.values() for cell in row.values()))


def counts(inv):return Counter({key:len(rows) for key,rows in inv['keyless'].items()})


def row_digest(value):return hashlib.sha256(repr(value).encode()).digest()


def empty_formula_scaffold(row,header):
    """Only blank-result helper formulas, with no declared field or literal data.

    This is not a general formula deletion exemption. Certification additionally
    requires formula-free post-delete snapshots and a formula-free Release.
    """
    found=False
    for col,cell in row.items():
        if empty_config_cell(cell):continue
        formula=first(cell,'f');value=first(cell,'v')
        if header.get(col) or formula is None or value is None:return False
        if cell.getAttribute('t')!='str' or value.childNodes:return False
        if sig(formula)[2] or not formula.firstChild:return False
        plain=cell.cloneNode(True);plain.removeChild(first(plain,'f'))
        if not empty_config_cell(plain):return False
        found=True
    return found


def summary(inv,tracked=None,payloads=True):
    if inv is None:return None
    keyed={};contents=set()
    for key,(_,row) in inv['keyed'].items():
        if not payloads and tracked is not None and key not in tracked:continue
        value=token(row,inv['header']);keyed[key]=row_digest(value)
        if payloads:contents.add(row_digest(tuple(pair for pair in value if not pair[0].startswith('*'))))
    return dict(keys=inv['keys'],keyed=keyed,keyless=counts(inv),payloads=contents,hasFormulas=inv['hasFormulas'],
                ids=set(inv['keyed']),tracked=frozenset(tracked or ()),complete=tracked is None or payloads,withPayloads=payloads)


def remove_rows(book,name,numbers):
    numbers=set(map(str,numbers))
    doc=book.doc(book.sheets[name][2])
    selected=[row for row in doc.getElementsByTagNameNS(M,'row') if row.getAttribute('r') in numbers]
    if len({row.getAttribute('r') for row in selected})!=len(selected):
        raise ValueError(name+'：待删除行的 XML 行号重复，无法可靠定位')
    # A removed helper row may own a shared formula used by surviving rows.
    # Materialize followers before removing their master from the source copy.
    if any((f:=first(cell,'f')) is not None and f.getAttribute('t')=='shared'
           for row in selected for cell in row.getElementsByTagNameNS(M,'c')):
        normalized=book.cells(name)
        for cell in list(doc.getElementsByTagNameNS(M,'c')):
            f=first(cell,'f')
            if f is not None and f.getAttribute('t')=='shared':
                cell.parentNode.replaceChild(doc.importNode(normalized[cell.getAttribute('r')],True),cell)
    for row in selected:row.parentNode.removeChild(row)
    book.cell_cache.pop(name,None)
    book.sheet_signatures.pop(name,None)
    book.signature_cache=None


def remove_row(book,name,number):remove_rows(book,name,[number])


class DeletionHistory:
    def __init__(self,core,config,path,session,start):
        self.core=core;self.config=config;self.path=path;self.session=session;self.start=start
        self.entries=None;self.checked=[];self.first=None
        identity=json.dumps([config,path,start],sort_keys=True)
        self.snapshots=session.history_snapshots.setdefault(identity,{})

    def snapshot(self,entry,names):
        revision=entry['revision']
        requests=names if isinstance(names,dict) else {name:(None,True) for name in names}
        absent=[]
        for name,(tracked,payloads) in requests.items():
            cached=self.snapshots.get((revision,name))
            if (revision,name) not in self.snapshots or (cached is not None and
                    ((payloads and not cached['withPayloads']) or
                     (not cached['complete'] and (tracked is None or not set(tracked).issubset(cached['tracked']))))):absent.append(name)
            else:self.session.metrics['history_hits']+=1
        if absent:
            source=self.core.urlpath(self.config['dev'],self.path)
            data=self.core.run('cat','-r',revision,'--',source+'@'+str(revision)).stdout
            book=Book(data)
            for name in absent:
                tracked,payloads=requests[name]
                cached=self.snapshots.get((revision,name))
                if cached is not None:
                    # A second coverage request promotes to all keyed digests.
                    # Never discard IDs or payload coverage learned earlier.
                    tracked=None
                    payloads=payloads or cached['withPayloads']
                    self.session.metrics['history_promotions']+=1
                self.snapshots[revision,name]=summary(inventory(book,name),tracked,payloads)
                self.session.metrics['history_builds']+=1
        return {name:self.snapshots[revision,name] for name in names}

    def later(self,revision):
        if self.entries is None:self.entries=history_entries(self.core,self.config,self.path,self.start,self.config['snapshot'])
        return [entry for entry in self.entries if entry['revision']>revision]

    def prepare(self,before,after,revision,replay):
        if before is None:return before
        if after is None:
            later=self.later(revision)
            if any(entry['author']!=self.config['author'] for entry in later):
                raise ValueError('文件删除后被其他作者修改或恢复，不能按旧删除处理')
            self.first=revision if self.first is None else min(self.first,revision)
            self.checked.append(dict(deletedAt=revision,fileDeleted=True,checkedRevisions=[e['revision'] for e in later]))
            return before
        a,b=self.session.source(before),self.session.source(after)
        removed_sheets=set(a.sheets)-set(b.sheets)
        if removed_sheets:
            later=self.later(revision);previous={name:None for name in removed_sheets}
            for entry in later:
                if any(action!='M' or copied for _,action,copied,_ in entry['changes']):
                    raise ValueError('删除工作表后发生文件复制、替换或删除，无法可靠追踪')
                source=self.core.urlpath(self.config['dev'],self.path)
                data=self.core.run('cat','-r',entry['revision'],'--',source+'@'+str(entry['revision'])).stdout
                book=Book(data)
                for name in sorted(removed_sheets):
                    current=sheet_signature(book,name) if name in book.sheets else None
                    if current!=previous[name] and entry['author']!=self.config['author']:
                        raise ValueError(name+'：工作表删除后被其他作者修改或恢复：r'+str(entry['revision'])+' / '+entry['author'])
                    previous[name]=current
            self.first=revision if self.first is None else min(self.first,revision)
            self.checked.append(dict(deletedAt=revision,deletedSheets=sorted(removed_sheets),checkedRevisions=[e['revision'] for e in later]))
        deletions=[]
        for name in a.sheets:
            if name not in b.sheets:continue
            # Most sheets are untouched. Shared strings can change independently.
            if a.parts[a.sheets[name][2]]==b.parts[b.sheets[name][2]] and a.parts.get('xl/sharedStrings.xml')==b.parts.get('xl/sharedStrings.xml'):continue
            # Re-saving XML or formatting cannot delete a record. Require the
            # complete stationary content proof before interpreting identities;
            # unrelated duplicate IDs must not block deletion history elsewhere.
            from deletion_guard import _same_content
            if _same_content(a,b,name):continue
            left,right=inventory(a,name),inventory(b,name)
            if left is None or right is None:continue
            if left['keys']!=right['keys']:raise ValueError('删除历史核验：主键结构发生变化')
            gone=set(left['keyed'])-set(right['keyed'])
            missing=counts(left)-counts(right)
            if missing and counts(right)-counts(left):
                raise ValueError(name+'：无 ID 数据同时新增或变化，不能认定为单纯删除')
            if gone or missing:deletions.append((name,left,right,gone,missing))
        if not deletions:return before
        later=self.later(revision)
        self.first=revision if self.first is None else min(self.first,revision)
        cleaned=None
        for name,left,right,gone,missing in deletions:
            scaffolds=set()
            for value,count in missing.items():
                if len(left['keyless'][value])!=1 or count!=1 or right['keyless'].get(value):
                    raise ValueError(name+'：被删除的无 ID 数据不唯一')
                if any(first(cell,'f') is not None for cell in left['keyless'][value][0][1].values()):
                    if not empty_formula_scaffold(left['keyless'][value][0][1],left['header']):
                        raise ValueError(name+'：被删除的无 ID 数据含公式，无法可靠追踪')
                    scaffolds.add(value)
            previous=summary(right,gone,bool(missing))
            if scaffolds and previous['hasFormulas']:
                raise ValueError(name+'：清除空公式残留后仍有公式，无法排除对应数据已变化')
            for entry in later:
                if any(action!='M' or copied for _,action,copied,_ in entry['changes']):
                    raise ValueError('r'+str(entry['revision'])+'：删除之后发生复制、替换或文件删除，无法可靠追踪')
                if getattr(self.core,'sync_phase',None):self.core.sync_phase('核对删除后历史 · r'+str(entry['revision'])+' · '+entry['author']+' · '+name)
                current=self.snapshot(entry,{item[0]:(item[3],bool(item[4])) for item in deletions})[name]
                if current is None or current['keys']!=right['keys']:
                    raise ValueError(name+'：删除之后的工作表或主键结构无法追踪')
                if scaffolds and current['hasFormulas']:
                    raise ValueError(name+'：r'+str(entry['revision'])+' / '+entry['author']+' 在清除空公式残留后出现公式，无法排除恢复')
                if entry['author']!=self.config['author']:
                    for key in gone:
                        av=previous['keyed'].get(key);bv=current['keyed'].get(key)
                        if av!=bv:
                            raise ValueError(name+'：删除后被其他作者修改或恢复：r'+str(entry['revision'])+' / '+entry['author']+' / ID '+str(key))
                if missing:
                    # Without a key, new keyed records could be an edited restore
                    # with a newly assigned ID. Do not infer identity by similarity.
                    additions=current['ids']-previous['ids']
                    changed_keyless=current['keyless']-previous['keyless']
                    def restored(inv):
                        return {value for value in missing if row_digest(tuple(pair for pair in value if not pair[0].startswith('*'))) in inv['payloads']}
                    if (additions and set(missing)-scaffolds) or changed_keyless or restored(current)-restored(previous):
                        raise ValueError(name+'：r'+str(entry['revision'])+' / '+entry['author']+' 在删除后新增或修改了可能对应的无 ID 数据，无法排除恢复')
                previous=current
            if missing:
                if replay is None:raise ValueError(name+'：无 ID 删除需通过作者核对合入')
                target=replay.current();dest=inventory(target,name) if target else None
                if dest is None or dest['keys']!=left['keys']:raise ValueError(name+'：Release 记录结构无法匹配')
                if scaffolds and summary(dest)['hasFormulas']:
                    raise ValueError(name+'：Release 仍有公式，无法排除空公式残留已变化')
                target_rows=[];source_rows=[]
                for value in missing:
                    matches=dest['keyless'].get(value,[])
                    if len(matches)>1:raise ValueError(name+'：Release 中待删除无 ID 数据不唯一')
                    if not matches and counts(dest)-counts(right)-missing:
                        raise ValueError(name+'：Release 存在无法排除为此记录修改结果的无 ID 数据')
                    if matches:
                        target_rows.append(matches[0][0])
                    source_rows.append(left['keyless'][value][0][0])
                if target_rows:
                    remove_rows(target,name,target_rows);replay.dirty=True;replay.same_cache=None
                if cleaned is None:cleaned=Book(before)
                remove_rows(cleaned,name,source_rows)
            self.checked.append(dict(deletedAt=revision,sheet=name,keys=[list(k) for k in sorted(gone)],
                                     keylessRows=[left['keyless'][v][0][0] for v in missing],
                                     emptyFormulaRows=[left['keyless'][v][0][0] for v in scaffolds],
                                     checkedRevisions=[e['revision'] for e in later],otherAuthors=sorted({e['author'] for e in later if e['author']!=self.config['author']})))
        return cleaned.save() if cleaned is not None else before

    def evidence(self):
        entries=[entry for entry in (self.entries or []) if self.first is not None and entry['revision']>self.first]
        return dict(version=VERSION,fromRevision=self.first,throughRevision=self.config['snapshot'],historyHash=digest(entries),deletions=self.checked)
