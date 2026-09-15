import unittest,tempfile,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from workbook_inspect import inspect
from test_workbook import book,parts,pack
class InspectTests(unittest.TestCase):
 def compare(self,a,b):
  with tempfile.TemporaryDirectory() as d:
   x,y=pathlib.Path(d)/'a.xlsx',pathlib.Path(d)/'b.xlsx';x.write_bytes(a);y.write_bytes(b);return inspect(x,y)
 def test_identical(self):self.assertEqual(self.compare(book(),book()),[])
 def test_removed_sheet(self):self.assertTrue(any(r['kind']=='工作表' and r['new']=='不存在' for r in self.compare(book(extra=True),book(extra=False))))
 def test_calculation_setting_not_storage(self):
  a=book();p=parts(a);p['xl/workbook.xml']=p['xl/workbook.xml'].replace(b'</workbook>',b'<calcPr fullCalcOnLoad="1"/></workbook>')
  self.assertTrue(any(r['kind']=='计算或工作簿设置' for r in self.compare(a,pack(p))))
 def test_serialization_only(self):
  a=book();p=parts(a);p['xl/workbook.xml']=p['xl/workbook.xml'].replace(b'><',b'>\n<')
  self.assertEqual(self.compare(a,pack(p))[0]['kind'],'存储结构')
if __name__=='__main__':unittest.main()

class SemanticReaderTests(unittest.TestCase):
 def test_shared_formula_and_numeric_storage_use_merge_reader(self):
  from test_author_isolation import fixture
  from workbook_inspect import semantic_cells
  from test_workbook import NS
  p=parts(fixture());p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f t="shared" si="0" ref="A1:A2">B1+1</f><v>2</v></c><c r="B1" t="n"><v>1.00E1</v></c></row><row r="2"><c r="A2"><f t="shared" si="0"/><v>3</v></c></row></sheetData></worksheet>').encode()
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'a.xlsx';path.write_bytes(pack(p));rows=semantic_cells(path)[0]['cells']
  self.assertEqual(rows['A2']['formula'],'B2+1');self.assertEqual(rows['A1']['formula'],'B1+1');self.assertEqual(rows['B1']['value'],'10')

class StoredRowExtentTests(unittest.TestCase):
 def test_rows_and_formatted_tail_survive_without_fake_cells(self):
  from test_author_isolation import fixture
  from test_workbook import NS
  from workbook_inspect import semantic_cells
  p=parts(fixture());p['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{NS}"><dimension ref="A1:XFD1048576"/><sheetData><row r="2"><c r="A2"><v>1</v></c></row><row r="6"><c r="A6"><v>2</v></c></row><row r="10"><c r="C10" s="0"/></row><row r="12"><c r="A12" t="inlineStr"/></row></sheetData></worksheet>').encode()
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'a.xlsx';path.write_bytes(pack(p));sheet=semantic_cells(path)[0]
  self.assertEqual(sheet['lastRow'],12)
  self.assertEqual(set(sheet['cells']),{'A2','A6'})
 def test_stale_dimension_and_validation_do_not_create_rows(self):
  from workbook_inspect import stored_last_row
  from test_workbook import NS
  self.assertEqual(stored_last_row(f'<worksheet xmlns="{NS}"><dimension ref="A1:XFD1048576"/><sheetData/><dataValidations><dataValidation sqref="A1:A1048576"/></dataValidations></worksheet>'),0)
 def test_merged_layout_and_implicit_rows(self):
  from workbook_inspect import stored_last_row
  from test_workbook import NS
  self.assertEqual(stored_last_row(f'<worksheet xmlns="{NS}"><sheetData><row/><row/></sheetData></worksheet>'),2)
  self.assertEqual(stored_last_row(f'<worksheet xmlns="{NS}"><sheetData/><mergeCells><mergeCell ref="A3:A15"/></mergeCells></worksheet>'),15)
