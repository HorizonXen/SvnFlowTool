"""Merge flat Unity interactionObjs lists by ID and field.

Only this known serialized shape is supported. Unsupported nested fields, duplicate
IDs and changes outside the list stop for review rather than falling back to line
matching. A new source object owns its declared fields; an existing target object
must match id, interactiveId and objectType before those fields can be applied.
"""
import re
from decimal import Decimal, InvalidOperation

RULE_VERSION = 1


def supports(path):
    return path.lower().endswith('.asset') and '/config/galaxy/' in '/' + path.lower()


SECTION = re.compile(r'^  interactionObjs:(?: \[\])?\r?\n', re.M)
FIELD = re.compile(r'^    ([A-Za-z_]\w*):', re.M)


def scalar(v):
    v=v.strip()
    try:return ('number', Decimal(v))
    except InvalidOperation:return ('literal',v)


def flow(v):
    v=v.strip()
    if not (v.startswith('{') and v.endswith('}')):return None
    result={}
    for part in v[1:-1].split(','):
        m=re.fullmatch(r'\s*([A-Za-z_]\w*):\s*([^{}:,]+)\s*',part)
        if not m or m[1] in result:return None
        result[m[1]]=m[2].strip()
    return result


def equal(a,b):
    if a is None or b is None:return a==b
    x,y=flow(a),flow(b)
    return ({k:scalar(v) for k,v in x.items()}=={k:scalar(v) for k,v in y.items()}) if x is not None and y is not None else scalar(a)==scalar(b)


def fields(block):
    normalized='    '+block[4:]
    matches=list(FIELD.finditer(normalized));result={}
    if not matches or matches[0].start()!=0:raise ValueError('星系对象字段格式无法识别')
    for i,m in enumerate(matches):
        if m[1] in result:raise ValueError('星系对象存在重复字段：'+m[1])
        end=matches[i+1].start() if i+1<len(matches) else len(normalized)
        value=normalized[m.end():end]
        if value.lstrip().startswith(('&','*','!')):raise ValueError('星系对象字段包含不支持的 YAML 引用或标签')
        if '\n' in value.strip() and flow(value) is None:raise ValueError('星系对象包含不支持的多行字段：'+m[1])
        result[m[1]]=value
    if 'id' not in result or not re.fullmatch(r'\d+',result['id'].strip()):raise ValueError('星系对象缺少有效 id')
    return result


def parse(data):
    text=data.decode('utf-8');matches=list(SECTION.finditer(text))
    if len(matches)!=1:raise ValueError('需要唯一的 interactionObjs 列表')
    m=matches[0];tail=re.search(r'^  [A-Za-z_]\w*:',text[m.end():],re.M)
    end=m.end()+tail.start() if tail else len(text)
    body=text[m.end():end];starts=list(re.finditer(r'^  - ',body,re.M));items={}
    if body and (not starts or starts[0].start()!=0):raise ValueError('星系对象列表格式无法识别')
    for i,s in enumerate(starts):
        block=body[s.start():starts[i+1].start() if i+1<len(starts) else len(body)]
        f=fields(block);key=f['id'].strip()
        if key in items:raise ValueError('星系对象存在重复 ID：'+key)
        items[key]=(block,f)
    return text[:m.start()],text[end:],items


def merge_field(a,b,t,latest):
    if equal(a,b) or equal(t,b):return t
    af,bf,tf=flow(a or ''),flow(b or ''),flow(t or '')
    if af is not None and bf is not None and tf is not None and af.keys()==bf.keys()==tf.keys():
        result=dict(tf)
        for k in af:
            if scalar(af[k])!=scalar(bf[k]):
                if not latest and scalar(tf[k]) not in (scalar(af[k]),scalar(bf[k])):raise ValueError('星系对象字段冲突：'+k)
                result[k]=bf[k]
        return ' {'+', '.join(k+': '+v for k,v in result.items())+'}\n'
    if equal(t,a):return b
    if not latest:raise ValueError('星系对象字段冲突')
    return b


def merge(before,after,local,latest=False,history=()):
    bp,bs,b=parse(before);ap,ass,a=parse(after);tp,ts,t=parse(local)
    if bp!=ap or bs!=ass:raise ValueError('作者还修改了 interactionObjs 以外内容，需要单独核对')
    output=dict(t)
    for key in dict.fromkeys([*b,*a]):
        old,new=b.get(key),a.get(key);current=t.get(key)
        if old is not None and new is not None and all(equal(old[1].get(k),new[1].get(k)) for k in old[1].keys()|new[1].keys()):continue
        if new is None:
            if not latest and current is not None and current[1]!=old[1]:raise ValueError('删除对象与 Release 冲突：'+key)
            output.pop(key,None);continue
        if old is None:
            if current is not None and not all(equal(current[1].get(k),new[1].get(k)) for k in current[1].keys()|new[1].keys()):
                identity=('id','interactiveId','objectType')
                if not latest or not all(k in new[1] and k in current[1] and equal(new[1][k],current[1][k]) for k in identity):
                    raise ValueError('新增对象 ID 已被 Release 占用：'+key)
                f=dict(current[1]);f.update(new[1])
                block=''.join('    '+k+':'+v for k,v in f.items());output[key]=('  - '+block[4:],f)
            else:output[key]=current or new
            continue
        if current is None:raise ValueError('Release 缺少作者修改的对象 ID：'+key)
        f=dict(current[1])
        for k in dict.fromkeys([*old[1],*new[1]]):
            if equal(old[1].get(k),new[1].get(k)):continue
            if k not in f and k in old[1] and k in new[1]:raise ValueError('Release 缺少已修改字段：'+key+'/'+k)
            v=merge_field(old[1].get(k),new[1].get(k),f.get(k),latest)
            if v is None:f.pop(k,None)
            else:f[k]=v
        block=''.join('    '+k+':'+v for k,v in f.items());block='  - '+block[4:]
        output[key]=(block,f)
    header='  interactionObjs:\n' if output else '  interactionObjs: []\n'
    result=(tp+header+''.join(v[0] for v in output.values())+ts).encode('utf-8')
    parse(result)
    return result
