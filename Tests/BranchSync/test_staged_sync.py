import json
import pathlib
import unittest
import test_file_sync as file_tests
import staged_sync


class StagedSyncTests(unittest.TestCase):
    setUp = file_tests.FileSyncTests.setUp
    tearDown = file_tests.FileSyncTests.tearDown
    commit = file_tests.FileSyncTests.commit
    report_files = file_tests.FileSyncTests.report_files

    def start(self):
        from test_sync import sync
        self.report_files()
        self.state = {'mode':'review-v1','items':{},'reportHash':sync.file_sync.report_hash(self.report)}
        sync.write_json(self.folder/'review.json', self.state)
        return sync

    def test_stage_read_only_accept_single_file_and_backup(self):
        core = self.start()
        before = (self.target/'a.txt').read_bytes()
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),before)
        self.assertEqual(core.fingerprint(str(self.target)),[])
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(),b'one\nchanged\nthree\n')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\nchanged\nthree\n')
        self.assertEqual((self.folder/'本地原件/a.txt').read_bytes(),before)
        self.assertEqual(core.run('cat',self.config['release']+'/a.txt').stdout,before)
        self.assertEqual((self.target/'binary.bin').read_bytes(),b'\x00old')
        with self.assertRaises(RuntimeError): staged_sync.operate(core,self.folder,'accept','a.txt')

    def test_low_risk_batch_after_unchanged_working_revision_update(self):
        from test_sync import sync
        base = b''.join(('line %d\n' % i).encode() for i in range(20))
        paths = ['batch-a.txt', 'batch-b.txt', 'batch-c.txt']
        for path in paths:
            self.commit(self.dev, path, base)
            self.commit(self.target, path, base, 'release')
            self.commit(self.dev, path, base.replace(b'line 5\n', b'changed\n'))
        core = self.start()
        for path in paths:
            entry = staged_sync.operate(core, self.folder, 'stage', path)
            self.assertEqual(entry['risk']['level'], 'low')
        self.commit(self.dev, 'unrelated.txt', b'unrelated')
        core.run('update', self.target)
        core.write_json(self.folder/'review-failures.json', dict.fromkeys(paths, '本地文件在生成对比后已变化，请保留修改并重新合入'))
        staged_sync.repair_review(core, self.folder)
        self.assertEqual(json.loads((self.folder/'review-failures.json').read_text()), {})
        for path in paths:
            result = staged_sync.operate(core, self.folder, 'accept-low', path)
            self.assertEqual(result['status'], 'accepted')
            self.assertEqual((self.target/path).read_bytes(), base.replace(b'line 5\n', b'changed\n'))
            self.assertEqual(core.run('cat', self.config['release']+'/'+path).stdout, base)

    def test_revision_update_does_not_hide_real_local_changes(self):
        import copy
        original = dict(hash='baseline', properties={}, item='normal', status=dict(item='normal', props='normal', revision='10'))
        updated = copy.deepcopy(original)
        updated['status']['revision'] = '11'
        self.assertTrue(staged_sync.same_reviewed_local(updated, original))
        for key, value in [('hash', 'edited'), ('properties', {'note':'changed'}), ('item', 'modified')]:
            changed = dict(updated, **{key:value})
            self.assertFalse(staged_sync.same_reviewed_local(changed, original))
        for key, value in [('tree-conflicted', 'true'), ('props', 'modified'), ('revision', '9')]:
            changed = copy.deepcopy(updated); changed['status'][key] = value
            self.assertFalse(staged_sync.same_reviewed_local(changed, original))

    def test_inherited_candidate_can_be_confirmed_with_current_batch_backup(self):
        core = self.start()
        staged_sync.operate(core,self.folder,'stage','a.txt')
        before = (self.target/'a.txt').read_bytes()
        destination = self.root/'next-batch'; destination.mkdir()
        for name in ('report.json','review.json'):
            (destination/name).write_bytes((self.folder/name).read_bytes())
        old_ledger = (self.folder/'review.json').read_bytes()
        self.assertEqual(staged_sync.repair_review(core,destination), ['a.txt'])
        self.assertEqual((self.target/'a.txt').read_bytes(),before)
        staged_sync.operate(core,destination,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\nchanged\nthree\n')
        self.assertEqual((destination/'本地原件/a.txt').read_bytes(),before)
        self.assertEqual((self.folder/'review.json').read_bytes(),old_ledger)
        self.assertEqual(core.run('cat',self.config['release']+'/a.txt').stdout,before)

    def test_latest_remote_is_baseline_even_when_working_copy_is_old(self):
        core = self.start()
        other = self.root/'other'
        core.run('checkout',self.config['release'],other)
        self.commit(other,'a.txt',b'newRelease\ntwo\nthree\n','release')
        core = self.start()
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual(pathlib.Path(entry['baseline']).read_bytes(),b'newRelease\ntwo\nthree\n')
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(),b'newRelease\nchanged\nthree\n')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'newRelease\nchanged\nthree\n')

    def test_stage_refreshes_release_after_old_catalog(self):
        core = self.start()
        old_snapshot = self.report['config']['snapshot']
        other = self.root/'new-release'; core.run('checkout',self.config['release'],other)
        self.commit(other,'a.txt',b'newRelease\ntwo\nthree\n','release')
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertGreater(entry['revision'],old_snapshot)
        self.assertEqual(pathlib.Path(entry['baseline']).read_bytes(),b'newRelease\ntwo\nthree\n')
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(),b'newRelease\nchanged\nthree\n')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')

    def test_remote_changed_after_review_blocks_without_write(self):
        core = self.start()
        staged_sync.operate(core,self.folder,'stage','a.txt')
        other = self.root/'other'; core.run('checkout',self.config['release'],other)
        self.commit(other,'a.txt',b'newRelease\ntwo\nthree\n','release')
        with self.assertRaisesRegex(RuntimeError,'最新 SVN 内容已变化'): staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\ntwo\nthree\n')

    def test_local_edit_after_stage_blocks_and_preserves_input(self):
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        (self.target/'a.txt').write_bytes(b'human editing')
        with self.assertRaisesRegex(RuntimeError,'本地文件.*变化'): staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'human editing')

    def test_overlapping_local_edit_cannot_be_silently_overwritten(self):
        (self.target/'a.txt').write_bytes(b'human editing')
        core = self.start()
        with self.assertRaisesRegex(RuntimeError,'无法独立拆分'):
            staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'human editing')

    def test_matching_local_modification_confirms_without_any_svn_write(self):
        data = b'one\nchanged\nthree\n'
        (self.target/'a.txt').write_bytes(data)
        core = self.start(); entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual(entry['local']['item'],'modified')
        before = staged_sync.local_state(core,self.config,'a.txt')
        stat = (self.target/'a.txt').stat()
        original_run = core.run
        def read_only(*args, **kwargs):
            self.assertNotIn(args[0], ('update','delete','add','propset','propdel','commit','revert'))
            return original_run(*args,**kwargs)
        core.run = read_only
        try: accepted = staged_sync.operate(core,self.folder,'accept','a.txt')
        finally: core.run = original_run
        self.assertTrue(accepted['acceptedExisting'])
        self.assertEqual(accepted['status'],'accepted')
        self.assertEqual(staged_sync.local_state(core,self.config,'a.txt'),before)
        self.assertEqual((self.target/'a.txt').stat().st_mtime_ns,stat.st_mtime_ns)
        self.assertEqual((self.target/'a.txt').read_bytes(),data)
        self.assertNotIn('pending',json.loads((self.folder/'review.json').read_text()))

    def test_matching_content_preserves_independent_local_properties(self):
        (self.target/'a.txt').write_bytes(b'one\nchanged\nthree\n')
        core = self.start()
        core.run('propset','local:note','keep',str(self.target/'a.txt'))
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertTrue(entry['includesLocalChanges'])
        self.assertEqual(entry['risk']['level'], 'high')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual(core.run('propget','local:note',str(self.target/'a.txt')).stdout.strip(),b'keep')

    def test_independent_local_text_and_outdated_remote_are_preserved(self):
        core = self.start()
        other = self.root/'other-release'
        core.run('checkout', self.config['release'], other)
        self.commit(other, 'a.txt', b'one\ntwo\nremote\n', 'release')
        local = b'local\ntwo\nthree\n'
        (self.target/'a.txt').write_bytes(local)
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        expected = b'local\nchanged\nremote\n'
        self.assertEqual(pathlib.Path(entry['candidate']).read_bytes(), expected)
        self.assertEqual((self.target/'a.txt').read_bytes(), local)
        self.assertTrue(entry['includesLocalChanges'])
        self.assertEqual(entry['risk']['level'], 'high')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(), expected)
        self.assertEqual((self.folder/'本地原件/a.txt').read_bytes(), local)
        self.assertEqual(core.run('cat', self.config['release']+'/a.txt').stdout, b'one\ntwo\nremote\n')

    def test_independent_local_workbook_cell_is_preserved(self):
        from test_workbook import book
        base = book(a='1', b='2', formula=False)
        self.commit(self.dev, 'book.xlsx', base, 'seed')
        self.commit(self.target, 'book.xlsx', base, 'seed')
        self.commit(self.dev, 'book.xlsx', book(a='3', b='2', formula=False))
        original = book(a='1', b='9', formula=False)
        (self.target/'book.xlsx').write_bytes(original)
        core = self.start()
        entry = staged_sync.operate(core,self.folder,'stage','book.xlsx')
        self.assertTrue(core.file_sync.same_data(pathlib.Path(entry['candidate']).read_bytes(), book(a='3',b='9',formula=False), 'book.xlsx'))
        staged_sync.operate(core,self.folder,'accept','book.xlsx')
        self.assertEqual((self.target/'book.xlsx').read_bytes(), pathlib.Path(entry['candidate']).read_bytes())
        self.assertEqual((self.folder/'本地原件/book.xlsx').read_bytes(), original)

    def test_local_lua_field_deletion_is_preserved_without_weakening_author_guard(self):
        base = b'return { a=1, b=2, c=3 }\n'
        self.commit(self.dev, 'config.lua', base, 'seed')
        self.commit(self.target, 'config.lua', base, 'seed')
        self.commit(self.dev, 'config.lua', b'return { a=4, b=2, c=3 }\n')
        local = b'return { a=1, c=3 }\n'
        (self.target/'config.lua').write_bytes(local)
        core = self.start()
        entry = staged_sync.operate(core,self.folder,'stage','config.lua')
        staged_sync.operate(core,self.folder,'accept','config.lua')
        actual = (self.target/'config.lua').read_bytes()
        self.assertIn(b'a=4', actual)
        self.assertNotIn(b'b=', actual)
        self.assertIn(b'c=3', actual)
        self.assertEqual((self.folder/'本地原件/config.lua').read_bytes(), local)

    def test_changed_review_must_not_discard_preserved_local_input(self):
        (self.target/'a.txt').write_bytes(b'local\ntwo\nthree\n')
        core = self.start()
        entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        changed = b'one\nchanged\nthree\n'
        pathlib.Path(entry['candidate']).write_bytes(changed)
        entry['candidateHash'] = core.file_sync.data_hash(changed)
        ledger = json.loads((self.folder/'review.json').read_text())
        ledger['items']['a.txt'] = entry
        core.write_json(self.folder/'review.json', ledger)
        with self.assertRaisesRegex(RuntimeError, '未完整保留本地修改'):
            staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(), b'local\ntwo\nthree\n')
        self.assertNotIn('pending', json.loads((self.folder/'review.json').read_text()))

    def test_edit_during_backup_is_preserved_before_revert(self):
        from unittest.mock import patch
        (self.target/'a.txt').write_bytes(b'local\ntwo\nthree\n')
        core = self.start()
        staged_sync.operate(core,self.folder,'stage','a.txt')
        backup = staged_sync.backup_before_write
        def editing(*args):
            result = backup(*args)
            (self.target/'a.txt').write_bytes(b'new unsaved input')
            return result
        with patch.object(staged_sync, 'backup_before_write', side_effect=editing):
            with self.assertRaisesRegex(RuntimeError, '备份期间本地文件已变化'):
                staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(), b'new unsaved input')
        self.assertNotIn('pending', json.loads((self.folder/'review.json').read_text()))

    def test_matching_local_content_still_checks_remote_changes(self):
        (self.target/'a.txt').write_bytes(b'one\nchanged\nthree\n')
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        other = self.root/'other'; core.run('checkout',self.config['release'],other)
        self.commit(other,'a.txt',b'new release','release')
        with self.assertRaisesRegex(RuntimeError,'最新 SVN 内容已变化'):
            staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'a.txt').read_bytes(),b'one\nchanged\nthree\n')

    def test_matching_hash_does_not_bypass_abnormal_svn_state(self):
        entry = {'candidateHash':'digest','properties':{}}
        for item, status in [('conflicted',{}),('added',{}),('missing',{}),('modified',{'tree-conflicted':'true'}),('modified',{'props':'conflicted'})]:
            local = {'hash':'digest','properties':{},'item':item,'status':status}
            self.assertFalse(staged_sync.local_matches_candidate(local,entry))

    def test_modified_candidate_blocked(self):
        core = self.start(); entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        pathlib.Path(entry['candidate']).write_bytes(b'edited')
        with self.assertRaisesRegex(RuntimeError,'副本已被修改'): staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual(core.fingerprint(str(self.target)),[])

    def test_skip_and_resume_state_do_not_write(self):
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertEqual(json.loads((self.folder/'review.json').read_text())['items']['a.txt']['status'],'ready')
        staged_sync.operate(core,self.folder,'defer','a.txt')
        self.assertEqual(core.fingerprint(str(self.target)),[])
        with self.assertRaises(RuntimeError): staged_sync.operate(core,self.folder,'accept','a.txt')

    def test_new_file(self):
        self.commit(self.dev,'new.txt',b'new content')
        core = self.start(); entry = staged_sync.operate(core,self.folder,'stage','new.txt')
        self.assertIsNone(entry['baseline']); self.assertFalse((self.target/'new.txt').exists())
        staged_sync.operate(core,self.folder,'accept','new.txt')
        self.assertEqual((self.target/'new.txt').read_bytes(),b'new content')

    def test_deleted_file(self):
        from test_sync import sync
        sync.run('delete',self.dev/'a.txt'); sync.run('commit',self.dev,'-m','delete','--username','sample.author')
        core = self.start(); entry = staged_sync.operate(core,self.folder,'stage','a.txt')
        self.assertIsNone(entry['candidate']); self.assertTrue((self.target/'a.txt').exists())
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertFalse((self.target/'a.txt').exists())

    def test_update_failure_preserves_pending_and_backup(self):
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        original_run = core.run
        def fail(*args, **kwargs):
            if args[0] == 'update': raise RuntimeError('test update failure')
            return original_run(*args,**kwargs)
        core.run = fail
        try:
            with self.assertRaisesRegex(RuntimeError,'test update failure'): staged_sync.operate(core,self.folder,'accept','a.txt')
        finally: core.run = original_run
        self.assertEqual((self.folder/'本地原件/a.txt').read_bytes(),b'one\ntwo\nthree\n')
        with self.assertRaisesRegex(RuntimeError,'上次写入未完成'): staged_sync.operate(core,self.folder,'accept','a.txt')

    def test_workbook_candidate_uses_existing_merge(self):
        from test_workbook import book
        baseline = book(a='1', b='2')
        self.commit(self.dev,'book.xlsx',baseline,'seed')
        self.commit(self.target,'book.xlsx',baseline,'seed')
        self.commit(self.dev,'book.xlsx',book(a='3', b='2'))
        core = self.start(); entry = staged_sync.operate(core,self.folder,'stage','book.xlsx')
        self.assertEqual((self.target/'book.xlsx').read_bytes(),baseline)
        staged_sync.operate(core,self.folder,'accept','book.xlsx')
        self.assertEqual((self.target/'book.xlsx').read_bytes(),pathlib.Path(entry['candidate']).read_bytes())

    def test_unrelated_local_edit_is_preserved(self):
        (self.target/'binary.bin').write_bytes(b'\x00human sibling')
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual((self.target/'binary.bin').read_bytes(),b'\x00human sibling')

    def test_remote_property_change_after_review_blocks(self):
        core = self.start(); staged_sync.operate(core,self.folder,'stage','a.txt')
        other = self.root/'other'; core.run('checkout',self.config['release'],other)
        core.run('propset','review-property','new',other/'a.txt')
        core.run('commit',other,'-m','property change','--username','release')
        with self.assertRaisesRegex(RuntimeError,'最新 SVN 内容已变化'): staged_sync.operate(core,self.folder,'accept','a.txt')
        self.assertEqual(core.fingerprint(str(self.target)),[])

    def test_path_escape_is_rejected(self):
        core = self.start()
        with self.assertRaises(RuntimeError): staged_sync.safe_path(self.target,'../outside')
        (self.target/'linked').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError): staged_sync.safe_path(self.target,'linked/outside')
