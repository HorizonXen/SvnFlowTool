"""Save-only equivalence must accept serialization churn, not edit corruption."""
import io
import pathlib
import sys
import unittest
import zipfile
from lxml import etree as E
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
import workbook_native as native
from workbook_cells import Book, sig
from workbook_dom import parseString
from test_config_identity import table


def xml(text):
    return sig(native.children(parseString('<root xmlns="'+native.M+'">'+text+'</root>').documentElement)[0])


def workbook(font='<name val="Arial"/><sz val="11"/><charset val="134"/>',
             tint='0.398815881832331', xf='applyFont="1"', base_font=None, rich=None):
    parts = Book(table([(6, dict(ID=1, value=10))])).parts.copy()
    fonts = '<font>'+font+'</font>'
    if base_font is not None: fonts += '<font>'+base_font+'</font>'
    parts['xl/styles.xml'] = (f'<styleSheet xmlns="{native.M}"><fonts>{fonts}</fonts>'
        f'<fills><fill><patternFill patternType="solid"><fgColor theme="8" tint="{tint}"/>'
        '</patternFill></fill></fills><borders><border/></borders>'
        f'<cellStyleXfs><xf fontId="{int(base_font is not None)}"/></cellStyleXfs>'
        f'<cellXfs><xf fontId="0" xfId="0" {xf}/></cellXfs></styleSheet>').encode()
    if rich is not None:
        root = E.fromstring(parts['xl/worksheets/sheet1.xml'])
        cell = root.find('.//{'+native.M+'}c[@r="B6"]')
        for child in list(cell): cell.remove(child)
        cell.set('t', 'inlineStr')
        cell.append(E.fromstring(f'<is xmlns="{native.M}">{rich}</is>'))
        parts['xl/worksheets/sheet1.xml'] = E.tostring(root)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, data in parts.items(): z.writestr(name, data)
    return out.getvalue()


class NativeSaveStylesTests(unittest.TestCase):
    def test_excel_font_metadata_and_tint_roundtrip(self):
        a = workbook()
        b = workbook(font='<name val="Arial"/><sz val="11"/><family val="2"/>',
                     tint='0.3987853633228553')
        self.assertNotEqual(Book(a).style('0'), Book(b).style('0'))
        native.verify(a, b, {})

    def test_actual_font_size_color_and_flags_block(self):
        a = workbook()
        cases = [workbook(font=f) for f in (
            '<name val="Calibri"/><sz val="11"/><charset val="134"/>',
            '<name val="Arial"/><sz val="12"/><charset val="134"/>',
            '<name val="Arial"/><sz val="11"/><charset val="2"/>')]
        cases += [workbook(tint='0.4'), workbook(xf='applyFont="0"'),
                  workbook(xf='applyFont="1" applyNumberFormat="1"')]
        for b in cases:
            with self.subTest(case=cases.index(b)), self.assertRaisesRegex(ValueError, '样式变化'):
                native.verify(a, b, {})

    def test_font_metadata_rules_are_directional_and_preserve_explicit_values(self):
        def font(body): return xml('<font>'+body+'</font>')
        name = '<name val="Arial"/>'
        cases = [(name+'<family val="2"/>', name+'<family val="3"/>'),
                 (name+'<charset val="2"/>', name),
                 (name+'<family val="2"/>', name),
                 ('<charset val="134"/>', ''),
                 (name, name+'<family val="99"/>')]
        for a, b in cases:
            with self.subTest(a=a,b=b): self.assertFalse(native.saved_xml_equal(font(a), font(b)))

    def test_tint_accepts_only_decimal_reserialization_or_exact_truncation(self):
        for a,b in [('0.599993896298105','0.59999389629810485'),
                    ('-0.0499893185216834','-4.9989318521683403E-2'),
                    ('0.799371318704794','0.7993408001953185')]:
            self.assertTrue(native.saved_xml_equal(xml(f'<fgColor theme="8" tint="{a}"/>'),
                                                   xml(f'<fgColor theme="8" tint="{b}"/>')))
        for color in ['theme="9" tint="0.3987853633228553"',
                      'theme="8" tint="0.39880"', 'theme="8" tint="nan"',
                      'rgb="FF00FF00" tint="0.3987853633228553"']:
            self.assertFalse(native.saved_xml_equal(xml('<fgColor theme="8" tint="0.398815881832331"/>'),
                                                    xml('<fgColor '+color+'/>')))

    def test_redundant_applyfont_only_when_both_fonts_equal_base(self):
        native.verify(workbook(), workbook(xf=''), {})
        base = '<name val="Calibri"/><sz val="11"/>'
        with self.assertRaisesRegex(ValueError, '样式变化'):
            native.verify(workbook(base_font=base), workbook(base_font=base, xf=''), {})

    def test_rich_text_metadata_preserves_text_runs_and_actual_formatting(self):
        a = '<r><rPr><rFont val="Arial"/><sz val="10"/><charset val="134"/></rPr><t>说明</t></r>'
        b = '<r><rPr><rFont val="Arial"/><sz val="10"/><family val="2"/></rPr><t>说明</t></r>'
        native.verify(workbook(rich=a), workbook(rich=b), {})
        for changed in [b.replace('说明','新说明'), b.replace('Arial','Calibri'),
                        b.replace('val="10"','val="12"'), b+b]:
            with self.assertRaisesRegex(ValueError, '数据或公式变化'):
                native.verify(workbook(rich=a), workbook(rich=changed), {})

    def test_source_comparison_stays_exact(self):
        a,b = workbook(),workbook(tint='0.3987853633228553')
        self.assertNotEqual(Book(a).cell_value(Book(a).cells('Main')['B6']),
                            Book(b).cell_value(Book(b).cells('Main')['B6']))

if __name__ == '__main__': unittest.main()
