#!/usr/bin/env python3
"""Exact-author revision migration with conservative OOXML three-way patches."""
import re, tempfile, contextlib, sys
sys.dont_write_bytecode = True
from workbook_sync import patch_workbook
import file_sync
import argparse, concurrent.futures, datetime as dt, hashlib, json, os, pathlib, subprocess, sys, urllib.parse, xml.etree.ElementTree as ET
from platform_lock import try_lock
from platform_settings import endpoint_name, fixed_copies, merge_copies

SVN = next((p for p in ['/opt/homebrew/bin/svn','/usr/local/bin/svn','/usr/bin/svn'] if os.path.isfile(p)), 'svn')
ENV = dict(os.environ, LC_ALL='en_US.UTF-8', LANGUAGE='en')
def run(*args, check=True, timeout=180):
    p = subprocess.run([SVN,'--non-interactive',*map(str,args)],capture_output=True,env=ENV,timeout=timeout)
    if check and p.returncode: raise RuntimeError(p.stderr.decode('utf-8','replace')[-8000:])
    return p

def info(target, revision=None):
    args=['info','--xml'] + (['-r',str(revision)] if revision else []) + ['--',target+'@']
    e=ET.fromstring(run(*args).stdout).find('entry')
    return {'url':e.findtext('url'),'root':e.findtext('repository/root'),'uuid':e.findtext('repository/uuid'),'revision':int(e.attrib['revision'])}
def load_config():
    dev,rel=merge_copies()
    d=info(dev['path']); r=info(rel['path']); target=rel['path']
    # Branch directory names differ. Align the path *inside* each SVN branch,
    # never append the Dev branch name to the Release working copy.
    def branch_tail(metadata):
        parts=urllib.parse.unquote(metadata['url'][len(metadata['root']):]).strip('/').split('/')
        for i in range(len(parts)-2):
            if parts[i].lower() == 'branch' and parts[i+1].lower() in ('dev','release','hotfix'):
                return parts[i+3:]
        return None
    left,right=branch_tail(d),branch_tail(r)
    if left is not None and right is not None and left != right:
        if left[:len(right)] != right: raise RuntimeError('Dev/Release 配置的分支内目录不对应，请重新配置。')
        target=str(pathlib.Path(target).joinpath(*left[len(right):])); r=info(target)
    if d['uuid'] != r['uuid'] or d['url']==r['url']: raise RuntimeError('Dev 和 Release 必须是同一仓库中的不同分支。')
    return {'dev':d['url'],'release':r['url'],'target':target,'root':d['root'],'uuid':d['uuid'],
            'sourceName':endpoint_name(dev['path'],'源目录'),'targetName':endpoint_name(target,'目标目录')}
def logs(url,start,end):
    return ET.fromstring(run('log','--xml','-v','-r',f'{{{start}}}:{{{end}}}',url+'@').stdout)
def authors_in_range(tree,start,end):
    # SVN date revisions may include the revision just before the lower bound.
    authors=set()
    for entry in tree.findall('logentry'):
        author=entry.findtext('author')
        try: date=dt.datetime.fromisoformat(entry.findtext('date','').replace('Z','+00:00'))
        except ValueError: continue
        if author and date.tzinfo is not None and start <= date <= end: authors.add(author)
    return sorted(authors)
def relpath(path,url,root):
    prefix=urllib.parse.unquote(url[len(root):]).rstrip('/')
    return path[len(prefix)+1:] if path.startswith(prefix+'/') else ('' if path==prefix else None)
def records(tree,url,root,author,start,end):
    result=[]
    for e in tree.findall('logentry'):
        if e.findtext('author')!=author or not(start <= e.findtext('date','') <= end):continue
        paths=[];outside=[]
        for p in e.findall('paths/path'):
            relative=relpath(p.text,url,root)
            if relative is None:outside.append(p.text);continue
            paths.append({'path':relative,'action':p.get('action'),'kind':p.get('kind',''),'copyFrom':p.get('copyfrom-path','')})
        if paths:result.append({'revision':int(e.get('revision')),'date':e.findtext('date'),'message':e.findtext('msg',''),'paths':paths,'outsideScope':outside})
    return sorted(result,key=lambda x:x['revision'])
def urlpath(root,path):return root.rstrip('/')+'/'+urllib.parse.quote(path,safe='/')
def content(url,revision):
    p=run('cat','-r',revision,'--',url+'@'+str(revision),check=False)
    if p.returncode:
        diagnostic=p.stderr.decode('utf-8','replace')
        if 'E200009' in diagnostic:
            q=run('info','--xml','-r',revision,'--',url+'@'+str(revision),check=False)
            if not q.returncode and ET.fromstring(q.stdout).find('entry').get('kind')=='dir':
                props=run('proplist','--xml','--verbose','-r',revision,'--',url+'@'+str(revision))
                values=sorted((e.get('name'),e.text or '') for e in ET.fromstring(props.stdout).findall('.//property'))
                return {'state':'directory','properties':values,'sha256':hashlib.sha256(json.dumps(values).encode()).hexdigest()}
        if any(code in diagnostic for code in ['E160013','W160013']):return {'state':'missing','error':diagnostic[-350:]}
        return {'state':'error','error':diagnostic[-500:]}
    return {'state':'file','sha256':hashlib.sha256(p.stdout).hexdigest(),'bytes':len(p.stdout)}
def audit(folder,author,days=30):
    if not author.strip() or author != author.strip(): raise RuntimeError('请输入精确的 SVN 作者账号。')
    if not 1 <= days <= 365: raise RuntimeError('查询天数必须在 1 至 365 之间。')
    folder.mkdir(parents=True,exist_ok=True)
    config=load_config(); end=dt.datetime.now(dt.timezone.utc);start=end-dt.timedelta(days=days)
    stamp=lambda v:v.strftime('%Y-%m-%dT%H:%M:%SZ')
    start,end=stamp(start),stamp(end)
    config.update(author=author,start=start,end=end,days=days)
    config['snapshot']=info(config['dev'],'{'+end+'}')['revision']
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        trees=list(pool.map(lambda role:logs(config[role],start,end),['dev','release']))
    for role,tree in zip(['dev','release'],trees):
        (folder/(role+'-log.xml')).write_bytes(ET.tostring(tree,encoding='utf-8'))
    dev=records(trees[0],config['dev'],config['root'],author,start,end); release=records(trees[1],config['release'],config['root'],author,start,end)
    merged=set();mergeError=''
    if dev:
        m=run('mergeinfo','--show-revs','merged','-r',f"{dev[0]['revision']}:{dev[-1]['revision']}",config['dev']+'@'+str(config['snapshot']),config['release']+'@'+str(config['snapshot']),check=False)
        if m.returncode:mergeError=m.stderr.decode('utf-8','replace')
        else:merged={int(line[1:]) for line in m.stdout.decode().splitlines() if line.startswith('r') and line[1:].isdigit()}
    paths=sorted({p['path'] for record in dev+release for p in record['paths'] if p['path']})
    files={}
    def compare(path):
        a=content(urlpath(config['dev'],path),config['snapshot']);b=content(urlpath(config['release'],path),config['snapshot'])
        return path,{'dev':a,'release':b,'equal':a['state'] in ('file','directory') and a['state']==b['state'] and a['sha256']==b['sha256'],'binary':path.lower().endswith(('.xlsx','.xlsm','.xls','.png','.bin','.bytes','.zip'))}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for i,(path,value) in enumerate(pool.map(compare,paths)):
            files[path]=value
            if i%20==0:print(f'核对文件 {i+1}/{len(paths)}',file=sys.stderr,flush=True)
    for record in dev:
        record['mergeRecorded']=record['revision'] in merged
        record['differentPaths']=[p['path'] for p in record['paths'] if not files.get(p['path'],{}).get('equal')]
        record['relatedRelease']=[r['revision'] for r in release if {p['path'] for p in r['paths']} & {p['path'] for p in record['paths']}]
        record['status']='已记录合并' if record['mergeRecorded'] else ('当前文件内容相同' if not record['differentPaths'] else '待核对同步')
    report={'schema':2,'config':config,'dev':dev,'release':release,'files':files,'fileItems':file_sync.group_files(dev),'directoryChangeCount':len({p['path'] for r in dev for p in r['paths'] if p.get('kind')=='dir'}),'mergeInfoError':mergeError}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    render(report,folder)
    print(str(folder/'report.json'))
    return report

def render(report,folder):
    c=report['config']; items=report.get('fileItems',file_sync.group_files(report['dev']))
    lines=[f"# {c['author']} · Dev → Release 文件迁移报告",'',
           f"时间：{c['start']} 至 {c['end']}（UTC）；仓库快照 r{c['snapshot']}。",'',
           f"Dev：`{c['dev']}`",f"Release：`{c['release']}`",'',
           f"目标作者的 {len(report['dev'])} 次提交汇总为 **{len(items)} 个文件**；同一文件只显示、确认一次。",'',
           '以所选作者提交确定改动位置，这些位置取本批 Dev 最新快照的值，包括其他人的后续修改；其余位置保留 Release 内容。提交版本仅供追溯，不按版本逐项执行；最终内容已相同的文件不重复修改。', '',
           '## 文件清单', '', '| 文件 | 最新提交 | 汇总提交版本 | 最新说明 |', '|---|---|---|---|']
    for item in items:
        versions=', '.join('r'+str(r) for r in item['revisions'])
        message=item['message'].replace('|','/').replace('\n',' ')
        lines.append(f"| {item['path'].replace('|','/')} | r{item['latestRevision']} | {versions} | {message} |")
    directories=sorted({p['path'] for r in report['dev'] for p in r['paths'] if p.get('kind')=='dir'})
    if directories:
        lines+=['','## 目录变化（需单独核对）',''] + ['- '+(p or '分支根目录') for p in directories]
    lines+=['','## 使用方式','',
            '准备 Release 后，可任意选择文件预演。预演显示汇总后的最终结果；确认同步只修改该文件。结果相同会记录为“内容相同”。版本记录保留在报告中，不写入整条修订的合并标记。最终统一检查本地变化并手动提交。', '',
            'Excel 支持汇总已提交的删表、公式转值和单元格变化。无法隔离的依赖、复制历史、目录依赖以及与 Release 的冲突会停止该文件；不会复制夹带其他作者内容的 Dev 最新整文件。未修改或操作失败的其他文件不受影响。']
    if report.get('mergeInfoError'): lines+=['','历史合并记录读取提示：'+report['mergeInfoError']]
    (folder/'差异报告.md').write_text('\n'.join(lines))

def write_json(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)
def fingerprint(target, paths=None):
    arguments = ['status', '--xml']
    if paths is not None: arguments += ['--depth', 'empty']
    arguments += ['--'] + [str(p)+'@' for p in (paths if paths is not None else [target])]
    tree=ET.fromstring(run(*arguments).stdout)
    entries=[]
    for e in tree.findall('.//entry'):
        status=e.find('wc-status'); path=e.get('path'); item=status.get('item');props=status.get('props')
        if item in ('normal','none','ignored','external') and props in ('none','normal'):continue
        entry={'path':path,'item':item,'props':props}
        if item in ('conflicted','obstructed','incomplete','missing') or status.get('tree-conflicted')=='true':raise RuntimeError('Release 有冲突或缺失项，请先处理：'+path)
        p=pathlib.Path(path)
        if p.is_file():entry['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():entry['children']=sorted(v.name for v in p.iterdir()) if item=='unversioned' else []
        entry['properties']=hashlib.sha256(run('proplist','--xml','--verbose','--',path+'@',check=False).stdout).hexdigest()
        entries.append(entry)
    return sorted(entries,key=lambda e:e['path'])
def verify_config(report):
    c=report['config']; live=load_config()
    for key in ['dev','release','target','uuid']:
        if live[key]!=c[key]:raise RuntimeError('Dev/Release 配置已改变，请重新生成报告。')
    return c

def load_workspace_export_config(target):
    """Bind a local export to one configured copy, without requiring a merge round."""
    root = pathlib.Path(target).resolve()
    copies = fixed_copies()
    if not any(pathlib.Path(c['path']).resolve() == root for c in copies):
        raise RuntimeError('导出目标已不在工作副本配置中，请返回目录重新选择 Excel。')
    identity = info(str(root))
    return dict(target=str(root), url=identity['url'], uuid=identity['uuid'])

def same_repository_url(left, right):
    # Compare decoded path segments once: SVN and urllib escape punctuation
    # differently. Keep separators and literal percent signs significant.
    def identity(value):
        u=urllib.parse.urlsplit(value)
        return (u.scheme, u.netloc, tuple(urllib.parse.unquote(segment) for segment in u.path.split('/')), u.query, u.fragment)
    return identity(left) == identity(right)

def validate_inventory(inventory, config):
    for entry in inventory.findall('entry'):
        local_path=pathlib.Path(entry.get('path')).absolute()
        relative=os.path.relpath(local_path,config['target'])
        if relative == '..' or relative.startswith('..'+os.sep):
            raise RuntimeError('SVN 返回了目标目录外的路径：'+str(local_path))
        expected=urlpath(config['release'],relative) if relative != '.' else config['release']
        if not same_repository_url(entry.findtext('url',''), expected):
            raise RuntimeError('Release 路径指向其他仓库位置（切换），请先核对：'+str(local_path))
        depth=entry.findtext('wc-info/depth')
        if entry.get('kind') == 'dir' and depth not in (None,'infinity'):
            raise RuntimeError('Release 目录未完整检出（深度 '+depth+'），请先核对：'+str(local_path))

def operate(folder,action,revision=None,file_path=None,resolve_author=False):
    folder.mkdir(parents=True,exist_ok=True)
    with contextlib.ExitStack() as locks:
        lock = locks.enter_context((folder/'operation.lock').open('w'))
        try:try_lock(lock)
        except BlockingIOError:raise RuntimeError('同步操作正在执行，请等待。')
        report=json.loads((folder/'report.json').read_text()); c=verify_config(report); ledger=folder/'session.json'
        identity = hashlib.sha256(str(pathlib.Path(c['target']).resolve()).encode()).hexdigest()
        target_lock = locks.enter_context((pathlib.Path(tempfile.gettempdir()) / ('svnflow-sync-' + identity + '.lock')).open('a'))
        try: try_lock(target_lock)
        except BlockingIOError: raise RuntimeError('同一个 Release 正在执行另一批同步，请等待。')
        if action=='prepare':
            inventory=ET.fromstring(run('info','--xml','--depth','infinity','--',c['target']+'@',timeout=600).stdout)
            validate_inventory(inventory,c)
            if ledger.exists():raise RuntimeError('已有同步会话，请先检查并提交已有合并结果；不要重复准备。')
            if fingerprint(c['target']):raise RuntimeError('Release 存在本地改动。为保留这些改动，请先提交或另行保存后再准备同步。')
            # Never silently rewind newer working-copy revisions.
            versions=inventory
            if any(int(e.get('revision','0'))>c['snapshot'] for e in versions.findall('entry')):raise RuntimeError('Release 工作副本比报告更新，请重新生成报告。')
            write_json(ledger,{'snapshot':c['snapshot'],'pending':'prepare','done':[]})
            result=run('update','--ignore-externals','-r',c['snapshot'],'--accept','postpone','--',c['target']+'@',timeout=1800)
            after=fingerprint(c['target'])
            if after:raise RuntimeError('更新后出现本地变化，请检查现场，已暂停同步。')
            state={'snapshot':c['snapshot'],'done':[],'fingerprint':after}
            if 'fileItems' in report: state.update(mode='files-v2',doneFiles=[],reportHash=file_sync.report_hash(report))
            write_json(ledger,state)
            print('Release 已准备好，可选择文件预演并确认合并后的最终内容。\n'+result.stdout.decode('utf-8','replace'));return
        if not ledger.exists():raise RuntimeError('请先点击“准备 Release”。')
        state=json.loads(ledger.read_text())
        if state.get('pending'):raise RuntimeError('上次操作未完整结束，已停止自动重试。请检查 Release 和同步会话记录。')
        if state['snapshot']!=c['snapshot']:raise RuntimeError('报告已变化，请先处理旧会话。')
        current=fingerprint(c['target'])
        if current!=state['fingerprint']:raise RuntimeError('Release 在上次操作后被修改，已暂停以保护人工改动。')
        if action == 'verify':
            import types
            return file_sync.verify_results(types.SimpleNamespace(**globals()), folder, report, state)
        if 'fileItems' in report or file_path is not None:
            # Pass the running core module without importing a duplicate __main__.
            import types
            core = types.SimpleNamespace(**globals())
            core.sync_progress = lambda path,revision: write_json(folder/'progress.json', {'path':path, 'revision':revision})
            return file_sync.operate_prepared(core,folder,report,state,current,action,file_path,resolve_author=resolve_author)
        record=next((r for r in report['dev'] if r['revision']==revision),None)
        if not record or revision in state['done']:raise RuntimeError('修订无效或已经处理。')
        candidates=[r['revision'] for r in report['dev'] if not r['mergeRecorded'] and r['revision'] not in state['done']]
        if not candidates or revision!=min(candidates):raise RuntimeError('请按列表从旧到新处理，避免漏掉前置依赖。')
        if action=='skip':
            state['done'].append(revision);state.setdefault('skipped',[]).append(revision);write_json(ledger,state);print('已跳过 r'+str(revision));return
        if record['outsideScope']:raise RuntimeError('此提交含 Client 范围外修改，请核对依赖后跳过或单独处理。')
        # Always derive scope from the repository, never trust editable report paths.
        e=ET.fromstring(run('log','--xml','-v','-r',revision,c['dev']+'@'+str(c['snapshot'])).stdout).find('logentry')
        if e is None or e.findtext('author')!=c['author']:raise RuntimeError('修订作者校验失败。')
        excel = {}
        notes = []
        root = info(c['dev'])['root']
        if report.get('mergeInfoError'): raise RuntimeError('合并记录读取失败，请重新生成报告。')
        for changed in e.findall('paths/path'):
            path = relpath(changed.text, c['dev'], root)
            if path is None: raise RuntimeError('提交含 Dev 范围外修改，已停止迁移。')
            if changed.get('copyfrom-path') or changed.get('action') == 'R':
                raise RuntimeError('复制、移动或替换路径可能带入其他作者历史，需单独核对：' + path)
            if changed.get('kind') == 'dir' and changed.get('action') == 'D':
                raise RuntimeError('目录删除需要核对整个子树，已停止迁移：' + path)
            target = pathlib.Path(c['target']) / path
            if '..' in pathlib.PurePosixPath(path).parts or target.resolve() != pathlib.Path(c['target']).resolve() / path:
                raise RuntimeError('路径越界或含符号链接，已停止迁移：' + path)
            source = urlpath(c['dev'], path) if path else c['dev']
            # A selected author's merge commit can itself include other authors' work.
            props = []
            for rev in (revision-1, revision):
                if (changed.get('action') == 'A' and rev == revision-1) or (changed.get('action') == 'D' and rev == revision):
                    props.append(b''); continue
                result = run('propget', 'svn:mergeinfo', '-r', rev, '--', source+'@'+str(rev), check=False)
                if result.returncode and not any(code in result.stderr.decode('utf-8','replace') for code in ('W200017','E160013','W160013')):
                    raise RuntimeError('无法核对合并来源：' + path)
                props.append(result.stdout)
            if props[0] != props[1]: raise RuntimeError('此修订包含分支合并记录，可能夹带其他作者修改：' + path)
            if changed.get('action') == 'M' and path.lower().endswith(('.xlsx','.xlsm')):
                if not target.is_file(): raise RuntimeError('Release 缺少 Excel：' + path)
                before = run('cat','-r',revision-1,'--',source+'@'+str(revision-1)).stdout
                after = run('cat','-r',revision,'--',source+'@'+str(revision)).stdout
                try: data, detail = patch_workbook(before, after, target.read_bytes())
                except Exception as error: raise RuntimeError('Excel 无法安全迁移 '+path+'：'+str(error)) from error
                excel[str(target)] = data
                notes.extend([path + '：' + line for line in detail])
        args=['merge','--accept','postpone','-c',revision,c['dev']+'@'+str(c['snapshot']),c['target']]
        dry=run(*args[:1],'--dry-run',*args[1:],check=False,timeout=600)
        output=dry.stdout.decode('utf-8','replace')+dry.stderr.decode('utf-8','replace')
        def blocked_output(output):
            for line in output.splitlines():
                if line.startswith('Skipped') or re.match(r'^  (Tree|Property) conflicts: [1-9]', line): return True
                if re.match(r'^[ A-Z!?~+]{4} ', line) and 'C' in line[:4]:
                    # Only the binary content conflict for an already verified workbook is expected.
                    if line[:4] != 'C   ' or line[5:].strip() not in excel: return True
            return False
        if dry.returncode or blocked_output(output):raise RuntimeError('预演发现冲突/跳过路径，未写入 Release：\n'+output)
        output += '\nExcel 定向迁移：\n' + '\n'.join(notes) if excel else ''
        if action=='preview':print(output or '预演没有文件变化。');return
        # Recheck local changes after network reads and before any writes.
        if fingerprint(c['target']) != current: raise RuntimeError('预演期间 Release 被修改，已停止。')
        state['pending']=revision;write_json(ledger,state)
        result=run(*args,check=False,timeout=1800)
        actual=(result.stdout+result.stderr).decode('utf-8','replace')
        (folder/f'merge-r{revision}.log').write_text(actual+'\n'+'\n'.join(notes))
        if result.returncode or blocked_output(actual):raise RuntimeError('合并未成功完成，请检查 Release；未自动回滚或重试。\n'+actual)
        for path, data in excel.items():
            pathlib.Path(path).write_bytes(data)
            status=ET.fromstring(run('status','--xml','--',path+'@').stdout).find('.//wc-status')
            if status is not None and status.get('item') == 'conflicted':
                run('resolve','--accept','working','--',path+'@')
        state['fingerprint']=fingerprint(c['target']);state.pop('pending');state['done'].append(revision);write_json(ledger,state)
        print('已将 r'+str(revision)+' 合并到本地 Release，尚未提交。\n'+result.stdout.decode('utf-8','replace'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['xtools-local-init','xtools-export','xtools-local-export','xtools-local-prepare','xtools-local-publish','xtools-local-resume','xtools-prepare','xtools-publish','xtools-resume','prefetch','authors','audit','prepare','preview','apply','skip','verify','scope-preview','scope-check','catalog','stage','regenerate','assess','accept-low','accept','defer','withdraw-row','text-review','choose-text','remaining-diff','repair-review']);parser.add_argument('--folder',required=True,type=pathlib.Path);parser.add_argument('--author');parser.add_argument('--days',type=int,default=30);parser.add_argument('--path');parser.add_argument('--confirm',action='store_true');parser.add_argument('--resolve-author',action='store_true');parser.add_argument('--sheet');parser.add_argument('--row',type=int);parser.add_argument('--review-hash');parser.add_argument('--workbook',action='append');parser.add_argument('--verify-path',action='append');parser.add_argument('--scope-directory',action='append');parser.add_argument('--scope-revision',type=int,action='append');parser.add_argument('--scope-preview',type=pathlib.Path);args=parser.parse_args()
    try:
        from sync_progress import SyncProgress, SyncCancelled
        activity = SyncProgress(args.folder, args.action, args.path)
        run = activity.wrap(run)
        if args.action == 'xtools-local-init':
            if not args.path:
                raise RuntimeError('缺少导出工作副本路径')
            import xtools_export, types
            xtools_export.initialize_workspace(types.SimpleNamespace(**globals()), args.folder, args.path)
            print('{}')
        elif args.action in ('xtools-export', 'xtools-local-export'):
            if not args.confirm:
                raise RuntimeError('导出操作需要明确授权写入本地目录')
            import xtools_export, types
            print(json.dumps(xtools_export.export(types.SimpleNamespace(**globals()), args.folder, args.workbook, local=args.action == 'xtools-local-export'), ensure_ascii=False))
        elif args.action in ('xtools-prepare', 'xtools-local-prepare'):
            import xtools_export, types
            print(json.dumps(xtools_export.prepare(types.SimpleNamespace(**globals()), args.folder, args.workbook, local=args.action == 'xtools-local-prepare'), ensure_ascii=False))
        elif args.action in ('xtools-publish', 'xtools-resume', 'xtools-local-publish', 'xtools-local-resume'):
            if not args.confirm or not args.review_hash:
                raise RuntimeError('发布必须确认当前候选及其审核哈希')
            import xtools_export, types
            print(json.dumps(xtools_export.publish(types.SimpleNamespace(**globals()), args.folder, args.review_hash, resume=args.action.endswith('-resume'), local=args.action.startswith('xtools-local-')), ensure_ascii=False))
        elif args.action in ('scope-preview','scope-check','catalog','stage','regenerate','assess','accept-low','accept','defer','withdraw-row','text-review','choose-text','remaining-diff','repair-review'):
            import staged_sync, types
            core = types.SimpleNamespace(**globals())
            core.sync_progress = activity.revision
            core.sync_phase = activity.phase
            core.sync_files = activity.files
            core.sync_item = activity.item
            core.sync_remaining = activity.remaining
            core.sync_metrics = activity.metrics
            if args.action == 'remaining-diff': print(json.dumps(staged_sync.remaining_diff(core,args.folder,args.verify_path if args.verify_path is not None else ([args.path] if args.path else None)),ensure_ascii=False))
            elif args.action == 'repair-review': print(json.dumps(staged_sync.repair_review(core,args.folder),ensure_ascii=False))
            elif args.action == 'scope-preview':
                result = staged_sync.scope_preview(core, args.author or '', args.days)
                core.write_json(args.folder/'scope-preview.json', result)
                print(json.dumps(result, ensure_ascii=False))
            elif args.action == 'scope-check':
                print(json.dumps(staged_sync.scope_check(core,args.folder,args.author or '',args.days,args.scope_directory,args.scope_preview,args.scope_revision),ensure_ascii=False))
            elif args.action == 'catalog': staged_sync.catalog(core,args.folder,args.author or '',args.days,args.scope_directory,args.scope_preview,args.scope_revision)
            else:
                if args.action in ('accept','accept-low') and not args.confirm: raise RuntimeError('请先在对比窗口确认此文件')
                print(json.dumps(staged_sync.operate(core,args.folder,args.action,args.path,sheet=args.sheet,row=args.row),ensure_ascii=False))
        elif args.action=='prefetch':
            import revision_cache,types
            print(json.dumps(revision_cache.prefetch(types.SimpleNamespace(**globals()),args.folder,args.path)))
        elif args.action=='authors':
            if not 1 <= args.days <= 365: raise ValueError('查询天数须为1—365之间的整数')
            c=load_config();end=dt.datetime.now(dt.timezone.utc);start=end-dt.timedelta(days=args.days)
            tree=logs(c['dev'],start.strftime('%Y-%m-%dT%H:%M:%SZ'),end.strftime('%Y-%m-%dT%H:%M:%SZ'))
            print(json.dumps(authors_in_range(tree,start,end),ensure_ascii=False))
        elif args.action=='audit':
            if (args.folder/'session.json').exists():raise RuntimeError('已有同步会话，请保留本报告并使用新目录生成报告。')
            audit(args.folder,args.author or '',args.days)
        else:
            if args.action in ['prepare','apply','skip'] and not args.confirm:raise RuntimeError('写入/跳过操作需要用户明确确认。')
            if 'fileItems' not in json.loads((args.folder/'report.json').read_text()): raise RuntimeError('请重新生成按文件汇总的报告。')
            operate(args.folder,args.action,file_path=args.path,resolve_author=args.resolve_author)
        activity.finish()
    except (Exception, SyncCancelled) as e:
        if 'activity' in locals():activity.finish(e)
        print(str(e),file=sys.stderr);sys.exit(1)
