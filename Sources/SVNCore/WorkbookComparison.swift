import Foundation

public struct WorkbookCell: Equatable, Decodable, Sendable {
    public let value: String
    public let formula: String
    public let type: String
    public let format: String?
    public init(value: String, formula: String, type: String, format: String? = nil) {
        self.value = value; self.formula = formula; self.type = type; self.format = format
    }
    public static func == (a: Self, b: Self) -> Bool {
        if !a.formula.isEmpty || !b.formula.isEmpty { return a.formula == b.formula }
        return a.value == b.value && a.type == b.type
    }
    public var display: String { formula.isEmpty ? value : "=" + formula + (value.isEmpty ? "" : "  → " + value) }
}
public struct WorkbookDifference: Identifiable, Sendable {
    public var id: String { address }
    public let address: String
    public let old: WorkbookCell?
    public let new: WorkbookCell?
    public var changed: Bool { old != new }
    /// A cached formula result was preserved as a literal, rather than removed.
    public var isValuePreservingFormulaConversion: Bool {
        guard let old, let new, !old.formula.isEmpty, new.formula.isEmpty,
              !old.value.isEmpty, !formatChanged else { return false }
        func valueKind(_ type: String) -> String {
            switch type {
            case "str", "text", "s", "inlineStr": return "text"
            case "", "n", "number": return "number"
            default: return type
            }
        }
        let kind = valueKind(old.type)
        guard kind == valueKind(new.type) else { return false }
        if old.value == new.value { return true }
        guard kind == "number" else { return false }
        // Validate the entire number: Decimal(string:) alone accepts prefixes.
        let pattern = #"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"#
        guard old.value.range(of: pattern, options: .regularExpression) != nil,
              new.value.range(of: pattern, options: .regularExpression) != nil,
              let a = Decimal(string: old.value, locale: Locale(identifier: "en_US_POSIX")),
              let b = Decimal(string: new.value, locale: Locale(identifier: "en_US_POSIX")),
              !a.isNaN, !b.isNaN else { return false }
        return a == b
    }
    public var formatChanged: Bool {
        guard let a = old?.format, let b = new?.format else { return false }
        return a != b
    }
    public enum ExplanationTone: Sendable { case neutral, red, green }
    public var explanationTone: ExplanationTone {
        guard let old, let new else { return old != nil ? .red : new != nil ? .green : .neutral }
        if !old.formula.isEmpty && new.formula.isEmpty { return .green }
        if old.formula != new.formula { return .red }
        if old.formula.isEmpty && old.value != new.value {
            return old.value.trimmingCharacters(in: .whitespacesAndNewlines) == new.value.trimmingCharacters(in: .whitespacesAndNewlines) ? .green : .red
        }
        if formatChanged || old.type != new.type { return .green }
        return changed ? .red : .neutral
    }
    public var changeExplanation: String {
        guard let old else { return new == nil ? "当前单元格为空，无值或公式变化。" : "新增单元格：原版本为空，当前版本有内容。" }
        guard let new else { return "删除单元格：原版本的内容已清空。" }
        guard changed else {
            if formatChanged { return "单元格格式发生变化，值与公式未变化。" }
            return old.formula == new.formula && !old.formula.isEmpty && old.value != new.value
                ? "公式未变化，仅缓存结果变化；按当前比较规则不计为差异。"
                : "当前单元格的值与公式无变化。"
        }
        var reasons: [String] = []
        if old.formula != new.formula {
            reasons.append(old.formula.isEmpty ? "普通值改为公式" : new.formula.isEmpty ? "公式改为普通值" : "公式发生变化")
        }
        if old.value != new.value {
            reasons.append(!old.formula.isEmpty || !new.formula.isEmpty ? "计算结果或缓存值发生变化" : old.value.trimmingCharacters(in: .whitespacesAndNewlines) == new.value.trimmingCharacters(in: .whitespacesAndNewlines) ? "值的首尾空白或换行发生变化" : "单元格值发生变化")
        }
        if old.type != new.type { reasons.append("数据类型发生变化（\(old.type) → \(new.type)）") }
        if formatChanged { reasons.append("单元格格式发生变化") }
        return reasons.joined(separator: "；") + "。"
    }
}
public struct WorkbookSheetComparison: Identifiable, Sendable {
    public var id: String { name }
    public let name: String
    public let oldExists: Bool
    public let newExists: Bool
    public let rows: [WorkbookDifference]
    public let changedCount: Int
    public let oldLastRow: Int
    public let newLastRow: Int
    public var rowNumbers: [Int] {
        let last = max(oldLastRow, newLastRow)
        return last > 0 ? Array(1...last) : []
    }
    /// Added/removed physical rows are navigable without inventing changed cells.
    public var changedPhysicalRows: [Int] {
        let first = min(oldLastRow, newLastRow) + 1, last = max(oldLastRow, newLastRow)
        return first <= last ? Array(first...last) : []
    }
}
public struct WorkbookReason: Decodable, Identifiable, Sendable {
    public var id: String { location + kind + old + new }
    public let location: String
    public let old: String
    public let new: String
    public let kind: String
}
public struct WorkbookComparison: Sendable {
    public let label: String
    public let reasons: [WorkbookReason]
    public let inspectionError: String?
    public let bytesEqual: Bool
    public let sheets: [WorkbookSheetComparison]
    public init(old: Data, new: Data, label: String) throws {
        self.label = label
        self.bytesEqual = old == new
        var inspected: [WorkbookReason] = []
        var inspectionFailure: String?
        if old != new {
            do {
                guard let resource = Bundle.main.resourceURL else { throw WorkbookReader.failure("缺少比较组件") }
                let script = resource.appendingPathComponent("workbook_inspect.py")
                let python = resource.appendingPathComponent("python/bin/python3.12")
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                defer { try? FileManager.default.removeItem(at: folder) }
                let a = folder.appendingPathComponent("before.xlsx"), b = folder.appendingPathComponent("after.xlsx")
                try old.write(to: a); try new.write(to: b)
                let result = try CommandRunner().run(executable: python, arguments: [script.path, a.path, b.path]).checked()
                inspected = try JSONDecoder().decode([WorkbookReason].self, from: result.standardOutput)
            } catch { inspectionFailure = "内部结构未完成分析：" + error.localizedDescription }
        }
        self.reasons = inspected; self.inspectionError = inspectionFailure
        let left = try WorkbookReader.read(old), right = try WorkbookReader.read(new)
        var names = left.map(\.name)
        for sheet in right where !names.contains(sheet.name) { names.append(sheet.name) }
        sheets = names.map { name in
            let a = left.first { $0.name == name }, b = right.first { $0.name == name }
            let keys = Set(a?.cells.keys.map { $0 } ?? []).union(b?.cells.keys.map { $0 } ?? [])
            let rows = keys.sorted { addressOrder($0) < addressOrder($1) }.map { WorkbookDifference(address: $0, old: a?.cells[$0], new: b?.cells[$0]) }
            return WorkbookSheetComparison(name: name, oldExists: a != nil, newExists: b != nil, rows: rows, changedCount: rows.filter(\.changed).count, oldLastRow: a?.storedLastRow ?? 0, newLastRow: b?.storedLastRow ?? 0)
        }
    }
}
private func addressOrder(_ address: String) -> Int {
    var column = 0, row = 0
    for byte in address.utf8 {
        if byte >= 65 && byte <= 90 { column = column * 26 + Int(byte - 64) }
        else if byte >= 48 && byte <= 57 { row = row * 10 + Int(byte - 48) }
    }
    return row * 16385 + column
}
private struct ParsedSheet: Decodable {
    let name: String
    let cells: [String: WorkbookCell]
    let lastRow: Int?
    var storedLastRow: Int {
        max(lastRow ?? 0, cells.keys.compactMap { Int($0.filter(\.isNumber)) }.max() ?? 0)
    }
}
private enum WorkbookReader {
    static func read(_ data: Data) throws -> [ParsedSheet] {
        if data.isEmpty { return [] }
        guard data.count <= 100 * 1024 * 1024 else { throw failure("工作簿超过 100 MB，暂不支持内置比较。") }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("svnflow-" + UUID().uuidString + ".xlsx")
        try data.write(to: file, options: .atomic)
        defer { try? FileManager.default.removeItem(at: file) }
        if let resources = Bundle.main.resourceURL {
            let script = resources.appendingPathComponent("workbook_inspect.py")
            let python = resources.appendingPathComponent("python/bin/python3.12")
            if FileManager.default.fileExists(atPath: script.path) && FileManager.default.isExecutableFile(atPath: python.path) {
                let result = try CommandRunner().run(executable: python, arguments: [script.path, "--cells", file.path]).checked()
                return try JSONDecoder().decode([ParsedSheet].self, from: result.standardOutput)
            }
        }
        let listing = try CommandRunner().run(executable: URL(fileURLWithPath: "/usr/bin/unzip"), arguments: ["-Z1", file.path]).checked().outputText
        let members = Set(listing.components(separatedBy: "\n"))
        func parse(_ member: String) throws -> WorkbookXML {
            guard members.contains(member), !member.contains(".."), !member.hasPrefix("/") else { throw failure("Excel 工作簿结构无效：" + member) }
            let bytes = try CommandRunner().run(executable: URL(fileURLWithPath: "/usr/bin/unzip"), arguments: ["-p", file.path, member]).checked().standardOutput
            guard bytes.count <= 256 * 1024 * 1024 else { throw failure("工作表 XML 超过 256 MB，暂不支持内置比较。") }
            let handler = WorkbookXML()
            let parser = XMLParser(data: bytes); parser.shouldResolveExternalEntities = false; parser.delegate = handler
            guard parser.parse(), !handler.exceeded else { throw failure("无法解析 Excel 工作表，或单表超过 2,000,000 个非空单元格。") }
            return handler
        }
        let workbook = try parse("xl/workbook.xml")
        let relationships = try parse("xl/_rels/workbook.xml.rels")
        let shared = members.contains("xl/sharedStrings.xml") ? try parse("xl/sharedStrings.xml").strings : []
        return try workbook.sheets.map { name, id in
            guard let target = relationships.relationships[id] else { throw failure("无法找到工作表：" + name) }
            let member = target.hasPrefix("/xl/") ? String(target.dropFirst()) : "xl/" + target
            let xml = try parse(member)
            var cells: [String: WorkbookCell] = [:]
            for (address, cell) in xml.cells {
                let value: String
                if cell.type == "s" {
                    guard let index = Int(cell.value), shared.indices.contains(index) else { throw failure("工作表共享字符串索引无效。") }
                    value = shared[index]
                } else { value = cell.value }
                if !value.isEmpty || !cell.formula.isEmpty { cells[address] = WorkbookCell(value: value, formula: cell.formula, type: cell.type == "s" || cell.type == "inlineStr" ? "text" : cell.type) }
            }
            return ParsedSheet(name: name, cells: cells, lastRow: xml.lastRow)
        }
    }
    static func failure(_ text: String) -> NSError { NSError(domain: "Excel Compare", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
}
private final class WorkbookXML: NSObject, XMLParserDelegate {
    var sheets: [(String, String)] = []
    var relationships: [String: String] = [:]
    var strings: [String] = []
    var cells: [String: WorkbookCell] = [:]
    var exceeded = false
    var lastRow = 0
    private var implicitRow = 0
    private var stack: [String] = []
    private var text = "", address = "", type = "", value = "", formula = "", rich = ""
    func parser(_ p: XMLParser, didStartElement e: String, namespaceURI: String?, qualifiedName: String?, attributes a: [String: String]) {
        stack.append(e); text = ""
        func retainRow(_ value: String?) {
            guard let value, let row = Int(value.filter(\.isNumber)), row > 0, row <= 1_048_576 else { return }
            lastRow = max(lastRow, row)
        }
        if e == "row" {
            implicitRow = Int(a["r"] ?? "") ?? (implicitRow + 1)
            retainRow(String(implicitRow))
        }
        if e == "c" { retainRow(a["r"]) }
        if e == "mergeCell" {
            for address in (a["ref"] ?? "").split(separator: ":") { retainRow(String(address)) }
        }
        // dimension is cached metadata; it must not inflate the displayed rows.
        if e == "sheet", let name = a["name"], let id = a["r:id"] { sheets.append((name, id)) }
        if e == "Relationship", a["TargetMode"] != "External", let id = a["Id"], let target = a["Target"] { relationships[id] = target }
        if e == "si" { rich = "" }
        if e == "c" { address = a["r"] ?? ""; type = a["t"] ?? "n"; value = ""; formula = ""; rich = "" }
        if e == "f", a["t"] == "shared" { formula = "[shared:" + (a["si"] ?? "") + "] " }
    }
    func parser(_ p: XMLParser, foundCharacters s: String) { text += s }
    func parser(_ p: XMLParser, didEndElement e: String, namespaceURI: String?, qualifiedName: String?) {
        if e == "v" { value = text }
        if e == "f" { formula += text }
        if e == "t" && !stack.contains("rPh") { rich += text }
        if e == "si" { strings.append(rich) }
        if e == "c", !address.isEmpty {
            let content = type == "inlineStr" ? rich : value
            // Formatting-only cells can span an entire sheet. They do not belong
            // in the value/formula grid; structural inspection reports formatting.
            if !content.isEmpty || !formula.isEmpty {
                cells[address] = WorkbookCell(value: content, formula: formula, type: type)
                if cells.count > 2_000_000 { exceeded = true; p.abortParsing() }
            }
        }
        stack.removeLast(); text = ""
    }
}
