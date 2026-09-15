import unittest
from test_author_isolation import fixture
from test_workbook import parts,pack,NS
from file_sync import merge_data
from workbook_cells import Book,first

def table(rows,fields=('ID','value','other')):
 p=parts(fixture())
 def cell(col,row,value):
  address=chr(65+col)+str(row)
  if isinstance(value,int):return f'<c r="{address}"><v>{value}</v></c>'
  return f'<c r="{address}" t="inlineStr"><is><t>{value}</t></is></c>'
 xml='<row r="2">'+''.join(cell(c,2,'*'+f if f=='ID' else f) for c,f in enumerate(fields))+'</row>'
 for number,values in rows:
  xml+=f'<row r="{number}">'+''.join(cell(c,number,values[f]) for c,f in enumerate(fields) if f in values)+'</row>'
 p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData>{xml}</sheetData></worksheet>').encode()
 return pack(p)

def merge(a,b,t):return merge_data(a,b,t,'config.xlsx',latest=True)
def values(data):
 c=Book(data).cells('Main');out={}
 for addr,cell in c.items():
  n=first(cell,'v')
  if n is not None and n.firstChild:out[addr]=n.firstChild.nodeValue
 return out

class IdentityTests(unittest.TestCase):
 def test_different_rows_match_id_not_position(self):
  a=table([(6,dict(ID=303,value=71,other=6)),(9,dict(ID=302,value=100,other=0))])
  b=table([(6,dict(ID=303,value=72,other=6)),(9,dict(ID=302,value=100,other=0))])
  t=table([(6,dict(ID=302,value=100,other=0)),(20,dict(ID=303,value=71,other=8))])
  r=values(merge(a,b,t));self.assertEqual(r['B6'],'100');self.assertEqual(r['B20'],'72');self.assertEqual(r['C20'],'8')
 def test_already_present_value_does_not_modify_wrong_row(self):
  a=table([(6,dict(ID=303,value=71))]);b=table([(6,dict(ID=303,value=72))])
  t=table([(6,dict(ID=302,value=100)),(20,dict(ID=303,value=72))])
  self.assertEqual(values(merge(a,b,t)),values(t))
 def test_field_order_uses_field_name(self):
  a=table([(6,dict(ID=1,value=1,other=9))]);b=table([(6,dict(ID=1,value=2,other=9))])
  t=table([(8,dict(ID=1,value=3,other=8))],('ID','other','value'))
  r=values(merge(a,b,t));self.assertEqual(r['B8'],'8');self.assertEqual(r['C8'],'2')
 def test_reordered_author_rows_are_not_edits(self):
  a=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))])
  b=table([(7,dict(ID=1,value=10)),(6,dict(ID=2,value=20))])
  t=table([(8,dict(ID=1,value=99)),(9,dict(ID=2,value=88))])
  self.assertEqual(values(merge(a,b,t)),values(t))
 def test_missing_existing_id_stops(self):
  with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
   merge(table([(6,dict(ID=1,value=10))]),table([(6,dict(ID=1,value=11))]),table([(6,dict(ID=2,value=99))]))
 def test_duplicate_ids_stop(self):
  with self.assertRaisesRegex(RuntimeError,'ID 重复'):
   merge(table([(6,dict(ID=1,value=10))]),table([(6,dict(ID=1,value=11))]),table([(6,dict(ID=1,value=99)),(9,dict(ID=1,value=88))]))
 def test_new_id_appends_without_overwriting_occupied_row(self):
  a=table([(6,dict(ID=1,value=10))]);b=table([(6,dict(ID=1,value=10)),(7,dict(ID=3,value=30))])
  t=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))])
  r=values(merge(a,b,t));self.assertEqual(r['A7'],'2');self.assertEqual(r['A8'],'3');self.assertEqual(r['B8'],'30')
 def test_deleted_id_deletes_matched_record(self):
  a=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))]);b=table([(7,dict(ID=2,value=20))])
  t=table([(6,dict(ID=2,value=20)),(9,dict(ID=1,value=99))])
  r=values(merge(a,b,t));self.assertEqual(r['A6'],'2');self.assertNotIn('A9',r);self.assertNotIn('B9',r)

 def test_data_in_frozen_row_four_still_matches_id(self):
  a=table([(4,dict(ID=1,value=10))]);b=table([(4,dict(ID=1,value=11))]);t=table([(4,dict(ID=2,value=99)),(8,dict(ID=1,value=10))])
  r=values(merge(a,b,t));self.assertEqual(r['B4'],'99');self.assertEqual(r['B8'],'11')
 def test_composite_declared_key_matches_full_identity(self):
  fields=('ID','**Level','value')
  a=table([(6,{'ID':1,'**Level':1,'value':10}),(7,{'ID':1,'**Level':2,'value':20})],fields)
  b=table([(6,{'ID':1,'**Level':1,'value':11}),(7,{'ID':1,'**Level':2,'value':20})],fields)
  t=table([(6,{'ID':1,'**Level':2,'value':99}),(9,{'ID':1,'**Level':1,'value':10})],fields)
  r=values(merge(a,b,t));self.assertEqual(r['C6'],'99');self.assertEqual(r['C9'],'11')

 def test_empty_keyless_cells_and_styles_do_not_block(self):
  a=table([(6,dict(ID=1,value=10))]);b=table([(4,dict(value='')),(6,dict(ID=1,value=11))]);t=table([(8,dict(ID=1,value=10))])
  p=parts(b);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<row r="4">',b'<row r="4"><c r="A4" s="1"/>');b=pack(p)
  r=values(merge(a,b,t));self.assertEqual(r['B8'],'11');self.assertNotIn('B4',r)
 def test_real_keyless_content_change_still_stops(self):
  a=table([(4,dict(value=10)),(6,dict(ID=1,value=10))]);b=table([(4,dict(value=11)),(6,dict(ID=1,value=10))])
  with self.assertRaisesRegex(RuntimeError,'第 4 行缺少配置 ID'):merge(a,b,table([(6,dict(ID=1,value=99))]))
 def test_deleted_keyless_data_already_absent_from_release(self):
  a=table([(7,dict(value='section')),(9,dict(value=50)),(10,dict(ID=1,value=10))])
  b=table([(7,dict(value='section')),(8,dict(ID=1,value=11))])
  t=table([(12,dict(value='section')),(15,dict(ID=1,value=99,other=8))])
  r=merge(a,b,t)
  self.assertEqual(values(r)['B15'],'11');self.assertEqual(values(r)['C15'],'8')
  self.assertIn('section',Book(r).cells('Main')['B12'].toxml())
 def test_deleted_keyless_data_present_or_edited_in_release_stops(self):
  a=table([(9,dict(value=50)),(10,dict(ID=1,value=10))])
  b=table([(8,dict(ID=1,value=11))])
  for value in (50,51):
   with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'第 9 行缺少配置 ID'):
    merge(a,b,table([(12,dict(value=value)),(15,dict(ID=1,value=99))]))
 def test_keyless_deletion_does_not_hide_extra_duplicate_in_release(self):
  a=table([(7,dict(value='section')),(9,dict(value=50)),(10,dict(ID=1,value=10))])
  b=table([(7,dict(value='section')),(8,dict(ID=1,value=11))])
  t=table([(12,dict(value='section')),(13,dict(value='section')),(15,dict(ID=1,value=99))])
  with self.assertRaisesRegex(RuntimeError,'第 9 行缺少配置 ID'):merge(a,b,t)
 def test_keyless_formula_change_still_stops(self):
  a=table([(6,dict(ID=1,value=10))]);p=parts(a)
  p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<sheetData>',b'<sheetData><row r="4"><c r="B4"><f>1+1</f></c></row>')
  with self.assertRaisesRegex(RuntimeError,'第 4 行缺少配置 ID'):merge(a,pack(p),table([(6,dict(ID=1,value=99))]))

 def test_xml_space_storage_change_keeps_foreign_values(self):
  a=table([(4,dict(value='client')),(6,dict(ID=1,value='same',other=1))])
  p=parts(a);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<t>',b'<t xml:space="preserve">');a=pack(p)
  b=table([(4,dict(value='client')),(6,dict(ID=1,value='same',other=2))])
  t=table([(4,dict(value='client')),(6,dict(ID=1,value='release edit',other=1))])
  r=merge(a,b,t);self.assertIn('release edit',Book(r).cells('Main')['B6'].toxml());self.assertEqual(values(r)['C6'],'2')
 def test_actual_whitespace_in_keyless_text_still_blocks(self):
  a=table([(4,dict(value='client')),(6,dict(ID=1,value=1))])
  b=table([(4,dict(value=' client ')),(6,dict(ID=1,value=1))])
  with self.assertRaisesRegex(RuntimeError,'第 4 行缺少配置 ID'):merge(a,b,table([(6,dict(ID=1,value=9))]))

 def test_declaration_can_move_with_rows(self):
  import re
  def shift(data,offset):
   p=parts(data);p['xl/worksheets/sheet1.xml']=re.sub(rb'r="([A-Z]*)([0-9]+)"',lambda m:b'r="'+m[1]+str(int(m[2])+offset).encode()+b'"',p['xl/worksheets/sheet1.xml']);return pack(p)
  a=shift(table([(6,dict(ID=1,value=10))]),4);b=shift(table([(6,dict(ID=1,value=11))]),4)
  t=table([(12,dict(ID=1,value=20))]);self.assertEqual(values(merge(a,b,t))['B12'],'11')
 def test_scope_metadata_change_is_not_a_missing_record(self):
  a=table([(4,dict(value='client')),(6,dict(ID=1,value=10))]);b=table([(4,dict(value='server')),(6,dict(ID=1,value=11))]);t=table([(4,dict(value='client')),(9,dict(ID=1,value=10))])
  r=merge(a,b,t);self.assertIn('server',Book(r).cells('Main')['B4'].toxml());self.assertEqual(values(r)['B9'],'11')
 def test_numeric_storage_change_does_not_overwrite_release(self):
  a=table([(6,dict(ID=1,value=10,other=1))]);p=parts(a);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<v>10</v>',b'<v>1.0E1</v>');a=pack(p)
  b=table([(6,dict(ID=1,value=10,other=2))]);t=table([(6,dict(ID=1,value=99,other=1))])
  r=values(merge(a,b,t));self.assertEqual(r['B6'],'99');self.assertEqual(r['C6'],'2')
 def test_formula_cache_does_not_require_missing_key(self):
  def formula(data,cache):
   p=parts(data);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<sheetData>',f'<sheetData><row r="5"><c r="B5"><f>1+1</f><v>{cache}</v></c></row>'.encode());return pack(p)
  a=formula(table([(6,dict(ID=1,value=10))]),2);b=formula(table([(6,dict(ID=1,value=11))]),3);t=formula(table([(6,dict(ID=1,value=20))]),99)
  r=merge(a,b,t);self.assertEqual(values(r)['B6'],'11');self.assertIn('<v>99</v>',Book(r).cells('Main')['B5'].toxml())

 def test_scope_word_as_record_id_is_not_metadata(self):
  a=table([(4,dict(ID='client',value='server'))]);b=table([(4,dict(ID='client',value='changed'))]);t=table([(9,dict(ID='client',value='release'))])
  self.assertIn('changed',Book(merge(a,b,t)).cells('Main')['B9'].toxml())
 def test_long_numeric_id_is_not_rounded(self):
  number=123456789012345678901234567890123456789
  a=table([(6,dict(ID=number,value=1))]);b=table([(6,dict(ID=number,value=2))]);t=table([(9,dict(ID=number,value=3))])
  r=values(merge(a,b,t));self.assertEqual(r['A9'],str(number));self.assertEqual(r['B9'],'2')

 def test_trailing_formatted_empty_rows_do_not_move_new_records(self):
  a=table([(6,dict(ID=1,value=10))]);b=table([(6,dict(ID=1,value=10)),(7,dict(ID=2,value=20))]);p=parts(a)
  p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</sheetData>',b'<row r="1048576"><c r="B1048576" s="1"/></row></sheetData>')
  r=values(merge(a,b,pack(p)));self.assertEqual(r['A7'],'2')

 def test_unused_phonetic_font_id_is_not_text_change(self):
  a=table([(5,dict(value='refer=shop.ID')),(6,dict(ID=1,value=10))]);p=parts(a);p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</is>',b'<phoneticPr fontId="7" type="noConversion"/></is>');a=pack(p)
  b=table([(5,dict(value='refer=shop.ID')),(6,dict(ID=1,value=11))]);t=table([(5,dict(value='refer=shop.ID')),(9,dict(ID=1,value=10))])
  self.assertEqual(values(merge(a,b,t))['B9'],'11')
 def test_field_directives_are_metadata(self):
  a=table([(5,dict(value='refer=old.ID')),(6,dict(ID=1,value=10))]);b=table([(5,dict(value='refer=new.ID')),(6,dict(ID=1,value=10))]);t=table([(5,dict(value='refer=old.ID')),(9,dict(ID=1,value=99))])
  r=merge(a,b,t);self.assertIn('refer=new.ID',Book(r).cells('Main')['B5'].toxml());self.assertEqual(values(r)['B9'],'99')

class MissingAnnotationCopyTests(unittest.TestCase):
 def data(self, *, copied=None, value=10, identity=1):
  p=parts(table([(6,dict(ID=identity,value=value))]))
  note='<c r="E6" t="inlineStr"><is><t>existing note</t></is></c>'
  if copied is not None:note+=f'<c r="F6" t="inlineStr"><is><t>{copied}</t></is></c>'
  p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'</row></sheetData>',(note+'</row></sheetData>').encode())
  return pack(p)
 def test_missing_id_repeated_annotation_does_not_create_record(self):
  a=self.data();b=self.data(copied='existing note');t=self.data(identity=2,value=99)
  from file_sync import same_data
  self.assertTrue(same_data(merge(a,b,t),t,'config.xlsx'))
 def test_present_id_still_receives_annotation(self):
  result=Book(merge(self.data(),self.data(copied='existing note'),self.data(value=99)))
  from workbook_cells import config_cell_text
  self.assertEqual(config_cell_text(result.cells('Main')['F6']),'existing note')
  self.assertEqual(config_cell_text(result.cells('Main')['B6']),'99')
 def test_real_value_and_new_annotation_still_require_record(self):
  for after in (self.data(copied='different note'),self.data(copied='existing note',value=11)):
   with self.subTest(after=hash(after)),self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
    merge(self.data(),after,self.data(identity=2,value=99))
 def test_formula_with_same_cached_text_is_not_annotation_copy(self):
  p=parts(self.data(copied='existing note'))
  p['xl/worksheets/sheet1.xml']=p['xl/worksheets/sheet1.xml'].replace(b'<c r="F6" t="inlineStr"><is><t>existing note</t></is></c>',b'<c r="F6" t="str"><f>E6</f><v>existing note</v></c>')
  with self.assertRaisesRegex(RuntimeError,'缺少配置 ID'):
   merge(self.data(),pack(p),self.data(identity=2,value=99))
