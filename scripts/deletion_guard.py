"""Independent final-result check: do not delete data still present in Dev.

This validator never repairs a candidate or guesses which old revision wins. It
compares semantic identities in Release, the candidate and pinned Dev. It is run
again at acceptance after checking that the Dev snapshot is still current.
"""
import re
import galaxy_sync

VERSION = 2


def _fail(path, locations):
    detail='；'.join(str(v) for v in locations[:8])
    raise ValueError('删除保护：'+path+' 的候选会删除或清空当前 Dev 仍保留的数据：'+detail+'。可能是他人后续恢复，请重新生成并核对；未写入 Release')


def _payload(cell):
    if cell is None:return False
    from workbook_cells import first, config_cell_text
    return first(cell,'f') is not None or bool(config_cell_text(cell))


def _cell_content(book, cell):
    from workbook_cells import empty_config_cell
    # Styles and plain blank storage cannot delete data. Keep formulas, rich
    # text, cell attributes and extensions in the proof, including addresses.
    return None if empty_config_cell(cell) else book.cell_value(cell)[0]


def _same_content(a, b, name):
    ac,bc=a.cells(name),b.cells(name)
    return all(_cell_content(a,ac.get(key))==_cell_content(b,bc.get(key))
               for key in ac.keys()|bc.keys())


def _unchanged_duplicates(a, b, name):
    """Exempt ambiguous groups only with a complete, stationary content proof.

    Never match a deleted duplicate to its neighbour or infer identity from a
    partial row. Both branches of the comparison here are Release/candidate;
    Dev is not needed for groups whose every cell remains untouched.
    """
    from workbook_cells import config_layout, config_cell_text
    layouts=[config_layout(book.cells(name)) for book in (a,b)]
    if any(layout is None for layout in layouts):return set()
    (ah,ar,am),(bh,br,bm)=layouts
    if ah!=bh or am!=bm:return set()
    keys=sorted(v for v in ah.values() if v.startswith('*'))
    if len(keys)!=len(set(keys)):return set()
    cols=[next(c for c,v in ah.items() if v==key) for key in keys]
    groups=[]
    for book,rows,meta in ((a,ar,am),(b,br,bm)):
        result={}
        for number,row in rows.items():
            if number in meta:continue
            values=tuple(config_cell_text(row.get(col)) for col in cols)
            if not all(values):continue
            result.setdefault(values,{})[number]={col:_cell_content(book,cell)
                for col,cell in row.items() if _cell_content(book,cell) is not None}
        groups.append(result)
    return {('record',tuple(zip(keys,values))) for values,rows in groups[0].items()
            if len(rows)>1 and rows==groups[1].get(values)}


def _sheet_inventory(book, name, unchanged=()):
    from workbook_cells import config_layout, config_cell_text
    cells=book.cells(name);layout=config_layout(cells)
    if layout is None:
        return {('cell',address) for address,cell in cells.items() if _payload(cell)},None
    header,rows,meta=layout
    keys=sorted(v for v in header.values() if v.startswith('*'))
    if len(keys)!=len(set(keys)):
        raise ValueError('删除保护：主键声明重复，无法确认配置行身份：'+name)
    keycols=[next(col for col,v in header.items() if v==key) for key in keys]
    result=set();seen=set()
    for number,row in rows.items():
        if number in meta:
            # Metadata moves with the declaration, not with physical row numbers.
            identity=('header',str(meta[number]))
        else:
            values=tuple(config_cell_text(row.get(col)) for col in keycols)
            if not all(values):
                # Keyless auxiliary data cannot be identified by a partial match.
                # An exact-value token catches deletion of a restored moved block.
                for col,cell in row.items():
                    if _payload(cell):
                        result.add(('auxiliary',header.get(col) or col,repr(book.cell_value(cell)[0][3])))
                continue
            identity=('record',tuple(zip(keys,values)))
            if identity in unchanged:continue
            if identity in seen:raise ValueError('删除保护：配置 ID 重复：'+name+' '+str(values))
            seen.add(identity);result.add(identity)
        for col,cell in row.items():
            if _payload(cell):
                field=header.get(col) or '@'+col
                if header.get(col) and list(header.values()).count(field)!=1:
                    raise ValueError('删除保护：字段声明重复：'+name+' '+field)
                result.add((*identity,field))
    return result,tuple(keys)


def _workbook(before, after, dev, path, phase):
    from workbook_cells import Book
    a,b,d=[Book(v) for v in (before,after,dev)]
    issues=[];removed=0
    for name in a.sheets:
        if phase:phase('删除保护 · '+name)
        if name not in b.sheets:
            removed+=1
            if name in d.sheets:issues.append('工作表 '+name)
            continue
        # Serialized equality is enough for a no-deletion fast path. Shared
        # strings are checked too, since unchanged indexes can change values.
        if (a.parts[a.sheets[name][2]]==b.parts[b.sheets[name][2]] and
                a.parts.get('xl/sharedStrings.xml')==b.parts.get('xl/sharedStrings.xml')):continue
        # Repacking shared strings or changing formatting on an unrelated page
        # must not turn that page's pre-existing duplicate IDs into a blocker.
        if _same_content(a,b,name):
            for book in (a,b,d):book.release_sheet(name)
            continue
        unchanged=set()
        try:
            aa,ak=_sheet_inventory(a,name);bb,bk=_sheet_inventory(b,name)
        except ValueError as error:
            if not str(error).startswith('删除保护：配置 ID 重复：'):raise
            unchanged=_unchanged_duplicates(a,b,name)
            if not unchanged:raise
            aa,ak=_sheet_inventory(a,name,unchanged);bb,bk=_sheet_inventory(b,name,unchanged)
        if ak!=bk:raise ValueError('删除保护：工作表 '+name+' 的主键声明发生变化，无法可靠定位删除')
        gone=aa-bb;removed+=len(gone)
        if gone and name in d.sheets:
            dd,dk=_sheet_inventory(d,name,unchanged)
            if ak!=dk:raise ValueError('删除保护：Dev 工作表 '+name+' 的主键声明不同，无法可靠定位删除')
            for key in sorted(gone & dd,key=repr):issues.append(name+' '+str(key))
        for book in (a,b,d):book.release_sheet(name)
    if issues:_fail(path,issues)
    return removed


def _lua_inventory(data):
    from lua_sync import parse
    root=parse(data)[1];result=set()
    def visit(node,path):
        # An existing table (even empty) has identity; nil means absence.
        if node.children is not None:
            if path:result.add(path)
            for key,value in node.children.items():visit(value,path+(key,))
        elif node.raw not in ('nil','""',"''",'[[]]'):result.add(path)
    visit(root,())
    return result


def _galaxy_inventory(data):
    result=set()
    for identity,(_,fields) in galaxy_sync.parse(data)[2].items():
        result.add((identity,))
        for name,value in fields.items():
            if value.strip():result.add((identity,name))
    return result


def check(before, after, dev, path, phase=None):
    """Raise before any working-copy write; return reviewable audit metadata."""
    removed=0;kind='file'
    if before is not None and after is None:
        removed=1
        if dev is not None:_fail(path,['整个文件'])
    elif before is not None and after is not None and before!=after and dev is not None:
        if path.lower().endswith(('.xlsx','.xlsm')):
            kind='workbook';removed=_workbook(before,after,dev,path,phase)
        elif path.lower().endswith('.lua') or galaxy_sync.supports(path):
            kind='lua' if path.lower().endswith('.lua') else 'galaxy'
            inventory=_lua_inventory if kind=='lua' else _galaxy_inventory
            try:
                try:a=inventory(before)
                except ValueError as error:
                    if kind=='lua' and str(error)=='非 Lua 数据表':
                        return {'version':VERSION,'status':'passed','kind':'file','removedIdentities':0}
                    raise
                b=inventory(after)
                gone=a-b;removed=len(gone)
                if gone:
                    remaining=gone & inventory(dev)
                    if remaining:_fail(path,sorted(remaining,key=repr))
            except ValueError as error:
                if str(error).startswith('删除保护：'):raise
                raise ValueError('删除保护：无法可靠识别 '+path+' 的对象或字段，需人工核对：'+str(error)) from error
    return {'version':VERSION,'status':'passed','kind':kind,'removedIdentities':removed}


def check_properties(before, after, dev, path):
    blocked=(before.keys()-after.keys()) & dev.keys()
    if blocked:_fail(path,['SVN 属性 '+k for k in sorted(blocked)])
