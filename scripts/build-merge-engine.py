"""Build the existing Python merge core as CPython 3.12 extension modules.

Build environment: .build/cython-tools, from a macOS arm64 CPython 3.12 with
headers; pip install -r scripts/merge-compiler-requirements.txt. End users need
neither this environment nor a compiler. No unsafe numeric directives are used.
"""
from pathlib import Path
import hashlib,json,subprocess,shutil

ROOT=Path(__file__).resolve().parents[1]
MODULES=('workbook_dom','workbook_cells','workbook_history')
def main():
    compiler=ROOT/'.build/cython-tools/bin/python'
    if not compiler.exists():raise SystemExit('缺少构建环境 .build/cython-tools；请使用带头文件的 CPython 3.12 创建 venv，并安装 scripts/merge-compiler-requirements.txt')
    out=ROOT/'.build/merge-engine';out.mkdir(parents=True,exist_ok=True)
    for name in MODULES:
        target=out/(name+'.py');source=(ROOT/'scripts'/(name+'.py')).read_bytes()
        if not target.exists() or target.read_bytes()!=source:target.write_bytes(source)
    setup='''import sys,platform,importlib.metadata
assert importlib.metadata.version('Cython')=='3.2.4'
assert importlib.metadata.version('setuptools')=='80.9.0'
assert sys.version_info[:2]==(3,12), '编译器必须使用 CPython 3.12'
assert platform.machine()=='arm64', '正式运行环境为 macOS arm64'
from setuptools import setup,Extension
from Cython.Build import cythonize
names=('workbook_dom','workbook_cells','workbook_history')
setup(name='svnflow-merge-core',ext_modules=cythonize([Extension(n,[n+'.py'],extra_compile_args=['-O3']) for n in names],compiler_directives={'language_level':3,'binding':True,'annotation_typing':False},annotate=True))
'''
    (out/'setup.py').write_text(setup)
    subprocess.run([str(compiler),'setup.py','build_ext','--build-lib','compiled'],cwd=out,check=True)
    manifest={'modules':{},'compilerRequirements':(ROOT/'scripts/merge-compiler-requirements.txt').read_text()}
    for name in MODULES:
        binary=out/(name+'.cpython-312-darwin.so')
        built=out/'compiled'/binary.name
        if not built.exists():raise RuntimeError('编译产物缺失：'+name)
        temporary=out/(binary.name+'.tmp');shutil.copy2(built,temporary);temporary.replace(binary)
        manifest['modules'][name]={'sourceHash':hashlib.sha256((out/(name+'.py')).read_bytes()).hexdigest(),'binaryHash':hashlib.sha256(binary.read_bytes()).hexdigest()}
    (out/'merge-engine.json').write_text(json.dumps(manifest,indent=2))
    subprocess.run([str(ROOT/'vendor/python/bin/python3.12'),'-c',"import workbook_dom,workbook_cells,workbook_history; assert all(m.__file__.endswith('.so') for m in (workbook_dom,workbook_cells,workbook_history)); print('内置 Python 加载编译核心成功')"],cwd=out,check=True)
if __name__=='__main__':main()
