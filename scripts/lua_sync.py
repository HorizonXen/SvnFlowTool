"""Merge generated Lua literal tables by keys without executing Lua code."""
import re
from dataclasses import dataclass

TOKEN = re.compile(r'\s+|--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|[A-Za-z_]\w*|.', re.S)
@dataclass
class Node:
    raw: str
    children: object = None
    keys: object = None
    start: int = 0
    end: int = 0
    entries: object = None
    def value(self):
        return {k:v.value() for k,v in self.children.items()} if self.children is not None else self.raw

def parse(data):
    text=data.decode('utf-8'); tokens=[m for m in TOKEN.finditer(text) if not m[0].isspace() and not m[0].startswith('--')]
    opening=next((i for i,m in enumerate(tokens) if m[0]=='{'),None)
    if opening is None: raise ValueError('非 Lua 数据表')
    i=opening
    def read():
        nonlocal i
        start=tokens[i].start();token=tokens[i][0];i+=1
        if token!='{':
            if not (token[0] in '\"\'' or token.startswith('[') or re.fullmatch(r'[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|true|false|nil',token)):
                raise ValueError('Lua 包含非字面量表达式：'+token)
            return Node(token, start=start, end=tokens[i-1].end())
        children={};keys={};entries={};auto=1
        while tokens[i][0]!='}':
            key_start=tokens[i].start()
            if tokens[i][0]=='[':
                i+=1; key=tokens[i][0];i+=1
                if tokens[i][0]!=']' or tokens[i+1][0]!='=':raise ValueError('Lua 键格式不支持')
                i+=2;label=text[key_start:tokens[i-1].start()].strip()
                key=('index',key)
            elif tokens[i+1][0]=='=':
                key=('name',tokens[i][0]);label=tokens[i][0];i+=2
            else:key=('index',str(auto));label='['+str(auto)+']';auto+=1
            if key in children:raise ValueError('Lua 存在重复键')
            children[key]=read();keys[key]=label
            if tokens[i][0] in (',',';'):i+=1
            elif tokens[i][0]!='}':raise ValueError('Lua 含表达式或缺少分隔符')
            entries[key]=(key_start,tokens[i-1].end())
        end=tokens[i].end();i+=1
        return Node(text[start:end],children,keys,start,end,entries)
    root=read()
    return text[:tokens[opening].start()],root,text[tokens[i-1].end():]

def merge(before,after,local,latest=False,history=()):
    parsed=[parse(v) for v in (before,after,local,*history)]
    def value(n):return n.value() if n is not None else None
    def patch(a,b,t,accepted=(),where='data'):
        av,bv,tv=map(value,(a,b,t))
        if tv==bv:return t
        if av==bv and not any(value(h)!=bv for h in accepted):return t
        if a is not None and b is not None and t is None:
            if not latest:raise ValueError('Lua 字段冲突：目标缺少已有字段，无法隔离源分支上下文：'+where)
            if a.children is not None and b.children is not None:
                t=Node('{}',{},{});tv={}
            else:return b
        if a is not None and b is not None and t is not None and all(n.children is not None for n in (a,b,t)):
            children=dict(t.children);keys=dict(t.keys)
            for key in dict.fromkeys([*a.children,*b.children,*(k for h in accepted if h and h.children is not None for k in h.children)]):
                result=patch(a.children.get(key),b.children.get(key),t.children.get(key),[h.children.get(key) if h and h.children is not None else None for h in accepted],where+'/'+str(key))
                if result is None:children.pop(key,None)
                else:children[key]=result;keys[key]=keys.get(key,b.keys.get(key))
            if {k:v.value() for k,v in children.items()}==tv:return t
            if t.entries is not None and (children.keys() == t.children.keys() or all('=' in t.raw[t.entries[k][0]-t.start:n.start-t.start] for k,n in t.children.items())):
                edits=[]
                for key, original in t.children.items():
                    if key not in children:
                        begin,end=t.entries[key]
                        edits.append((begin-t.start,end-t.start,''))
                    elif children[key].raw != original.raw:
                        edits.append((original.start-t.start,original.end-t.start,children[key].raw))
                added=[k for k in children if k not in t.children]
                if added:
                    retained=[k for k in t.children if k in children]
                    if retained:
                        last=retained[-1];node=t.children[last]
                        tail=t.raw[node.end-t.start:t.entries[last][1]-t.start]
                        if not tail.strip().endswith((',', ';')):
                            edits.append((node.end-t.start,node.end-t.start,','))
                    first=next(iter(t.entries.values()),(t.start+1,0))[0]-t.start
                    start=t.raw.rfind('\n',0,first)+1
                    indent=t.raw[start:first] if t.raw[start:first].isspace() else '    '
                    close=t.raw.rfind('}')
                    closing=t.raw[t.raw.rfind('\n',0,close)+1:close]
                    closing=closing if closing.isspace() else ''
                    insertion='\n'+''.join(indent+keys[k]+' = '+children[k].raw+',\n' for k in added)+closing
                    edits.append((close,close,insertion))
                raw=t.raw
                for begin,end,replacement in sorted(edits, key=lambda e:(e[0],e[1]), reverse=True):
                    raw=raw[:begin]+replacement+raw[end:]
                return Node(raw,children,keys,t.start,t.end)
            return Node('{\n'+',\n'.join(keys[k]+' = '+v.raw for k,v in children.items())+'\n}',children,keys)
        if av==bv and not any(tv==value(h) for h in accepted):return t
        def string(node):
            return node is not None and node.children is None and (node.raw.startswith(('"', "'")) or re.match(r'\[(=*)\[',node.raw))
        if not latest and all(string(node) for node in (a,b,t)):
            from file_sync import merge_text
            raw=merge_text(a.raw.encode(),b.raw.encode(),t.raw.encode(),latest,[h.raw.encode() for h in accepted if string(h)]).decode()
            return Node(raw)
        if tv==av or any(tv==value(h) for h in accepted) or latest:return b
        raise ValueError('Lua 字段冲突：'+where)
    result=patch(parsed[0][1],parsed[1][1],parsed[2][1],[p[1] for p in parsed[3:]])
    # Generated table wrappers contain code; don't copy changed executable context.
    if parsed[0][0]!=parsed[1][0] or parsed[0][2]!=parsed[1][2]:
        from file_sync import merge_text
        prefix=merge_text(parsed[0][0].encode(),parsed[1][0].encode(),parsed[2][0].encode(),latest).decode()
        suffix=merge_text(parsed[0][2].encode(),parsed[1][2].encode(),parsed[2][2].encode(),latest).decode()
    else:prefix,suffix=parsed[2][0],parsed[2][2]
    output=(prefix+result.raw+suffix).encode()
    parse(output)
    return output
