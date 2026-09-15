"""Directory scope must constrain work before any content analysis starts."""
import copy
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock
import test_sync  # supplies scripts import path
import staged_sync as staged

LUA = 'Client/Assets/Script/Lua'
EXCEL = 'Client/CommonRes/Table/Design'


def report():
    paths = [LUA+'/a.lua', LUA+'/sub/b.meta', LUA+'Extra/c.lua', EXCEL+'/table.xlsx', EXCEL+'/pmdata.bin']
    rows = [dict(revision=4, date='2026-09-12T00:00:00Z', message='change', paths=[dict(path=p, action='D' if p.endswith('meta') else 'M', kind='file') for p in paths], outsideScope=[])]
    return dict(schema=3, config=dict(dev='repo/dev', release='repo/release', target='/target', root='repo', uuid='uuid', author='user', days=30, start='a', end='b', snapshot=4), dev=rows, fileItems=staged.files.group_files(rows))


class DirectoryScopeTests(unittest.TestCase):
    def test_boundary_overlap_deletion_and_input_unchanged(self):
        source = report(); before = copy.deepcopy(source)
        scoped = staged.scoped_report(source, [LUA+'/sub', LUA, LUA])
        self.assertEqual([i['path'] for i in scoped['fileItems']], [LUA+'/a.lua', LUA+'/sub/b.meta'])
        self.assertEqual(scoped['dev'][0]['paths'][1]['action'], 'D')
        self.assertEqual(scoped['config']['scopeDirectories'], [LUA])
        self.assertEqual(scoped['config']['scopeTotal'], 4)
        self.assertEqual(scoped['config']['scopeExcluded'], 2)
        self.assertEqual(source, before)

    def test_all_empty_and_invalid_never_expand(self):
        self.assertEqual(len(staged.scoped_report(report(), None)['fileItems']), 5)
        for invalid in [[], [''], ['/Client'], ['Client/../Other'], ['Client//Lua'], ['Client\\Lua'], ['.']]:
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError): staged.scoped_report(report(), invalid)
        self.assertEqual(staged.scoped_report(report(), ['absent'])['fileItems'], [])

    def test_preview_is_log_only(self):
        source = report()
        core = types.SimpleNamespace(load_config=lambda: source['config'], info=mock.Mock(return_value={'revision': 4}),
            logs=mock.Mock(return_value='logs'), records=mock.Mock(return_value=source['dev']),
            run=mock.Mock(side_effect=AssertionError('Content must not be read')))
        result = staged.scope_preview(core, 'user', 30)
        self.assertEqual(len(result['fileItems']), 5)
        core.logs.assert_called_once(); core.run.assert_not_called()

    def test_preview_reused_and_only_scoped_report_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp); source = report(); preview = folder/'preview.json'
            preview.write_text(json.dumps(source))
            core = types.SimpleNamespace(load_config=lambda: source['config'],
                logs=mock.Mock(side_effect=AssertionError('Preview must not be queried again')),
                write_json=lambda p, d: p.write_text(json.dumps(d)),
                render=lambda r, f: (f/'差异报告.md').write_text('## 使用方式'))
            result = staged.catalog(core, folder/'round', 'user', 30, [LUA], preview)
            core.logs.assert_not_called()
            self.assertEqual(len(result['fileItems']), 2)
            self.assertEqual(json.loads((folder/'round/report.json').read_text()), result)
            self.assertTrue((folder/'round/review.json').exists())
            for field, value in [('target', '/other'), ('dev', 'other'), ('uuid', 'other')]:
                changed = copy.deepcopy(source); changed['config'][field] = value
                preview.write_text(json.dumps(changed))
                with self.assertRaises(RuntimeError): staged.catalog(core, folder/'bad', 'user', 30, [LUA], preview)
                self.assertFalse((folder/'bad').exists())
            preview.write_text(json.dumps(source))
            with self.assertRaises(RuntimeError): staged.catalog(core, folder/'bad', 'other', 30, [LUA], preview)

    def test_pmdata_not_in_verification_counts(self):
        result = staged.scoped_report(report(), [EXCEL])
        self.assertEqual(len(result['fileItems']), 2)
        self.assertEqual(result['config']['scopeTotal'] - result['config']['scopeExcluded'], 1)


if __name__ == '__main__': unittest.main()
