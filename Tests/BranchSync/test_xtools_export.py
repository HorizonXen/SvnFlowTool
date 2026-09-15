import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from bundle_xtools import discover, desktop_bridge_source
sys.path.insert(0, str(discover(__file__) / 'tools/excel'))
import branch_sync
import file_sync
import xtools_bridge
# Exercise the same compatibility source shipped by bundle_xtools.
exec(compile(desktop_bridge_source(pathlib.Path(xtools_bridge.__file__).read_text()),
             xtools_bridge.__file__, 'exec'), xtools_bridge.__dict__)
import xtools_export
from test_config_identity import table
from test_workbook import book


class XToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='svnflow-xtools-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = pathlib.Path(self.temp.name).resolve()
        self.repo = self.directory / 'repository'
        subprocess.run([shutil.which('svnadmin'), 'create', str(self.repo)], check=True, capture_output=True)
        seed = self.directory / 'seed'
        self.workbook = 'CommonRes/Table/Design/global/base/1.xlsx'
        path = seed / self.workbook
        path.parent.mkdir(parents=True)
        with patch('test_config_identity.fixture', return_value=book(extra=False, formula=False)):
            path.write_bytes(table([(3, dict(ID='int', value='int', other='string')), (6, dict(ID=1, value=2, other='release-only'))]))
        design = seed / 'CommonRes/Table/Design'
        (design / '.导表.bat').write_text('cd ../../../Tools/xlsTools\nstart "" pandaTools.exe\n')
        tool = seed / 'Tools/xlsTools'
        (tool / 'bin').mkdir(parents=True)
        (tool / 'pandaTools.exe').write_bytes(b'fixture-gui')
        (tool / 'bin/xlstools-backend-darwin-arm64').write_bytes(b'fixture-backend')
        (tool / 'config.json').write_text(json.dumps({'inputDir':'../../CommonRes/Table/Design','clientOutputDir':'../../CommonRes/Table/Client','serverOutputDir':'../../CommonRes/Table/Server'}))
        for side in ('Client', 'Server'):
            parent = seed / 'CommonRes/Table' / side / 'global/base'
            parent.mkdir(parents=True)
            (parent / 't_Main.lua').write_text('local data = {[1] = {ID=1,value=1,other=[[release-only]]}}\nreturn data')
            (parent / 'keep.lua').write_text('return {keep=7}')
        package = seed / 'Assets/Arts/Config/BddData/global/pmdata.bin'
        package.parent.mkdir(parents=True)
        package.write_bytes(b'old-package')
        url = self.repo.as_uri()
        branch_sync.run('import', '-q', str(seed), url, '-m', 'isolated fixture')
        self.root = self.directory / 'release'
        branch_sync.run('checkout', '-q', url, str(self.root))
        self.folder = self.directory / 'batch'
        self.folder.mkdir()
        self.config = dict(target=str(self.root), release=url, dev=url, uuid=branch_sync.info(str(self.root))['uuid'])
        report = dict(config=self.config, dev=[], fileItems=[])
        self.report = report
        branch_sync.write_json(self.folder / 'report.json', report)
        candidate = self.folder / '待合入' / self.workbook
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes((self.root / self.workbook).read_bytes())
        entry = dict(status='accepted', same=False, path=self.workbook, candidate=str(candidate), candidateHash=hashlib.sha256(candidate.read_bytes()).hexdigest())
        branch_sync.write_json(self.folder / 'review.json', dict(reportHash=file_sync.report_hash(report), items={self.workbook:entry}))
        self.core = types.SimpleNamespace(verify_config=lambda report:self.config, info=branch_sync.info, run=branch_sync.run, write_json=branch_sync.write_json)
        self.addCleanup(patch.stopall)
        patch.object(xtools_bridge.platform, 'system', return_value='Darwin').start()
        patch.object(xtools_bridge.platform, 'machine', return_value='arm64').start()
        patch.object(xtools_bridge, 'run_backend_export', side_effect=self.export).start()
        patch.object(xtools_bridge, 'pack_pmdata', side_effect=self.pack).start()

    def export(self, binary, design, version, layer, filename, output, **kwargs):
        for side in ('client', 'server'):
            path = output / side / version / layer / 't_Main.lua'
            path.parent.mkdir(parents=True)
            path.write_text('local data = {[1] = {ID=1,value=2,other=[[release-only]]}}\nreturn data')
        return dict(ok=True, log='fixture backend')

    def pack(self, binary, design, version, layer, output, **kwargs):
        output.write_bytes(b'new-package')
        return dict(ok=True, log='fixture package')

    def test_real_svn_publication_keeps_unrelated_files_and_does_not_commit(self):
        before = xtools_bridge.tree(self.root)
        revision = branch_sync.info(self.config['release'])['revision']
        result = xtools_export.prepare(self.core, self.folder)
        self.assertEqual(xtools_bridge.tree(self.root), before)
        self.assertEqual(result['fields'], 6)
        result = xtools_export.publish(self.core, self.folder, result['sha256'])
        self.assertEqual(result['status'], 'published')
        self.assertEqual(branch_sync.info(self.config['release'])['revision'], revision)
        self.assertEqual((self.root / 'CommonRes/Table/Client/global/base/keep.lua').read_text(), 'return {keep=7}')
        self.assertIn('value=2', (self.root / 'CommonRes/Table/Client/global/base/t_Main.lua').read_text())
        self.assertIn(b'value=1', branch_sync.run('cat', self.config['release']+'/CommonRes/Table/Client/global/base/t_Main.lua').stdout)
        self.assertEqual(xtools_export.publish(self.core, self.folder, result['sha256'])['status'], 'published')

    def test_independent_semantics_rejects_consistently_wrong_exports(self):
        original = self.export
        def wrong(*args, **kwargs):
            result = original(*args, **kwargs)
            for path in args[5].rglob('*.lua'):
                path.write_text(path.read_text().replace('value=2', 'value=99'))
            return result
        with patch.object(xtools_bridge, 'run_backend_export', side_effect=wrong):
            with self.assertRaisesRegex(ValueError, '全字段合同'):
                xtools_export.prepare(self.core, self.folder)
        self.assertIn('value=1', (self.root/'CommonRes/Table/Client/global/base/t_Main.lua').read_text())

    def test_changed_excel_blocks_publication(self):
        result = xtools_export.prepare(self.core, self.folder)
        with (self.root/self.workbook).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(ValueError):
            xtools_export.publish(self.core, self.folder, result['sha256'])

    def test_local_unbracketed_lists_verify_and_publish_but_wrong_items_fail(self):
        workbook = self.root / self.workbook
        with patch('test_config_identity.fixture', return_value=book(extra=False, formula=False)):
            workbook.write_bytes(table([
                (3, dict(ID='int', value='list(string)', other='list(int)')),
                (6, dict(ID=1, value='#4169bb,#beecff', other='1, 2')),
            ]))
        before = workbook.read_bytes()
        original = self.export
        def lists(*args, **kwargs):
            result = original(*args, **kwargs)
            for path in args[5].rglob('*.lua'):
                path.write_text('return {[1]={ID=1,value={"#4169bb","#beecff"},other={1,2}}}')
            return result
        with patch.object(xtools_bridge, 'run_backend_export', side_effect=lists):
            result = xtools_export.export(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(workbook.read_bytes(), before)
        def wrong(*args, **kwargs):
            result = lists(*args, **kwargs)
            for path in args[5].rglob('*.lua'):
                path.write_text(path.read_text().replace('#beecff', '#ffffff'))
            return result
        with patch.object(xtools_bridge, 'run_backend_export', side_effect=wrong):
            with self.assertRaisesRegex(ValueError, '全字段合同'):
                xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)

    def test_keyless_sheet_uses_order_and_keeps_literal_star_strings(self):
        workbook = self.root / self.workbook
        with patch('test_config_identity.fixture', return_value=book(extra=False, formula=False)):
            data = table([(3, dict(ID='int', value='int', other='string')),
                          (6, dict(ID=7, value=2, other='*literal')),
                          (8, dict(ID=7, value=3, other='second'))])
        # Remove only the explicit key declaration in this synthetic workbook.
        import io, zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename.endswith('.xml'):
                    content = content.replace(b'>*ID<', b'>ID<')
                target.writestr(item, content)
        workbook.write_bytes(output.getvalue())
        def keyless(*args, **kwargs):
            result = self.export(*args, **kwargs)
            for path in args[5].rglob('*.lua'):
                path.write_text('return {[1]={ID=7,value=2,other="*literal"},[2]={ID=7,value=3,other="second"}}')
            return result
        with patch.object(xtools_bridge, 'run_backend_export', side_effect=keyless):
            self.assertEqual(xtools_export.export(self.core, self.folder, [self.workbook], local=True)['fields'], 12)

    def test_one_click_local_export_writes_outputs_without_merge_record(self):
        (self.folder / 'review.json').unlink()
        before = (self.root / self.workbook).read_bytes()
        revision = branch_sync.info(self.config['release'])['revision']
        result = xtools_export.export(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual((self.root / 'Assets/Arts/Config/BddData/global/pmdata.bin').read_bytes(), b'new-package')
        self.assertIn('value=2', (self.root / 'CommonRes/Table/Client/global/base/t_Main.lua').read_text())
        self.assertEqual((self.root / self.workbook).read_bytes(), before)
        self.assertEqual(branch_sync.info(self.config['release'])['revision'], revision)

    def test_one_click_export_stops_before_write_on_failed_verification(self):
        before = xtools_bridge.tree(self.root)
        with patch.object(xtools_export, 'semantics', side_effect=ValueError('bad fields')):
            with self.assertRaises(ValueError):
                xtools_export.export(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(xtools_bridge.tree(self.root), before)

    def test_local_export_allows_newer_remote_output_without_committing(self):
        other = self.directory / 'other-wc'
        branch_sync.run('checkout', '-q', self.config['release'], str(other))
        path = 'CommonRes/Table/Client/global/base/t_Main.lua'
        remote = other / path
        remote.write_text('return {remote_newer=99}')
        branch_sync.run('commit', '-m', 'remote generated artifact', str(remote))
        revision = branch_sync.info(self.config['release'])['revision']
        result = xtools_export.export(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertIn('value=2', (self.root / path).read_text())
        self.assertEqual(branch_sync.run('cat', self.config['release']+'/'+path).stdout, b'return {remote_newer=99}')
        self.assertEqual(branch_sync.info(self.config['release'])['revision'], revision)

    def test_one_click_merge_export_completes(self):
        result = xtools_export.export(self.core, self.folder, [self.workbook])
        self.assertEqual(result['status'], 'published')

    def test_local_excel_without_merge_ledger_exports_and_publishes(self):
        (self.folder / 'review.json').unlink()
        before = (self.root / self.workbook).read_bytes()
        revision = branch_sync.info(self.config['release'])['revision']
        result = xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(result['fields'], 6)
        self.assertFalse((self.folder / 'xtools-latest.json').exists())
        result = xtools_export.publish(self.core, self.folder, result['sha256'], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual((self.root / self.workbook).read_bytes(), before)
        self.assertFalse((self.folder / 'review.json').exists())
        self.assertEqual(branch_sync.info(self.config['release'])['revision'], revision)

    def test_local_export_preserves_invalidated_merge_record(self):
        ledger = self.folder / 'review.json'
        state = json.loads(ledger.read_text())
        state['items'][self.workbook]['status'] = 'invalidated'
        state['items'][self.workbook]['candidateHash'] = 'old-content'
        branch_sync.write_json(ledger, state)
        before = ledger.read_bytes()
        result = xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)
        xtools_export.publish(self.core, self.folder, result['sha256'], local=True)
        self.assertEqual(ledger.read_bytes(), before)
        with self.assertRaises(RuntimeError):
            xtools_export.prepare(self.core, self.folder, [self.workbook])

    def test_local_excel_change_blocks_write(self):
        result = xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)
        (self.root / self.workbook).write_bytes(b'changed after preview')
        with self.assertRaisesRegex(RuntimeError, '发生变化'):
            xtools_export.publish(self.core, self.folder, result['sha256'], local=True)
        self.assertIn('value=1', (self.root / 'CommonRes/Table/Client/global/base/t_Main.lua').read_text())

    def test_local_selection_and_path_boundaries(self):
        for paths in (None, [], [self.workbook, self.workbook], ['../escape.xlsx'], [str(self.root / self.workbook)], ['missing.xlsx'], ['not.lua']):
            with self.subTest(paths=paths), self.assertRaises((RuntimeError, ValueError)):
                xtools_export.prepare(self.core, self.folder, paths, local=True)

    def test_local_failed_semantics_cannot_publish(self):
        with patch.object(xtools_export, 'semantics', side_effect=ValueError('bad fields')):
            with self.assertRaises(ValueError):
                xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)
        self.assertFalse((self.folder / 'xtools-local-latest.json').exists())

    def test_local_export_does_not_bypass_pending_merge(self):
        ledger = self.folder / 'review.json'
        state = json.loads(ledger.read_text()); state['pending'] = self.workbook
        branch_sync.write_json(ledger, state)
        with self.assertRaisesRegex(RuntimeError, '合入尚未完成'):
            xtools_export.prepare(self.core, self.folder, [self.workbook], local=True)

    def test_boolean_lua_key_is_not_integer_one(self):
        candidate = self.directory / 'bool-key.lua'
        candidate.write_text('return {[true] = {ID=1,value=2}}')
        with self.assertRaisesRegex(ValueError, '布尔'):
            xtools_export.read_lua(candidate)

    def test_only_selected_accepted_excel_is_exported(self):
        state = json.loads((self.folder / 'review.json').read_text())
        state['items']['CommonRes/Table/Design/global/base/unselected.xlsx'] = dict(status='accepted', same=False)
        branch_sync.write_json(self.folder / 'review.json', state)
        result = xtools_export.prepare(self.core, self.folder, [self.workbook])
        receipt = json.loads(pathlib.Path(result['receipt']).read_text())
        self.assertEqual([row['path'] for row in receipt['workbooks']], [self.workbook])

    def test_empty_or_unaccepted_selection_blocks(self):
        for paths in ([], ['unknown.xlsx'], [self.workbook, self.workbook]):
            with self.subTest(paths=paths), self.assertRaises(RuntimeError):
                xtools_export.prepare(self.core, self.folder, paths)

    def test_svn_identity_change_blocks(self):
        result = xtools_export.prepare(self.core, self.folder)
        original = self.core.info
        self.core.info = lambda target:dict(original(target), uuid='different')
        with self.assertRaisesRegex(RuntimeError, '身份'):
            xtools_export.publish(self.core, self.folder, result['sha256'])

    def test_missing_approval_blocks(self):
        xtools_export.prepare(self.core, self.folder)
        with self.assertRaisesRegex(RuntimeError, '当前确认'):
            xtools_export.publish(self.core, self.folder, 'wrong')

    def test_property_changes_block(self):
        result = xtools_export.prepare(self.core, self.folder)
        branch_sync.run('propset','test-property','changed',str(self.root/'CommonRes/Table/Client/global/base/t_Main.lua'))
        with self.assertRaisesRegex(RuntimeError, '属性'):
            xtools_export.publish(self.core, self.folder, result['sha256'])

    def test_executable_lua_wrapper_is_rejected(self):
        path = self.directory/'bad.lua'
        path.write_text('local data = {x=1}\nos.execute("unsafe")\nreturn data')
        with self.assertRaisesRegex(ValueError, '可执行'):
            xtools_export.read_lua(path)

    def test_reverse_enum_marker_is_verified_without_changing_excel(self):
        with patch('test_config_identity.fixture', return_value=book(extra=False, formula=False)):
            self.check_reverse_enum_marker()

    def check_reverse_enum_marker(self):
        enum_path = self.root / 'CommonRes/Table/Design/global/base/3.枚举表.xlsx'
        enum_bytes = table([
            (3, dict(enumname='string', key='string', ckey='string', value='int')),
            (6, dict(enumname='SYSTEM_EVENT_TYPE$', key='EVENT', ckey='事件', value=2)),
        ], fields=('enumname', 'key', 'ckey', 'value'))
        enum_path.write_bytes(enum_bytes)
        workbook = self.root / self.workbook
        workbook.write_bytes(table([
            (3, dict(ID='int', value='enum.SYSTEM_EVENT_TYPE', other='string')),
            (6, dict(ID=1, value='事件', other='release-only')),
        ]))
        result = xtools_export.export(self.core, self.folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['fields'], 6)
        self.assertEqual(enum_path.read_bytes(), enum_bytes)
        workbook.write_bytes(table([
            (3, dict(ID='int', value='match:SYSTEM_EVENT_TYPE\ndefault:string',
                     other='match:SYSTEM_EVENT_TYPE\ndefault:string')),
            (6, dict(ID=1, value='事件', other='release-only')),
        ]))
        self.assertEqual(xtools_export.export(self.core, self.folder, [self.workbook], local=True)['status'], 'published')
        # An actual missing definition remains an error, even with the adapter.
        workbook.write_bytes(table([
            (3, dict(ID='int', value='enum.MISSING_TYPE', other='string')),
            (6, dict(ID=1, value='事件', other='release-only')),
        ]))
        with self.assertRaisesRegex(ValueError, '缺少独立枚举定义'):
            xtools_export.export(self.core, self.folder, [self.workbook], local=True)

    def workspace_core(self, roots):
        copies = [{'id': str(index), 'path': str(root)} for index, root in enumerate(roots)]
        patch.object(branch_sync, 'fixed_copies', return_value=copies).start()
        self.core.load_workspace_export_config = branch_sync.load_workspace_export_config

    def test_workspace_dev_and_release_export_are_isolated_without_merge_report(self):
        dev = self.directory / 'dev'
        branch_sync.run('checkout', '-q', self.repo.as_uri(), str(dev))
        self.workspace_core([dev, self.root])
        release_before = xtools_bridge.tree(self.root)
        revision = branch_sync.info(self.repo.as_uri())['revision']
        dev_folder = self.directory / 'dev-export'
        xtools_export.initialize_workspace(self.core, dev_folder, str(dev))
        result = xtools_export.export(self.core, dev_folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(xtools_bridge.tree(self.root), release_before)
        self.assertTrue(all(pathlib.Path(row['target']).is_relative_to(dev) for row in result['outputs']))
        self.assertEqual((dev / 'Assets/Arts/Config/BddData/global/pmdata.bin').read_bytes(), b'new-package')
        dev_after = xtools_bridge.tree(dev)
        release_folder = self.directory / 'release-export'
        xtools_export.initialize_workspace(self.core, release_folder, str(self.root))
        result = xtools_export.export(self.core, release_folder, [self.workbook], local=True)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(xtools_bridge.tree(dev), dev_after)
        self.assertEqual(branch_sync.info(self.repo.as_uri())['revision'], revision)
        with self.assertRaisesRegex(RuntimeError, '不属于'):
            xtools_export.initialize_workspace(self.core, dev_folder, str(self.root))

    def test_workspace_identity_change_and_unconfigured_target_block(self):
        self.workspace_core([self.root])
        folder = self.directory / 'local-export'
        with self.assertRaisesRegex(RuntimeError, '配置'):
            xtools_export.initialize_workspace(self.core, folder, str(self.directory))
        xtools_export.initialize_workspace(self.core, folder, str(self.root))
        candidate = xtools_export.prepare(self.core, folder, [self.workbook], local=True)
        original = self.core.load_workspace_export_config
        self.core.load_workspace_export_config = lambda target: dict(original(target), uuid='changed')
        before = xtools_bridge.tree(self.root)
        with self.assertRaisesRegex(RuntimeError, '身份'):
            xtools_export.publish(self.core, folder, candidate['sha256'], local=True)
        self.assertEqual(xtools_bridge.tree(self.root), before)
        with self.assertRaisesRegex(RuntimeError, '不能用于合入'):
            xtools_export.prepare(self.core, folder, [self.workbook])

    def test_lua_decimal_escape_is_not_read_as_python_octal(self):
        path = self.directory/'escape.lua'
        path.write_text('local data = {x="' + chr(92) + '123"}\nreturn data')
        with self.assertRaisesRegex(ValueError, '转义'):
            xtools_export.read_lua(path)


if __name__ == '__main__':
    unittest.main()
