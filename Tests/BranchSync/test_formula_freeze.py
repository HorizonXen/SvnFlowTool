import unittest
from test_config_identity import table, merge, values
from test_workbook import parts, pack, NS
from workbook_cells import Book, first, WorkbookReplay


def formula(data, address, expression='1+1', kind=None, cache=None):
    from lxml import etree as E
    p=parts(data);root=E.fromstring(p['xl/worksheets/sheet1.xml']);q='{'+NS+'}'
    cell=root.find('.//'+q+'c[@r="'+address+'"]')
    if kind is not None:cell.set('t',kind)
    if cache is not None:
        for child in list(cell):cell.remove(child)
        E.SubElement(cell,q+'v').text=cache
    f=E.Element(q+'f');f.text=expression;cell.insert(0,f)
    p['xl/worksheets/sheet1.xml']=E.tostring(root);return pack(p)


class FormulaFreezeTests(unittest.TestCase):
    def test_whole_sheet_freeze_uses_release_values_including_release_only_ids(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6')
        b=table([(6,dict(ID=1,value=10))])
        t=formula(formula(table([(9,dict(ID=1,value=99,other=8)),(10,dict(ID=2,value=88))]),'B9'),'B10')
        result=merge(a,b,t);cells=Book(result).cells('Main')
        self.assertEqual(values(result)['B9'],'99');self.assertEqual(values(result)['B10'],'88')
        self.assertEqual(values(result)['C9'],'8')
        self.assertTrue(all(first(c,'f') is None for c in cells.values()))

    def test_freeze_then_apply_actual_value_edit(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6')
        b=table([(6,dict(ID=1,value=11))])
        t=formula(table([(9,dict(ID=1,value=99))]),'B9')
        self.assertEqual(values(merge(a,b,t))['B9'],'11')

    def test_missing_id_with_only_conversion_does_not_create_record(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6');b=table([(6,dict(ID=1,value=10))])
        t=formula(table([(9,dict(ID=2,value=99))]),'B9');result=merge(a,b,t)
        self.assertEqual(values(result)['A9'],'2');self.assertEqual(values(result)['B9'],'99')
        self.assertNotIn('A6',values(result));self.assertIsNone(first(Book(result).cells('Main')['B9'],'f'))

    def test_missing_id_with_real_value_edit_still_blocks(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6');b=table([(6,dict(ID=1,value=11))])
        with self.assertRaisesRegex(RuntimeError,'Release 缺少配置 ID'):
            merge(a,b,table([(9,dict(ID=2,value=99))]))

    def test_partial_freeze_matches_moved_id_and_keeps_other_formulas(self):
        a=formula(formula(table([(6,dict(ID=1,value=10,other=20))]),'B6'),'C6')
        b=formula(table([(6,dict(ID=1,value=10,other=20))]),'C6')
        t=formula(formula(table([(9,dict(ID=1,value=99,other=88))]),'B9'),'C9')
        result=merge(a,b,t);cells=Book(result).cells('Main')
        self.assertEqual(values(result)['B9'],'99');self.assertIsNone(first(cells['B9'],'f'))
        self.assertIsNotNone(first(cells['C9'],'f'))

    def test_partial_missing_id_pure_conversion_is_noop(self):
        a=formula(formula(table([(6,dict(ID=1,value=10,other=20))]),'B6'),'C6')
        b=formula(table([(6,dict(ID=1,value=10,other=20))]),'C6')
        t=formula(table([(9,dict(ID=2,value=99))]),'B9')
        self.assertIsNotNone(first(Book(merge(a,b,t)).cells('Main')['B9'],'f'))

    def test_saved_string_empty_string_boolean_and_numeric_types(self):
        for kind,cache,target in [('str','hello','release'),('str','',''),('str',' hello ',' release '),('b','1','0'),('n','1.0E1','9.9E1')]:
            with self.subTest(kind=kind,cache=cache):
                literal=cache if kind=='str' else int(float(cache))
                a=formula(table([(6,dict(ID=1,value=literal))]),'B6',kind=kind,cache=cache)
                b=table([(6,dict(ID=1,value=literal))])
                if kind=='b':
                    p=parts(b);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="B6">',b'<c r="B6" t="b">');b=pack(p)
                t=formula(table([(9,dict(ID=1,value=99))]),'B9',kind=kind,cache=target)
                cell=Book(merge(a,b,t)).cells('Main')['B9']
                self.assertIsNone(first(cell,'f'))
                if kind=='str':self.assertIn(target,cell.toxml());self.assertEqual(cell.getAttribute('t'),'inlineStr')
                else:self.assertEqual(first(cell,'v').firstChild.nodeValue,'0' if kind=='b' else '99')

    def test_missing_release_cache_blocks_instead_of_using_dev(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6');b=table([(6,dict(ID=1,value=10))])
        t=formula(table([(9,dict(ID=1,value=99))]),'B9');p=parts(t)
        p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<v>99</v>',b'<v/>')
        with self.assertRaisesRegex(RuntimeError,'没有已保存的计算结果'):merge(a,b,pack(p))

    def test_partial_single_cell_array_can_follow_moved_id(self):
        a=formula(formula(table([(6,dict(ID=1,value=10,other=20))]),'B6'),'C6')
        p=parts(a);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<f>1+1</f>',b'<f t="array" ref="B6">1+1</f>',1);a=pack(p)
        b=formula(table([(6,dict(ID=1,value=10,other=20))]),'C6')
        t=formula(table([(9,dict(ID=1,value=99,other=88))]),'B9')
        result=merge(a,b,t)
        self.assertEqual(values(result)['B9'],'99');self.assertIsNone(first(Book(result).cells('Main')['B9'],'f'))

    def test_replay_does_not_modify_cached_source_books_and_is_idempotent(self):
        a=formula(table([(6,dict(ID=1,value=10))]),'B6');b=table([(6,dict(ID=1,value=10))])
        t=formula(table([(9,dict(ID=1,value=99))]),'B9');replay=WorkbookReplay(t)
        source=replay.source(a);replay.apply(a,b)
        self.assertIsNotNone(first(source.cells('Main')['B6'],'f'))
        replay.apply(a,b);result=replay.finish()
        self.assertEqual(values(result)['B9'],'99');self.assertIsNone(first(Book(result).cells('Main')['B9'],'f'))
