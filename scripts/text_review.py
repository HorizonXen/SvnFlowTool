"""Pinned SVN line attribution and explicit Lua field choices for existing compare UI."""
import difflib
import hashlib
import json
import pathlib
import tempfile
import xml.etree.ElementTree as ET
import lua_sync
import file_sync as files


def fields(data):
    if data is None: return {}
    text = data.decode('utf-8')
    root = lua_sync.parse(data)[1]
    result = {}
    def visit(node, path):
        if node.children is None or not node.children:
            result[json.dumps(path)] = (node, text.count('\n', 0, node.start) + 1)
        else:
            for key, child in node.children.items(): visit(child, path + [key])
    visit(root, [])
    return result


def attribution(core, url, revision, data):
    if data is None: return []
    tree = ET.fromstring(core.run('blame', '--xml', '-r', revision, '--', url+'@'+str(revision)).stdout)
    result = ['来源未知'] * len(data.decode('utf-8').splitlines())
    for entry in tree.findall('.//entry'):
        commit = entry.find('commit'); index = int(entry.get('line-number')) - 1
        if commit is not None and 0 <= index < len(result):
            result[index] = (commit.findtext('author') or '未知作者')+' · '+((commit.findtext('date') or '未知日期')[:19].replace('T',' '))+' · r'+commit.get('revision', '?')
    return result


def read_version(core, url, revision):
    result = core.run('cat', '-r', revision, '--', url+'@'+str(revision), check=False)
    if result.returncode:
        error = result.stderr.decode('utf-8', 'replace')
        if any(code in error for code in ('E160013','W160013','W170000')): return None
        raise RuntimeError(error)
    return result.stdout


def mapped_lines(data, source, labels):
    output = ['待合入 · 未提交 / 结构重排'] * len((data or b'').decode('utf-8').splitlines())
    for block in difflib.SequenceMatcher(None, (source or b'').splitlines(), (data or b'').splitlines(), autojunk=False).get_matching_blocks():
        output[block.b:block.b+block.size] = labels[block.a:block.a+block.size]
    return output


def load(core, folder, report, state, path):
    import staged_sync as staged
    entry = state['items'].get(path)
    if not entry or entry['status'] != 'ready': raise RuntimeError('文件不在待确认状态')
    baseline = staged.reviewed_bytes(folder, entry, 'baseline', 'Release快照')
    candidate = staged.reviewed_bytes(folder, entry, 'candidate', '待合入')
    if 'textReview' not in entry:
        c = report['config']; revision = entry['revision']; url = core.urlpath(c['dev'], path)
        old_labels = attribution(core, core.urlpath(c['release'],path), revision, baseline)
        latest = read_version(core, url, revision)
        latest_labels = attribution(core, url, revision, latest)
        cache = {'old': old_labels, 'original': (candidate or b'').decode('utf-8'),
                 'latest': None if latest is None else latest.decode('utf-8'), 'revision': revision,
                 'choices': [], 'selected': {}, 'fieldOrigins': {}}
        try:
            base_fields, original_fields, latest_fields = [fields(v) for v in (baseline, candidate, latest)]
        except (ValueError, IndexError):
            base_fields = original_fields = latest_fields = {}
        # Replay provenance only for positions actually changed in verified author revisions.
        origins = {}
        if original_fields:
            for rev in sorted(entry['revisions']):
                before = read_version(core,url,rev-1); after = read_version(core,url,rev)
                try: a,b = fields(before), fields(after)
                except (ValueError,IndexError): continue
                labels = attribution(core,url,rev,after)
                for key, (node,line) in b.items():
                    if key not in a or a[key][0].value() != node.value(): origins[key] = (node.value(), labels[line-1])
        for key in dict.fromkeys([*base_fields,*original_fields,*latest_fields]):
            nodes = [table.get(key) for table in (base_fields,original_fields,latest_fields)]
            values = [pair[0].raw if pair else None for pair in nodes]
            original_origin = '待合入 · 未提交 / 来源待核对'
            if key in origins and nodes[1] and nodes[2] and nodes[1][0].value() == nodes[2][0].value(): original_origin = latest_labels[nodes[2][1]-1]
            elif key in origins and nodes[1] and origins[key][0] == nodes[1][0].value(): original_origin = origins[key][1]
            elif nodes[0] and nodes[1] and nodes[0][0].value() == nodes[1][0].value(): original_origin = old_labels[nodes[0][1]-1]
            cache['fieldOrigins'][key] = original_origin
            if len(set(values)) < 2: continue
            cache['choices'].append({'id':key, 'label':' / '.join(k[1] for k in json.loads(key)),
                'values': values, 'origins': [old_labels[nodes[0][1]-1] if nodes[0] else '此版本无该字段', original_origin,
                                          latest_labels[nodes[2][1]-1] if nodes[2] else '此版本无该字段']})
        entry['textReview'] = cache
        core.write_json(folder/'review.json',state)
    cache = entry['textReview']
    new_labels = mapped_lines(candidate,baseline,cache['old'])
    try: current = fields(candidate); previous = fields(baseline)
    except (ValueError,IndexError): current = previous = {}
    choice_by_key = {v['id']:v for v in cache['choices']}
    line_origins = {}
    for key,(node,line) in current.items():
        choice = choice_by_key.get(key)
        label = choice['origins'][cache['selected'].get(key,1)] if choice else cache['fieldOrigins'].get(key,'来源待核对')
        end_line = (candidate or b'').decode('utf-8').count('\n',0,node.end)+1
        for index in range(line-1,min(end_line,len(new_labels))):
            line_origins.setdefault(index,[])
            if label not in line_origins[index]: line_origins[index].append(label)
    for index,labels in line_origins.items(): new_labels[index] = ' / '.join(labels)
    choices = [dict(v, oldLine=previous[v['id']][1] if v['id'] in previous else None,
                    newLine=current[v['id']][1] if v['id'] in current else None,
                    selected=cache['selected'].get(v['id'],1)) for v in cache['choices']]
    return {'old':cache['old'], 'new':new_labels, 'choices':choices, 'revision':cache['revision']}


def replace_field(data, key, value):
    path = [tuple(v) for v in json.loads(key)]
    prefix,root,suffix = lua_sync.parse(data)
    current = root
    for part in path[:-1]:
        if current.children is None or part not in current.children:
            raise RuntimeError('父字段不存在或类型已改变，无法单独选择此字段')
        current = current.children[part]
    if not path or current.children is None: raise RuntimeError('此字段需按完整文件核对')
    # Preserve comments and formatting for scalar replacements.
    existing = current.children.get(path[-1])
    if existing is not None and value is not None:
        text = data.decode('utf-8')
        output = (text[:existing.start]+value+text[existing.end:]).encode('utf-8')
    else:
        def rebuild(node, depth):
            children = dict(node.children)
            part = path[depth]
            if depth == len(path)-1:
                if value is None: children.pop(part,None)
                else: children[part] = lua_sync.Node(value)
            else: children[part] = rebuild(children[part],depth+1)
            def label(k): return node.keys.get(k) or (k[1] if k[0]=='name' else '['+k[1]+']')
            return lua_sync.Node('{\n'+',\n'.join(label(k)+' = '+v.raw for k,v in children.items())+'\n}',children,node.keys)
        output = (prefix+rebuild(root,0).raw+suffix).encode('utf-8')
    lua_sync.parse(output)
    return output


def choose(core,folder,report,state,path,key,side):
    import staged_sync as staged
    if side not in (0,1,2): raise RuntimeError('无效的版本选择')
    load(core,folder,report,state,path)
    entry = state['items'][path]; cache = entry['textReview']
    choice = next((v for v in cache['choices'] if v['id']==key),None)
    if choice is None: raise RuntimeError('字段已变化，请刷新对比')
    candidate = staged.reviewed_bytes(folder,entry,'candidate','待合入')
    if candidate is None: raise RuntimeError('删除文件需按完整文件核对')
    output = replace_field(candidate,key,choice['values'][side])
    backup = staged.safe_path(folder/'字段选择前副本',path)
    backup.parent.mkdir(parents=True,exist_ok=True)
    backup = backup.with_name(backup.name+'.'+files.data_hash(candidate))
    if not backup.exists(): backup.write_bytes(candidate)
    destination = staged.safe_path(folder/'待合入',path)
    with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as handle:
        handle.write(output); temporary = pathlib.Path(handle.name)
    try: temporary.replace(destination)
    finally: temporary.unlink(missing_ok=True)
    cache['selected'][key] = side
    entry.pop('risk', None)
    entry['candidateHash'] = files.data_hash(output)
    entry['same'] = entry['candidateHash']==entry['baselineHash'] and entry['properties']==entry['beforeProperties']
    entry['summary'] += '\n字段选择：'+choice['label']+' → '+['Release','原待合入','源分支最新'][side]
    core.write_json(folder/'review.json',state)
    return entry


def verify_latest_choices(core, report, entry):
    cache = entry.get('textReview', {})
    selected = [v for v in cache.get('choices', []) if cache.get('selected', {}).get(v['id']) == 2]
    if not selected: return
    c = report['config']; revision = core.info(c['dev'], 'HEAD')['revision']
    data = read_version(core, core.urlpath(c['dev'],entry['path']),revision)
    try: current = fields(data)
    except (ValueError,IndexError): raise RuntimeError('源分支最新内容结构已变化，请重新合入并核对')
    for choice in selected:
        node = current.get(choice['id'])
        value = node[0].raw if node else None
        if value != choice['values'][2]:
            raise RuntimeError('所选字段的源分支最新值已变化，请重新合入并核对：'+choice['label'])
