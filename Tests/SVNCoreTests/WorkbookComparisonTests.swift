import Foundation
import SVNCore

enum WorkbookComparisonTests {
    static func run() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        func workbook(_ name: String, _ cells: String, sheet: String = "Data", worksheet: String? = nil) throws -> Data {
            let folder = root.appendingPathComponent(name)
            let files = [
                "xl/workbook.xml": "<workbook xmlns:r=\"urn:rels\"><sheets><sheet name=\"\(sheet)\" r:id=\"s1\"/></sheets></workbook>",
                "xl/_rels/workbook.xml.rels": "<Relationships><Relationship Id=\"s1\" Target=\"worksheets/sheet1.xml\"/></Relationships>",
                "xl/sharedStrings.xml": "<sst><si><r><t>Hello</t></r><r><t>世界</t></r></si></sst>",
                "xl/worksheets/sheet1.xml": worksheet ?? "<worksheet><sheetData><row>\(cells)</row></sheetData></worksheet>"
            ]
            for (path, text) in files {
                let url = folder.appendingPathComponent(path)
                try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                try Data(text.utf8).write(to: url)
            }
            let zip = root.appendingPathComponent(name + ".xlsx")
            _ = try CommandRunner().run(executable: URL(fileURLWithPath: "/usr/bin/zip"), arguments: ["-q", "-r", zip.path, "xl"], directory: folder).checked()
            return try Data(contentsOf: zip)
        }
        let a = try workbook("old", "<c r=\"A1\" t=\"s\"><v>0</v></c><c r=\"B2\"><v>10</v></c><c r=\"A10\"><f>B2*2</f><v>20</v></c><c r=\"C2\"><v>7</v></c>")
        let frozenOld = try workbook("formula-literal-old", """
            <c r="A1" t="str"><f>C63</f><v>蓝</v></c>
            <c r="A2"><f>7*3</f><v>21.0</v></c>
            <c r="A3"><f>7*3</f><v>21</v></c>
            <c r="A4" t="str"><f>C63</f><v>蓝 </v></c>
            <c r="A5"><f>7*3</f><v>21</v></c>
            <c r="A6"><f>7*3</f></c>
            <c r="A7"><v>21</v></c>
            <c r="A8"><f>7*3</f><v>21</v></c>
            <c r="A9"><f>7*3</f><v>21</v></c>
            <c r="A10"><f>7*3</f><v>21</v></c>
            <c r="A11" t="b"><f>1=1</f><v>1</v></c>
            """)
        let frozenNew = try workbook("formula-literal-new", """
            <c r="A1" t="inlineStr"><is><t>蓝</t></is></c>
            <c r="A2"><v>21</v></c>
            <c r="A3"><v>22</v></c>
            <c r="A4" t="inlineStr"><is><t>蓝</t></is></c>
            <c r="A5" t="inlineStr"><is><t>21</t></is></c>
            <c r="A7"><v>22</v></c>
            <c r="A8"><f>3*7</f><v>21</v></c>
            <c r="A9"><v>21oops</v></c>
            <c r="A10"><v>2.1E1</v></c>
            <c r="A11" t="b"><v>1</v></c>
            """)
        let conversions = try WorkbookComparison(old: frozenOld, new: frozenNew, label: "BASE").sheets[0].rows
        expectEqual(conversions.filter(\.isValuePreservingFormulaConversion).map(\.address), ["A1", "A2", "A10", "A11"])
        expectEqual(try WorkbookComparison(old: frozenNew, new: frozenOld, label: "BASE").sheets[0].rows.filter(\.isValuePreservingFormulaConversion).count, 0)
        let b = try workbook("new", "<c r=\"A1\" t=\"inlineStr\"><is><t>Hello世界</t></is></c><c r=\"B2\"><v>11</v></c><c r=\"A10\"><f>B2*3</f><v>33</v></c><c r=\"D2\"><v>8</v></c><c r=\"E2\" s=\"2\"/>")
        let diff = try WorkbookComparison(old: a, new: b, label: "BASE")
        let staged = try await RepositoryQuery().compareWorkbookFiles(ComparisonFiles(old: root.appendingPathComponent("old.xlsx").path, new: root.appendingPathComponent("new.xlsx").path, oldLabel: "Release SVN · r42", newLabel: "待合入"))
        expectEqual(staged.label, "Release SVN · r42")
        expectEqual(staged.sheets[0].changedCount, diff.sheets[0].changedCount)
        expectEqual(diff.sheets[0].changedCount, 4)
        expectEqual(diff.sheets[0].rows.map(\.address), ["A1", "B2", "C2", "D2", "A10"])
        expectEqual(diff.sheets[0].rows[0].changed, false)
        expectEqual(diff.sheets[0].rows.last?.new?.formula, "B2*3")
        expectEqual(diff.sheets[0].rows[0].changeExplanation, "当前单元格的值与公式无变化。")
        expectEqual(diff.sheets[0].rows[1].changeExplanation, "单元格值发生变化。")
        expectEqual(diff.sheets[0].rows[1].explanationTone, .red)
        expectEqual(diff.sheets[0].rows[2].explanationTone, .red)
        expectEqual(diff.sheets[0].rows.last?.explanationTone, .red)
        expectEqual(diff.sheets[0].rows[2].changeExplanation, "删除单元格：原版本的内容已清空。")
        expectEqual(diff.sheets[0].rows[3].changeExplanation, "新增单元格：原版本为空，当前版本有内容。")
        expectEqual(diff.sheets[0].rows.last?.changeExplanation, "公式发生变化；计算结果或缓存值发生变化。")
        expectEqual(try WorkbookComparison(old: a, new: a, label: "").sheets[0].changedCount, 0)
        let cachedA = try workbook("cache-a", "<c r=\"A1\"><f>B1*2</f><v>2</v></c>")
        let cachedB = try workbook("cache-b", "<c r=\"A1\" t=\"str\"><f>B1*2</f><v>99</v></c>")
        expectEqual(try WorkbookComparison(old: cachedA, new: cachedB, label: "").sheets[0].changedCount, 0)
        expectEqual(try WorkbookComparison(old: cachedA, new: cachedB, label: "").sheets[0].rows[0].changeExplanation, "公式未变化，仅缓存结果变化；按当前比较规则不计为差异。")
        let spaces = try workbook("spaces", "<c r=\"A1\" t=\"inlineStr\"><is><t> Hello世界 </t></is></c>")
        expectEqual(try WorkbookComparison(old: a, new: spaces, label: "").sheets[0].rows[0].changeExplanation, "值的首尾空白或换行发生变化。")
        expectEqual(try WorkbookComparison(old: a, new: spaces, label: "").sheets[0].rows[0].explanationTone, .green)
        let formulaValue = try workbook("formula-value", "<c r=\"A1\"><v>2</v></c>")
        expectEqual(try WorkbookComparison(old: cachedA, new: formulaValue, label: "").sheets[0].rows[0].explanationTone, .green)
        let typeValue = try workbook("type-value", "<c r=\"A1\" t=\"inlineStr\"><is><t>2</t></is></c>")
        expectEqual(try WorkbookComparison(old: formulaValue, new: typeValue, label: "").sheets[0].rows[0].explanationTone, .green)
        let renamed = try workbook("renamed", "", sheet: "New")
        let sheets = try WorkbookComparison(old: a, new: renamed, label: "").sheets
        expectEqual(sheets.map(\.name), ["Data", "New"])
        expectEqual(sheets[0].newExists, false)
        expectEqual(sheets[1].oldExists, false)
        expectEqual(try WorkbookComparison(old: Data(), new: a, label: "").sheets[0].changedCount, 4)
        expectThrows(try WorkbookComparison(old: Data("invalid zip".utf8), new: a, label: ""))
        let dataOnly = try workbook("extent-base", "", worksheet: "<worksheet><dimension ref=\"A1:XFD1048576\"/><sheetData><row r=\"2\"><c r=\"A2\"><v>1</v></c></row><row r=\"6\"><c r=\"A6\"><v>2</v></c></row></sheetData></worksheet>")
        let withTail = try workbook("extent-tail", "", worksheet: "<worksheet><dimension ref=\"A1:XFD1048576\"/><sheetData><row r=\"2\"><c r=\"A2\"><v>1</v></c></row><row r=\"6\"><c r=\"A6\"><v>2</v></c></row><row r=\"10\" ht=\"18\"><c r=\"C10\" s=\"2\"/></row><row r=\"12\"/></sheetData></worksheet>")
        let extent = try WorkbookComparison(old: dataOnly, new: withTail, label: "").sheets[0]
        expectEqual(extent.rowNumbers, Array(1...12))
        expectEqual(extent.oldLastRow, 6)
        expectEqual(extent.newLastRow, 12)
        expectEqual(extent.changedPhysicalRows, Array(7...12))
        expectEqual(extent.changedCount, 0) // Empty rows are not fabricated cell edits.
        expectEqual(extent.rows.map(\.address), ["A2", "A6"])
        let removedTail = try WorkbookComparison(old: withTail, new: dataOnly, label: "").sheets[0]
        expectEqual(removedTail.rowNumbers, Array(1...12))
        expectEqual(removedTail.changedPhysicalRows, Array(7...12))
        expectEqual(try WorkbookComparison(old: withTail, new: withTail, label: "").sheets[0].changedPhysicalRows, [])
        let empty = try workbook("extent-empty", "", worksheet: "<worksheet><dimension ref=\"A1:XFD1048576\"/><sheetData/></worksheet>")
        expectEqual(try WorkbookComparison(old: empty, new: empty, label: "").sheets[0].rowNumbers, [])
        let merged = try workbook("extent-merged", "", worksheet: "<worksheet><sheetData><row r=\"2\"><c r=\"A2\"><v>1</v></c></row></sheetData><mergeCells><mergeCell ref=\"A2:A15\"/></mergeCells></worksheet>")
        expectEqual(try WorkbookComparison(old: merged, new: merged, label: "").sheets[0].rowNumbers, Array(1...15))
        print("PASS: workbook values, formulas, shared/inline strings, ordering, blank styles, sheet add/remove and malformed archive")
    }
}
