import unittest
from test_config_identity import table,values
from test_formula_freeze import formula
from test_workbook import parts,pack
from workbook_cells import patch


def scratch(data,value=None):
    if value is None:return data
    data=parts(data)
    data['xl/worksheets/sheet1.xml']=data['xl/worksheets/sheet1.xml'].replace(b'<row r="9">',f'<row r="9"><c r="E9"><v>{value}</v></c>'.encode())
    return pack(data)


class MissingRecordAuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.base=table([(9,dict(ID=1,value=10,other=20))])
        self.target=table([(9,dict(ID=2,value=99,other=88))])

    def test_freeze_and_remove_undeclared_scratch_does_not_create_record(self):
        before=formula(scratch(self.base,30),'B9','1+9')
        before=formula(before,'E9','10+20')
        out,_=patch(before,self.base,self.target,prefer_source=True)
        self.assertEqual(values(out),values(self.target))

    def test_business_value_change_still_blocks(self):
        before=formula(scratch(self.base,30),'B9','1+9')
        after=table([(9,dict(ID=1,value=11,other=20))])
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):patch(before,after,self.target,prefer_source=True)

    def test_declared_field_deletion_still_blocks(self):
        after=table([(9,dict(ID=1,value=10))])
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):patch(scratch(self.base,30),after,self.target,prefer_source=True)

    def test_auxiliary_addition_or_changed_value_still_blocks(self):
        for before,after in [(self.base,scratch(self.base,30)),(scratch(self.base,30),scratch(self.base,31))]:
            with self.subTest(after=after[-12:]),self.assertRaisesRegex(ValueError,'缺少配置 ID'):
                patch(before,after,self.target,prefer_source=True)

    def test_declared_header_change_still_blocks(self):
        after=table([(9,dict(ID=1,value=10,other=20))],fields=('ID','value','other','new'))
        with self.assertRaisesRegex(ValueError,'缺少配置 ID'):patch(scratch(self.base,30),after,self.target,prefer_source=True)

    def test_existing_record_still_receives_auxiliary_clear(self):
        before=scratch(self.base,30)
        out,_=patch(before,self.base,before,prefer_source=True)
        self.assertEqual(values(out),values(self.base))

if __name__=='__main__':unittest.main()
