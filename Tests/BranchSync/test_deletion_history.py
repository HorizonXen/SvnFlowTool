import unittest
from types import SimpleNamespace
from unittest import mock
import xml.etree.ElementTree as ET
from test_config_identity import table,values
from file_sync import latest_scope_patches,merge_data
from workbook_cells import WorkbookMergeSession,WorkbookReplay
from workbook_history import DeletionHistory,validate
from test_workbook import parts,pack

class HistoryFixture:
    def __init__(self,after,later):
        self.after=after;self.later=later;self.calls=[]
        self.config=dict(dev='svn://repo/dev',root='svn://repo',author='chosen',snapshot=max([5]+[r for r,_,_ in later]))
    def urlpath(self,root,path):return root+'/'+path
    def relpath(self,path,url,root):return path[len('/dev/'):]
    def info(self,*args):return {'revision':self.config['snapshot']}
    def run(self,*args):
        self.calls.append(args)
        if args[0]=='log':
            doc=ET.Element('log')
            for rev,author,_ in self.later:
                e=ET.SubElement(doc,'logentry',revision=str(rev));ET.SubElement(e,'author').text=author
                p=ET.SubElement(e,'paths');ET.SubElement(p,'path',action='M',kind='file').text='/dev/config.xlsx'
            return SimpleNamespace(stdout=ET.tostring(doc))
        if args[0]=='cat':return SimpleNamespace(stdout=next(data for r,_,data in self.later if r==args[2]))
        raise AssertionError(args)

def run(before,after,target,later=()):
    core=HistoryFixture(after,later);dev=later[-1][2] if later else after
    session=WorkbookMergeSession(dev);replay=WorkbookReplay(target,session=session)
    audit=DeletionHistory(core,core.config,'config.xlsx',session,5)
    clean=audit.prepare(before,after,5,replay)
    project=lambda a,b,t:merge_data(a,b,t,'config.xlsx',latest=True,scope_projection=True,workbook_session=session)
    for a,b in latest_scope_patches(clean,after,dev,project):replay.apply(a,b)
    return replay.finish(),audit.evidence(),core

class DeletionHistoryTests(unittest.TestCase):
    def test_unchanged_duplicate_sheet_rewritten_xml_needs_no_deletion_identity(self):
        before=table([(6,dict(ID=1,value=10)),(7,dict(ID=1,value=20))])
        p=parts(before);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<sheetData>',b'\n<sheetData>')
        after=pack(p);core=HistoryFixture(after,[]);session=WorkbookMergeSession(after)
        audit=DeletionHistory(core,core.config,'config.xlsx',session,5)
        self.assertEqual(audit.prepare(before,after,5,None),before)
        self.assertEqual(audit.evidence()['deletions'],[])
        changed=table([(6,dict(ID=1,value=99)),(7,dict(ID=1,value=20))])
        with self.assertRaisesRegex(ValueError,'配置 ID 重复'):
            audit.prepare(before,changed,5,None)

    def test_layout_only_edit_on_duplicate_ids_preserves_release_cells(self):
        before=table([(6,dict(ID=1,value=10)),(7,dict(ID=1,value=20))])
        p=parts(before);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<sheetData>',b'<sheetFormatPr defaultRowHeight="17"/><sheetData>')
        after=pack(p);target=table([(6,dict(ID=1,value=90)),(7,dict(ID=1,value=80))])
        result,evidence,_=run(before,after,target)
        self.assertEqual(values(result),values(target))
        self.assertEqual(evidence['deletions'],[])

    def setUp(self):
        self.before=table([(6,dict(ID=1,value=10)),(7,dict(value='deleted'))])
        self.after=table([(6,dict(ID=1,value=10))])
        self.target=table([(10,dict(ID=1,value=90,other=8)),(22,dict(value='deleted'))])
    def test_unchanged_later_history_deletes_exact_moved_keyless_record(self):
        later=table([(9,dict(ID=1,value=30))])
        result,evidence,core=run(self.before,self.after,self.target,[(6,'other',later)])
        self.assertNotIn('B22',values(result));self.assertEqual(values(result)['B10'],'90')
        self.assertEqual(values(result)['C10'],'8')
        self.assertEqual(evidence['deletions'][0]['otherAuthors'],['other'])
        self.assertEqual(evidence['deletions'][0]['keylessRows'],[7])
        validate(core,core.config,'config.xlsx',evidence)
    def test_absent_release_record_preserves_unrelated_records(self):
        target=table([(12,dict(ID=2,value=90))])
        result,_,_=run(self.before,self.after,target)
        self.assertEqual(values(result),values(target))

    def test_batch_can_mix_already_absent_and_exact_present_deletions(self):
        before=table([(6,dict(ID=1,value=10)),(7,dict(value='absent')),(8,dict(value='deleted'))])
        result,_,_=run(before,self.after,self.target)
        self.assertNotIn('B22',values(result));self.assertEqual(values(result)['B10'],'90')
    def test_restore_then_delete_is_detected_despite_identical_tip(self):
        restored=table([(6,dict(ID=1,value=10)),(30,dict(value='deleted'))])
        with self.assertRaisesRegex(ValueError,'r6 / other'):
            run(self.before,self.after,self.target,[(6,'other',restored),(7,'chosen',self.after)])
    def test_restored_with_assigned_id_and_edited_value_is_ambiguous(self):
        restored=table([(6,dict(ID=1,value=10)),(30,dict(ID=9,value='edited'))])
        with self.assertRaisesRegex(ValueError,'无法排除恢复'):
            run(self.before,self.after,self.target,[(6,'other',restored)])
    def test_changed_or_duplicate_release_keyless_row_is_not_deleted(self):
        for rows in ([(22,dict(value='edited'))],[(22,dict(value='deleted')),(23,dict(value='deleted'))]):
            with self.subTest(rows=rows),self.assertRaisesRegex(ValueError,'Release'):
                run(self.before,self.after,table(rows))
    def test_duplicate_source_is_not_certified(self):
        duplicate=table([(6,dict(ID=1,value=10)),(7,dict(value='deleted')),(8,dict(value='deleted'))])
        with self.assertRaisesRegex(ValueError,'不唯一'):run(duplicate,self.after,self.target)
    def test_keyed_other_author_restore_then_delete_is_detected(self):
        before=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))])
        after=table([(6,dict(ID=1,value=10))])
        with self.assertRaisesRegex(ValueError,'其他作者修改或恢复'):
            run(before,after,before,[(6,'other',before),(7,'chosen',after)])
    def test_keyed_same_author_restore_uses_latest_data(self):
        before=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))])
        after=table([(6,dict(ID=1,value=10))])
        restored=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=30))])
        result,_,_=run(before,after,before,[(6,'chosen',restored)])
        self.assertEqual(values(result)['B7'],'30')
    def test_history_failure_is_not_evidence_of_absence(self):
        with mock.patch.object(HistoryFixture,'run',side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError,'offline'):
                run(self.before,self.after,self.target,[(6,'other',self.after)])
    def test_acceptance_rechecks_history_even_when_content_returns_to_same(self):
        _,evidence,core=run(self.before,self.after,self.target)
        core.later=[(6,'other',self.before),(7,'chosen',self.after)];core.config['snapshot']=7
        with self.assertRaisesRegex(RuntimeError,'历史已变化'):
            validate(core,core.config,'config.xlsx',evidence)
    def test_old_evidence_cannot_be_accepted(self):
        core=HistoryFixture(self.after,[])
        with self.assertRaisesRegex(RuntimeError,'规则已更新'):validate(core,core.config,'config.xlsx',None)

    def test_deleted_sheet_absent_in_later_versions_is_certified(self):
        p=parts(self.after);p['xl/workbook.xml']=p['xl/workbook.xml'].replace(b'name="Main"',b'name="Other"');after=pack(p)
        result,evidence,_=run(self.before,after,self.before,[(6,'other',after)])
        self.assertEqual(evidence['deletions'][0]['deletedSheets'],['Main'])
        from workbook_cells import Book
        self.assertNotIn('Main',Book(result).sheets)

    def test_sheet_restored_then_removed_by_other_author_is_blocked(self):
        p=parts(self.after);p['xl/workbook.xml']=p['xl/workbook.xml'].replace(b'name="Main"',b'name="Other"');after=pack(p)
        with self.assertRaisesRegex(ValueError,'工作表删除后被其他作者'):
            run(self.before,after,self.before,[(6,'other',self.before),(7,'chosen',after)])

    def test_file_deleted_without_later_changes_is_certified(self):
        result,evidence,_=run(self.before,None,self.before)
        self.assertIsNone(result);self.assertTrue(evidence['deletions'][0]['fileDeleted'])

    def test_file_restore_then_delete_is_blocked(self):
        with self.assertRaisesRegex(ValueError,'文件删除后被其他作者'):
            run(self.before,None,self.before,[(6,'other',self.before),(7,'chosen',None)])

class EmptyFormulaHistoryTests(unittest.TestCase):
    def book(self, *, formula=False, row=7, cache='<v/>', kind='str', field='', literal=False, keyed=False, metadata=''):
        data=table([(6,dict(ID=1,value=10))]+([(row,dict(ID=2))] if keyed else []),('ID','value',field))
        if not formula:return data
        p=parts(data)
        cell=f'<c r="C{row}" t="{kind}" {metadata}><f>IF(A7=&quot;&quot;,&quot;&quot;,A7)</f>{cache}</c>'
        if literal:cell+=f'<c r="B{row}"><v>42</v></c>'
        xml=p['xl/worksheets/sheet1.xml']
        if keyed:xml=xml.replace(f'<row r="{row}">'.encode(),(f'<row r="{row}">'+cell).encode())
        else:xml=xml.replace(b'</sheetData>',(f'<row r="{row}">'+cell+'</row></sheetData>').encode())
        p['xl/worksheets/sheet1.xml']=xml
        return pack(p)
    def test_blank_helper_formulas_certified_with_later_new_ids(self):
        before=self.book(formula=True);after=self.book();later=self.book(keyed=True)
        result,evidence,core=run(before,after,after,[(6,'other',later)])
        self.assertEqual(values(result),values(after))
        self.assertEqual(evidence['deletions'][0]['emptyFormulaRows'],[7])
        validate(core,core.config,'config.xlsx',evidence)
    def test_formula_restore_then_remove_and_rekeyed_restore_blocked(self):
        for keyed in (False,True):
            with self.subTest(keyed=keyed),self.assertRaisesRegex(ValueError,'r6 / other.*无法排除恢复'):
                run(self.book(formula=True),self.book(),self.book(),[(6,'other',self.book(formula=True,keyed=keyed,row=22)),(7,'chosen',self.book())])
    def test_edited_literal_restore_still_blocked(self):
        restored=table([(6,dict(ID=1,value=10)),(22,{'':99})],('ID','value',''))
        with self.assertRaisesRegex(ValueError,'无法排除恢复'):
            run(self.book(formula=True),self.book(),self.book(),[(6,'other',restored)])
    def test_release_formula_or_unknown_keyless_value_blocks(self):
        for target in (self.book(formula=True,row=22),table([(6,dict(ID=1,value=10)),(22,{'':99})],('ID','value',''))):
            with self.assertRaisesRegex(ValueError,'Release'):
                run(self.book(formula=True),self.book(),target)
    def test_only_empty_undeclared_plain_formula_rows_qualify(self):
        for kwargs in (dict(cache='<v>0</v>',kind='n'),dict(cache='<v> </v>'),dict(cache=''),dict(field='helper'),dict(literal=True),dict(metadata='cm="1"')):
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(ValueError,'含公式'):
                run(self.book(formula=True,**kwargs),self.book(field=kwargs.get('field','')),self.book(field=kwargs.get('field','')))
    def test_formulas_remaining_after_delete_block(self):
        with self.assertRaisesRegex(ValueError,'仍有公式'):
            run(self.book(formula=True),self.book(formula=True,keyed=True,row=22),self.book())
    def test_new_history_invalidates_formula_certificate(self):
        _,evidence,core=run(self.book(formula=True),self.book(),self.book())
        core.later=[(6,'other',self.book(formula=True)),(7,'chosen',self.book())];core.config['snapshot']=7
        with self.assertRaisesRegex(RuntimeError,'历史已变化'):
            validate(core,core.config,'config.xlsx',evidence)
    def test_removing_shared_formula_master_preserves_surviving_formula(self):
        from workbook_cells import Book,first
        from workbook_history import remove_rows
        p=parts(self.book(formula=True));xml=p['xl/worksheets/sheet1.xml']
        xml=xml.replace(b'<f>',b'<f t="shared" si="0" ref="C7:C8">')
        xml=xml.replace(b'</sheetData>',b'<row r="8"><c r="C8" t="str"><f t="shared" si="0"/><v/></c></row></sheetData>')
        p['xl/worksheets/sheet1.xml']=xml;b=Book(pack(p));remove_rows(b,'Main',[7]);cells=Book(b.save()).cells('Main')
        self.assertNotIn('C7',cells)
        self.assertEqual(first(cells['C8'],'f').firstChild.nodeValue,'IF(A8="","",A8)')
        self.assertFalse(first(cells['C8'],'f').hasAttribute('t'))
