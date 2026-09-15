"""Checksummed cache of immutable SVN file revisions; author checks stay live."""
import contextlib,hashlib,json,os,pathlib,subprocess,tempfile,time

@contextlib.contextmanager
def reads(core,root,uuid):
    if not uuid:
        yield;return
    root=pathlib.Path(root)/hashlib.sha256(uuid.encode()).hexdigest();original=core.run
    def run(*args,**kwargs):
        values=list(map(str,args));eligible=values and values[0] in ('cat','proplist','info') and '-r' in values
        rev=values[values.index('-r')+1] if eligible else ''
        eligible=eligible and '--revprop' not in values and rev.isdigit() and values[-1].endswith('@'+rev) and '://' in values[-1]
        if not eligible:return original(*args,**kwargs)
        key=hashlib.sha256(json.dumps(values).encode()).hexdigest();path=root/key
        try:
            stored=path.read_bytes();checksum,data=stored[:64],stored[65:]
            if stored[64:65]==b'\n' and checksum==hashlib.sha256(data).hexdigest().encode():
                if getattr(core,'sync_phase',None):core.sync_phase('复用历史版本缓存 · r'+rev)
                return subprocess.CompletedProcess(values,0,data,b'')
        except OSError:pass
        result=original(*args,**kwargs)
        if result.returncode==0:
            temporary=None
            try:
                root.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=root,delete=False) as out:
                    temporary=pathlib.Path(out.name);out.write(hashlib.sha256(result.stdout).hexdigest().encode()+b'\n'+result.stdout)
                os.replace(temporary,path)
                marker=root/'.pruned'
                if not marker.exists() or time.time()-marker.stat().st_mtime>=30:
                    marker.touch()
                    files=sorted((p for p in root.iterdir() if len(p.name)==64),key=lambda p:p.stat().st_mtime)
                    total=sum(p.stat().st_size for p in files)
                    for old in files:
                        if total<=2*1024**3:break
                        size=old.stat().st_size;old.unlink();total-=size
            except OSError:pass
            finally:
                if temporary is not None:
                    try:temporary.unlink(missing_ok=True)
                    except OSError:pass
        return result
    core.run=run
    try:yield
    finally:core.run=original

def prefetch(core,folder,path):
    report=json.loads((folder/'report.json').read_text());config=core.verify_config(report)
    item=next(i for i in report['fileItems'] if i['path']==path);source=core.urlpath(config['dev'],path)
    with reads(core,folder.parent/'历史缓存',config.get('uuid')):
        for rev in sorted({v for r in item['revisions'] for v in (r-1,r)}):
            core.run('cat','-r',rev,'--',source+'@'+str(rev),check=False)
    return {'prefetched':path}
