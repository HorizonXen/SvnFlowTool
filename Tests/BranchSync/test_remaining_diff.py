"""Remaining work uses current repository contents, independently of historical review artifacts."""
import json
import unittest
from unittest import mock
import test_file_sync as fixtures
import staged_sync


class RemainingDiffTests(unittest.TestCase):
    setUp = fixtures.FileSyncTests.setUp
    tearDown = fixtures.FileSyncTests.tearDown
    commit = fixtures.FileSyncTests.commit
    report_files = fixtures.FileSyncTests.report_files

    def test_excel_already_applied_scope_with_unrelated_duplicate_page(self):
        from test_config_identity import table
        from test_workbook import parts, pack
        def data(value, other):
            p=parts(table([(6,dict(ID=100,value=value,other=other))]))
            p['xl/worksheets/sheet2.xml']=parts(table([
                (6,dict(ID=':',value=1)),(7,dict(ID=':',value=2))]))['xl/worksheets/sheet1.xml']
            return pack(p)
        self.commit(self.dev,'config.xlsx',data(1,9),'seed')
        release=data(2,8)
        self.commit(self.target,'config.xlsx',release,'release')
        self.commit(self.dev,'config.xlsx',data(2,9))
        self.report_files();core=fixtures.sync
        core.write_json(self.folder/'review.json',dict(mode='review-v1',
            reportHash=core.file_sync.report_hash(self.report),items={}))
        result=staged_sync.remaining_diff(core,self.folder,paths=['config.xlsx'])
        self.assertEqual(result['noDiffPaths'],['config.xlsx'])
        self.assertFalse(result['errors'])
        self.assertEqual((self.target/'config.xlsx').read_bytes(),release)

    def test_new_engine_retries_cached_duplicate_id_failure(self):
        core=self.start()
        with mock.patch.object(staged_sync.files,'compiled_engine_hash',return_value=b'old-engine'), \
             mock.patch.object(staged_sync.files,'build_plan',side_effect=ValueError('删除保护：配置 ID 重复：old')):
            self.assertIn('a.txt',self.check(core)['errors'])
        result=self.check(core)
        self.assertFalse(result['errors'])
        self.assertEqual(result['differentPaths'],['a.txt'])

    def start(self):
        core = fixtures.sync
        self.report_files()
        self.report['fileItems'] = [i for i in self.report['fileItems'] if i['path'] == 'a.txt']
        core.write_json(self.folder/'report.json', self.report)
        core.write_json(self.folder/'review.json', dict(mode='review-v1', reportHash=core.file_sync.report_hash(self.report), items={}))
        return core

    def check(self, core):
        ledger = (self.folder/'review.json').read_bytes()
        content = (self.target/'a.txt').read_bytes()
        result = staged_sync.remaining_diff(core, self.folder)
        self.assertEqual((self.folder/'review.json').read_bytes(), ledger)
        self.assertEqual((self.target/'a.txt').read_bytes(), content)
        return result

    def test_external_merge_is_recognized_without_accepting_a_review(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'one\nchanged\nthree\n')
        result = self.check(core)
        self.assertEqual(result['differentPaths'], ['a.txt'])
        self.assertEqual(result['localStates'], {'a.txt':'same'})
        self.assertFalse(result['localIssues'])
        self.assertEqual(json.loads((self.folder/'review.json').read_text())['items'], {})
        core.run('revert', self.target/'a.txt')
        result = self.check(core)
        self.assertEqual(result['localStates']['a.txt'], 'different')
        self.assertFalse(result['localIssues'])

    def test_local_merge_with_unrelated_release_values(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'release-only\nchanged\nthree\n')
        result = self.check(core)
        self.assertEqual(result['localStates']['a.txt'], 'same')
        self.assertFalse(result['localIssues'])

    def test_registered_local_equality_skips_replay_across_report_folders(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'release-only\nchanged\nthree\n')
        self.assertEqual(self.check(core)['localStates']['a.txt'], 'same')
        other = self.folder.parent/'another-report'
        other.mkdir()
        for name in ('report.json', 'review.json'):
            (other/name).write_bytes((self.folder/name).read_bytes())
        with mock.patch.object(staged_sync.files, 'build_plan', side_effect=AssertionError('registered scope replayed')):
            result = staged_sync.remaining_diff(core, other)
        self.assertEqual(result['localStates']['a.txt'], 'same')
        self.assertFalse(result['errors'])
        self.assertFalse(result['localIssues'])

    def test_registered_local_equality_expires_after_local_edit(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'release-only\nchanged\nthree\n')
        self.assertEqual(self.check(core)['localStates']['a.txt'], 'same')
        (self.target/'a.txt').write_bytes(b'release-only\ntwo\nthree\n')
        result = self.check(core)
        self.assertNotEqual(result['localStates']['a.txt'], 'same')

    def test_registered_local_equality_does_not_cover_new_author_commit(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'release-only\nchanged\nthree\n')
        self.assertEqual(self.check(core)['localStates']['a.txt'], 'same')
        self.commit(self.dev, 'a.txt', b'one\nnew-value\nthree\n')
        self.start()
        result = self.check(core)
        self.assertNotEqual(result['localStates']['a.txt'], 'same')

    def test_local_conflict_never_counts_as_merged(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'one\nchanged\nthree\n')
        local = staged_sync.local_state(core, self.report['config'], 'a.txt')
        local['status']['tree-conflicted'] = 'true'
        with mock.patch.object(staged_sync, 'local_state', return_value=local):
            result = self.check(core)
        self.assertEqual(result['localStates']['a.txt'], 'blocked')
        self.assertIn('a.txt', result['localIssues'])

    def test_saved_evidence_expires_after_external_edit(self):
        core = self.start()
        self.check(core)
        (self.target/'a.txt').write_bytes(b'external edit')
        staged_sync.repair_review(core, self.folder)
        saved = json.loads((self.folder/'remaining-last.json').read_text())
        self.assertNotIn('a.txt', saved['differentPaths'])
        self.assertNotIn('a.txt', saved['localStates'])

    def test_submitted_result_hides_despite_historical_diff(self):
        core = self.start()
        staged_sync.operate(core, self.folder, 'stage', 'a.txt')
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        result = self.check(core)
        self.assertEqual(result['noDiffPaths'], ['a.txt'])
        self.assertFalse(json.loads((self.folder/'review.json').read_text())['items']['a.txt']['same'])

    def test_unrelated_later_release_commit_does_not_resurrect_old_diff(self):
        core = self.start()
        staged_sync.operate(core, self.folder, 'stage', 'a.txt')
        self.commit(self.target, 'a.txt', b'release-only\nchanged\nthree\n', 'release')
        self.assertEqual(self.check(core)['noDiffPaths'], ['a.txt'])

    def test_real_remaining_change_and_remote_revert_stay_visible(self):
        core = self.start()
        self.assertEqual(self.check(core)['differentPaths'], ['a.txt'])
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        self.assertEqual(self.check(core)['noDiffPaths'], ['a.txt'])
        self.commit(self.target, 'a.txt', b'one\ntwo\nthree\n', 'release')
        self.assertEqual(self.check(core)['differentPaths'], ['a.txt'])

    def test_local_edit_is_rechecked_even_with_cached_no_diff(self):
        core = self.start()
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        self.assertEqual(self.check(core)['noDiffPaths'], ['a.txt'])
        (self.target/'a.txt').write_bytes(b'unsaved local work')
        with mock.patch.object(staged_sync.files, 'build_plan', side_effect=AssertionError('cache missed')):
            result = self.check(core)
        self.assertEqual(result['noDiffPaths'], ['a.txt'])
        self.assertIn('本地修改', result['localIssues']['a.txt'])

    def test_property_only_change_is_not_hidden(self):
        core = self.start()
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        core.run('propset', 'custom:flag', 'author', self.dev/'a.txt')
        core.run('commit', self.dev, '-m', 'property change', '--username', 'sample.author')
        self.start()
        self.assertEqual(self.check(core)['differentPaths'], ['a.txt'])

    def test_identical_current_branches_need_no_history_replay(self):
        core = self.start()
        self.commit(self.target, 'a.txt', (self.dev/'a.txt').read_bytes(), 'release')
        with mock.patch.object(staged_sync.files, 'build_plan', side_effect=AssertionError('unnecessary history replay')):
            self.assertEqual(self.check(core)['noDiffPaths'], ['a.txt'])

    def test_deterministic_failure_stays_visible_without_replaying_unchanged_inputs(self):
        core = self.start()
        with mock.patch.object(staged_sync.files, 'build_plan', side_effect=RuntimeError('r1：无法安全提取作者改动范围内的 Dev 最新值：fixture')) as replay:
            first = self.check(core)
            second = self.check(core)
            self.assertEqual(replay.call_count, 1)
        self.assertEqual(first['errors'], second['errors'])
        self.assertFalse(second['noDiffPaths'])

    def test_workbook_history_change_invalidates_equal_content_cache(self):
        core=fixtures.sync
        self.commit(self.dev,'a.xlsx',b'dev state')
        self.commit(self.target,'a.xlsx',b'release state','release')
        self.report_files()
        self.report['fileItems']=[item for item in self.report['fileItems'] if item['path']=='a.xlsx']
        core.write_json(self.folder/'report.json',self.report)
        core.write_json(self.folder/'review.json',dict(reportHash=core.file_sync.report_hash(self.report),items={}))
        with mock.patch.object(staged_sync.files,'build_plan',return_value={'same':False}) as build:
            staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
            staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
            self.assertEqual(build.call_count,1)
            self.commit(self.dev,'a.xlsx',b'intermediate restore','other')
            self.commit(self.dev,'a.xlsx',b'dev state','sample.author')
            staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
            self.assertEqual(build.call_count,2)

    def test_workbook_unrelated_commit_reuses_result_but_rechecks_history(self):
        core=fixtures.sync
        self.commit(self.dev,'a.xlsx',b'dev state')
        self.commit(self.target,'a.xlsx',b'release state','release')
        self.report_files()
        self.report['fileItems']=[item for item in self.report['fileItems'] if item['path']=='a.xlsx']
        core.write_json(self.folder/'report.json',self.report)
        core.write_json(self.folder/'review.json',dict(reportHash=core.file_sync.report_hash(self.report),items={}))
        import workbook_history
        with mock.patch.object(staged_sync.files,'build_plan',return_value={'same':False}) as build:
            first=staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
            self.commit(self.dev,'unrelated.txt',b'new unrelated data','other')
            with mock.patch.object(workbook_history,'history_entries',wraps=workbook_history.history_entries) as history:
                second=staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
                self.assertTrue(history.called)
            self.assertFalse(second['errors']);self.assertGreater(second['snapshot'],first['snapshot'])
            self.assertEqual(build.call_count,1)
            with mock.patch.object(workbook_history,'history_entries',side_effect=RuntimeError('network unavailable')):
                failed=staged_sync.remaining_diff(core,self.folder,['a.xlsx'])
                self.assertIn('network unavailable',failed['errors']['a.xlsx'])

    def test_transient_read_error_inside_projection_is_not_cached(self):
        core=self.start();reader_factory=staged_sync.remaining_local_reader
        def factory(*args,**kwargs):
            read=reader_factory(*args,**kwargs)
            def runner(*values,**options):
                if values==('cat','fixture-network-failure'):raise RuntimeError('offline')
                return read(*values,**options)
            return runner
        def fail(worker,*args,**kwargs):
            try:worker.run('cat','fixture-network-failure')
            except RuntimeError as error:raise RuntimeError('r5：无法安全提取作者改动范围内的 Dev 最新值：'+str(error)) from error
        with mock.patch.object(staged_sync,'remaining_local_reader',side_effect=factory):
            with mock.patch.object(staged_sync.files,'build_plan',side_effect=fail):
                first=self.check(core);self.assertIn('offline',first['errors']['a.txt'])
            with mock.patch.object(staged_sync.files,'build_plan',return_value={'same':False}) as build:
                second=self.check(core);self.assertTrue(build.called);self.assertFalse(second['errors'])

    def test_clean_but_outdated_working_copy_is_not_called_a_local_edit(self):
        core = self.start()
        other = self.root/'other-release'
        core.run('checkout', self.config['release'], other)
        self.commit(other, 'a.txt', b'one\nchanged\nthree\n', 'release')
        result = self.check(core)
        self.assertFalse(result['localIssues'])
        self.assertEqual(result['noDiffPaths'], ['a.txt'])

    def test_local_independent_edit_does_not_block_preparation(self):
        core = self.start()
        (self.target/'a.txt').write_bytes(b'local\ntwo\nthree\n')
        result = self.check(core)
        self.assertFalse(result['localIssues'])
        self.assertEqual(result['localStates']['a.txt'], 'different')
        self.assertEqual(result['differentPaths'], ['a.txt'])

    def test_outdated_release_with_remaining_work_does_not_block(self):
        core = self.start()
        other = self.root/'other-release'
        core.run('checkout', self.config['release'], other)
        self.commit(other, 'a.txt', b'one\ntwo\nremote\n', 'release')
        result = self.check(core)
        self.assertFalse(result['localIssues'])
        self.assertEqual(result['differentPaths'], ['a.txt'])
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual(__import__('pathlib').Path(entry['candidate']).read_bytes(), b'one\nchanged\nremote\n')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(), b'one\nchanged\nremote\n')

    def test_unfinished_write_never_checks_or_hides(self):
        core = self.start()
        ledger = json.loads((self.folder/'review.json').read_text()); ledger['pending'] = 'a.txt'
        core.write_json(self.folder/'review.json', ledger)
        with mock.patch.object(core, 'info', side_effect=AssertionError('must not read SVN')):
            with self.assertRaisesRegex(RuntimeError, '未完成写入'):
                self.check(core)

    def test_warm_scan_batches_local_reads_and_keeps_head_live(self):
        core = self.start()
        self.check(core)
        calls = []
        original = core.run
        def run(*args, **kwargs):
            calls.append(tuple(map(str, args)))
            return original(*args, **kwargs)
        with mock.patch.object(core, 'run', side_effect=run):
            self.check(core)
        self.assertEqual([c[0] for c in calls].count('status'), 2)  # Batch snapshot + fresh publication guard
        self.assertEqual([c[0] for c in calls].count('proplist'), 2)  # Revalidate properties before publishing
        self.assertEqual([c[0] for c in calls].count('cat'), 0)
        self.assertEqual([c[0] for c in calls].count('info'), 2)  # HEAD + local repository identity
        self.assertTrue(any('HEAD' in c for c in calls))

    def test_batch_local_properties_rechecked_after_warm_scan(self):
        core = self.start()
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        self.assertEqual(self.check(core)['noDiffPaths'], ['a.txt'])
        core.run('propset', 'custom:flag', 'local change', self.target/'a.txt')
        result = self.check(core)
        self.assertEqual(result['noDiffPaths'], ['a.txt'])
        self.assertEqual(result['localStates']['a.txt'], 'same')
        self.assertNotIn('a.txt', result['localIssues'])

    def test_batch_reader_matches_individual_queries_for_special_names_and_missing_files(self):
        core = self.start()
        names = ['a.txt', '中文 @ file.txt', 'missing.txt']
        (self.target/names[1]).write_text('special name')
        core.run('add', str(self.target/names[1])+'@')
        core.run('propset', 'custom:flag', 'value', str(self.target/names[1])+'@')
        expected = {name: staged_sync.local_state(core, self.config, name) for name in names}
        import types
        reader = types.SimpleNamespace(**vars(core))
        reader.run = staged_sync.remaining_local_reader(core, self.config, [{'path': n} for n in names])
        actual = {name: staged_sync.local_state(reader, self.config, name) for name in names}
        self.assertEqual(actual, expected)

    def test_unrelated_repository_revision_reuses_pinned_file_reads(self):
        core = self.start()
        first = self.check(core)
        core.run('mkdir', self.config['root']+'/unrelated', '-m', 'unrelated change')
        calls=[]
        original=core.run
        def run(*args, **kwargs):
            calls.append(tuple(map(str,args)))
            return original(*args, **kwargs)
        with mock.patch.object(core,'run',side_effect=run):
            result=self.check(core)
        self.assertGreater(result['snapshot'],first['snapshot'])
        self.assertEqual(result['differentPaths'], first['differentPaths'])
        self.assertEqual([c[0] for c in calls].count('diff'),2)
        self.assertFalse(any(c[0]=='cat' for c in calls))

    def test_summary_failure_falls_back_to_current_revision(self):
        core = self.start()
        self.check(core)
        self.commit(self.target, 'a.txt', b'one\nchanged\nthree\n', 'release')
        original=core.run
        import subprocess
        def run(*args, **kwargs):
            if args[0]=='diff': return subprocess.CompletedProcess(args,1,b'',b'unavailable')
            return original(*args, **kwargs)
        with mock.patch.object(core,'run',side_effect=run):
            self.assertEqual(self.check(core)['noDiffPaths'],['a.txt'])

    def test_ancestor_mergeinfo_does_not_invalidate_unchanged_files(self):
        core = self.start()
        self.check(core)
        core.run('propset','custom:directory','changed',self.target)
        core.run('commit',self.target,'-m','directory property only','--username','release')
        calls=[]
        original=core.run
        def run(*args, **kwargs):
            calls.append(tuple(map(str,args)))
            return original(*args, **kwargs)
        with mock.patch.object(core,'run',side_effect=run):
            self.assertEqual(self.check(core)['differentPaths'],['a.txt'])
        self.assertFalse(any(c[0]=='cat' for c in calls))

    def test_partial_results_are_published_before_slow_file_finishes(self):
        core = self.start()
        import threading, types, copy
        slow = threading.Event()
        published = threading.Event()
        fast = self.report['fileItems'][0]
        extra = dict(fast, path='slow.txt')
        self.report['fileItems'].append(extra)
        core.write_json(self.folder/'report.json', self.report)
        core.write_json(self.folder/'review.json', dict(reportHash=core.file_sync.report_hash(self.report), items={}))
        worker = types.SimpleNamespace(**vars(core))
        def emit(result):
            if 'a.txt' in result['differentPaths']:
                saved = json.loads((self.folder/'remaining-last.json').read_text())
                self.assertIn('a.txt', saved['differentPaths'])
                self.assertFalse(saved['complete'])
                published.set(); slow.set()
        worker.sync_remaining = emit
        original=staged_sync.remote
        def remote(core, config, path, revision):
            if path=='slow.txt':
                if not slow.wait(15): raise RuntimeError('fast result did not publish')
                raise RuntimeError('slow file unavailable')
            return original(core,config,path,revision)
        with mock.patch.object(staged_sync,'remote',side_effect=remote):
            result=staged_sync.remaining_diff(worker,self.folder)
        self.assertTrue(published.is_set())
        self.assertIn('slow.txt',result['errors'])
        self.assertTrue(result['complete'])

    def test_manual_merge_by_different_author_is_also_recognized(self):
        core=self.start()
        self.commit(self.target,'a.txt',b'one\nchanged\nthree\n','another.user')
        result=self.check(core)
        self.assertEqual(result['noDiffPaths'],['a.txt'])
        self.assertFalse(result['localIssues'])

    def scoped_fixture(self):
        core = self.start()
        item = self.report['fileItems'][0]
        self.report['fileItems'] += [dict(item, path='other/a.txt'), dict(item, path='untouched.txt')]
        core.write_json(self.folder/'report.json', self.report)
        core.write_json(self.folder/'review.json', dict(reportHash=core.file_sync.report_hash(self.report), items={}))
        return core

    def test_scoped_single_reads_only_exact_path_and_preserves_other_results(self):
        import hashlib, types
        core = self.scoped_fixture()
        saved = dict(snapshot=self.config['snapshot'], reportDigest=hashlib.sha256((self.folder/'report.json').read_bytes()).hexdigest(),
                     noDiffPaths=['other/a.txt'], differentPaths=[], errors={'untouched.txt':'previous error'},
                     localIssues={'other/a.txt':'local changes'}, complete=False)
        core.write_json(self.folder/'remaining-last.json', saved)
        counts=[]; worker=types.SimpleNamespace(**vars(core)); worker.sync_files=lambda n,total:counts.append((n,total))
        reader=staged_sync.remaining_local_reader; remote=staged_sync.remote
        with mock.patch.object(staged_sync,'remaining_local_reader', wraps=reader) as local, mock.patch.object(staged_sync,'remote', wraps=remote) as reads:
            result=staged_sync.remaining_diff(worker,self.folder,['a.txt','a.txt'])
        self.assertEqual([i['path'] for i in local.call_args.args[2]], ['a.txt'])
        self.assertTrue(all(call.args[2]=='a.txt' for call in reads.call_args_list))
        self.assertEqual(result['differentPaths'],['a.txt']); self.assertFalse(result['errors'])
        self.assertEqual(counts[-1],(1,1))
        persisted=json.loads((self.folder/'remaining-last.json').read_text())
        self.assertEqual(persisted['noDiffPaths'],['other/a.txt'])
        self.assertEqual(persisted['errors'],{'untouched.txt':'previous error'})
        self.assertEqual(persisted['localIssues'],{'other/a.txt':'local changes'})
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')

    def test_scoped_empty_or_unknown_never_falls_back_to_full_scan(self):
        core=self.scoped_fixture()
        with mock.patch.object(core,'info',side_effect=AssertionError('must not contact SVN')):
            for paths in ([], ['missing.txt'], ['a.txt','../a.txt']):
                with self.assertRaises(RuntimeError): staged_sync.remaining_diff(core,self.folder,paths)

    def test_scoped_batch_progress_and_partial_persistence(self):
        import types
        core=self.scoped_fixture(); worker=types.SimpleNamespace(**vars(core)); counts=[]
        worker.sync_files=lambda n,total:counts.append((n,total))
        result=staged_sync.remaining_diff(worker,self.folder,['a.txt','other/a.txt'])
        self.assertEqual(counts[-1],(2,2))
        self.assertEqual(set(result['differentPaths'])|set(result['errors'])|set(result['noDiffPaths']), {'a.txt','other/a.txt'})
        saved=json.loads((self.folder/'remaining-last.json').read_text())
        self.assertFalse(saved['complete'])
        self.assertNotIn('untouched.txt', saved['errors'])

    def test_scoped_new_head_does_not_summarize_whole_branch_or_replace_snapshot_cache(self):
        core=self.start(); self.check(core)
        cache=self.folder.parent/'remaining-snapshots.json'; previous=cache.read_bytes()
        core.run('mkdir', self.config['root']+'/unrelated', '-m', 'unrelated change')
        calls=[]; original=core.run
        def run(*args,**kwargs):
            calls.append(tuple(map(str,args)));return original(*args,**kwargs)
        with mock.patch.object(core,'run',side_effect=run):
            result=staged_sync.remaining_diff(core,self.folder,['a.txt'])
        self.assertEqual(result['differentPaths'],['a.txt'])
        self.assertFalse(any(c[0]=='diff' and '--summarize' in c for c in calls))
        self.assertEqual(cache.read_bytes(),previous)

    def test_scoped_cli_passes_explicit_path_without_expanding_scope(self):
        import subprocess,sys
        self.scoped_fixture()
        for flag in ('--verify-path','--path'):
            result=subprocess.run([sys.executable,fixtures.sync.__file__,'remaining-diff','--folder',str(self.folder),flag,'a.txt'],capture_output=True,check=True)
            payload=json.loads(result.stdout)
            self.assertEqual(payload['differentPaths'],['a.txt'])
            self.assertFalse(payload['noDiffPaths']);self.assertFalse(payload['errors'])
