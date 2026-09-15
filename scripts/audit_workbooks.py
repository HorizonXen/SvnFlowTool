import argparse,multiprocessing,sys,json,pathlib,hashlib,subprocess,concurrent.futures,time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import branch_sync as core, staged_sync, file_sync
parser=argparse.ArgumentParser(description='只读批量验证作者表格合入，不修改 Release')
parser.add_argument('--jobs',type=int,choices=range(1,5),default=2)
parser.add_argument('--author',required=True);parser.add_argument('--days',type=int,default=30);parser.add_argument('--output',required=True)
args=parser.parse_args()
root=pathlib.Path(args.output);root.mkdir(parents=True,exist_ok=True);cache=root/'svn-cache';cache.mkdir(exist_ok=True)
raw=core.run
def cached(*args,**kw):
 key=hashlib.sha256(json.dumps(list(map(str,args)),ensure_ascii=False).encode()).hexdigest();p=cache/key
 if p.exists():return subprocess.CompletedProcess(args,0,p.read_bytes(),b'')
 r=raw(*args,**kw)
 if r.returncode==0:p.write_bytes(r.stdout)
 return r
core.run=cached
report_path=root/'catalog'/'report.json'
if report_path.exists():report=json.loads(report_path.read_text())
else:report=staged_sync.catalog(core,root/'catalog',args.author,args.days)
if report['config']['author']!=args.author or report['config']['days']!=args.days:raise RuntimeError('输出目录属于其他作者或时间范围，请使用新目录')
(root/'run.json').write_text(json.dumps({'author':args.author,'days':args.days,'snapshot':report['config']['snapshot'],'sourceHashes':{n:hashlib.sha256((pathlib.Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['workbook_cells.py','file_sync.py','staged_sync.py']}},ensure_ascii=False,indent=2))
items=[i for i in report['fileItems'] if i['path'].lower().endswith(('.xlsx','.xlsm'))]
def check(item):
 path=item['path'];start=time.time();result={'path':path,'revisions':item['revisions']}
 try:
  baseline=staged_sync.remote(core,report['config'],path,report['config']['snapshot'])
  plan=file_sync.build_plan(core,report,item,resolve_author=True,baseline=baseline)
  output=root/'candidates'/path;output.parent.mkdir(parents=True,exist_ok=True)
  if plan['data'] is not None:output.write_bytes(plan['data'])
  result.update(status='passed',same=plan['same'])
 except Exception as e:result.update(status='blocked',reason=str(e))
 result['seconds']=round(time.time()-start,1)
 (root/(hashlib.sha256(path.encode()).hexdigest()+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps(result,ensure_ascii=False),flush=True);return result
with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs,mp_context=multiprocessing.get_context("fork")) as pool:results=list(pool.map(check,items))
(root/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print('TOTAL',len(results),'PASS',sum(r['status']=='passed' for r in results),flush=True)
