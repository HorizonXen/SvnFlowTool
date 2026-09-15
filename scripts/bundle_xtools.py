import hashlib
import json
import os
import pathlib
import shutil
import sys


def desktop_bridge_source(source):
    """Apply the desktop header contract without modifying the shared checkout.

    xlsTools sheetconvert.go reads fields at row 2 and data from row 6.
    A sheet without starred keys uses sequential record indices. Keep all
    existing field/type/key/output checks; only replace header discovery.
    Fail the build if the upstream implementation changes under this patch.
    """
    old = '''            declarations = [i for i, row in sorted(rows.items()) if any(re.fullmatch(r"\\*{1,2}[A-Za-z_][A-Za-z_0-9]*", str(v)) for v in row.values())]
            if len(declarations) != 1:
                raise ValueError("主键声明缺失或重复：" + name)
            header = declarations[0]
'''
    new = '''            # xlsTools fixed header; keyless sheets use sequential indices.
            header = 2
            if not rows.get(header):
                raise ValueError("字段声明缺失：" + name)
'''
    if source.count(old) != 1:
        raise RuntimeError('共享导出核心表头实现已变化，请重新核查桌面兼容补丁')
    return source.replace(old, new)


def discover(start):
    override = os.environ.get('FND_TOOLS_ROOT')
    if override:
        candidates = [pathlib.Path(override).expanduser().resolve()]
    else:
        candidates = []
        for parent in pathlib.Path(start).resolve().parents:
            if parent == pathlib.Path('/'):
                break
            candidates.append(parent)
            for child in parent.iterdir():
                if child.is_dir() and not child.name.startswith('.'):
                    candidates.append(child)
                    if parent == pathlib.Path('/Users'):
                        candidates.extend(p for p in child.iterdir() if p.is_dir() and not p.name.startswith('.'))
    hits = {p.resolve() for p in candidates if (p / 'tools/excel/xtools_bridge.py').is_file() and (p / 'tools/excel/xlstools_single_file_validate.py').is_file()}
    if len(hits) != 1:
        raise RuntimeError('无法唯一找到可选导出核心；请设置 FND_TOOLS_ROOT 指向其仓库根目录')
    return hits.pop()


def unavailable_source(module):
    return (
        '"""Optional export integration is not included in the public build."""\n'
        'def __getattr__(name):\n'
        '    raise RuntimeError("此构建未包含可选的配置导出集成。")\n'
    )


def bundle(destination, optional=False):
    destination = pathlib.Path(destination)
    if not destination.is_dir():
        raise RuntimeError('应用资源目录不存在')
    try:
        root = discover(__file__)
    except RuntimeError:
        if not optional:
            raise
        manifest = {'available': False, 'reason': 'optional integration not bundled'}
        for name in ('xtools_bridge.py', 'xlstools_single_file_validate.py'):
            (destination / name).write_text(unavailable_source(name), encoding='utf-8')
        (destination / 'xtools-core.json').write_text(json.dumps(manifest, indent=2))
        return
    manifest = {}
    for name in ('xtools_bridge.py', 'xlstools_single_file_validate.py'):
        source = root / 'tools/excel' / name
        target = destination / name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError('共享导出核心打包校验失败')
        manifest[name] = {'source': str(source), 'sha256': digest}
        if name == 'xtools_bridge.py':
            target.write_text(desktop_bridge_source(target.read_text()))
            manifest[name]['desktopPatch'] = 'fixed-row-2-header-v1'
            manifest[name]['bundledSha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / 'xtools-core.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    bundle(sys.argv[1], optional='--optional' in sys.argv[2:])
