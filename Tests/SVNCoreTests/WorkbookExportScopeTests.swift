import Foundation
import SVNCore

enum WorkbookExportScopeTests {
    static func run() throws {
        let fm = FileManager.default
        let base = fm.temporaryDirectory.appendingPathComponent("export-scope-" + UUID().uuidString)
        let root = base.appendingPathComponent("Release")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: base) }
        let a = root.appendingPathComponent("a.xlsx").path
        let b = root.appendingPathComponent("b.XLSX").path
        try Data().write(to: URL(fileURLWithPath: a))
        try Data().write(to: URL(fileURLWithPath: b))
        try Data().write(to: base.appendingPathComponent("outside.xlsx"))
        let accepted: Set<String> = ["a.xlsx", "b.XLSX"]
        func scope(_ selection: Set<String>, copy: String? = nil) throws -> Set<String> {
            try WorkbookExportScope.paths(selection: selection, workingCopy: copy ?? root.path,
                                          target: root.path, accepted: accepted)
        }
        expectEqual(try scope([a, b, root.appendingPathComponent("data.lua").path]), accepted)
        expectEqual(try WorkbookExportScope.paths(selection: [a, b], workingCopy: root.path,
                                                    target: root.path), accepted)
        let dev = base.appendingPathComponent("Dev")
        try fm.createDirectory(at: dev, withIntermediateDirectories: true)
        let devFile = dev.appendingPathComponent("a.xlsx")
        try Data().write(to: devFile)
        expectEqual(try WorkbookExportScope.paths(selection: [devFile.path], workingCopy: dev.path,
                                                  target: dev.path), ["a.xlsx"])
        expectThrows(try WorkbookExportScope.paths(selection: [devFile.path, a], workingCopy: dev.path,
                                                   target: dev.path))
        expectThrows(try WorkbookExportScope.paths(selection: [root.appendingPathComponent("missing.xlsx").path],
                                                    workingCopy: root.path, target: root.path))
        expectThrows(try scope([]))
        expectThrows(try scope([a], copy: base.appendingPathComponent("Dev").path))
        expectThrows(try scope([a, root.appendingPathComponent("unconfirmed.xlsx").path]))
        expectThrows(try scope([base.appendingPathComponent("ReleaseOther/a.xlsx").path]))
        let alias = base.appendingPathComponent("Alias")
        try fm.createSymbolicLink(at: alias, withDestinationURL: root)
        expectEqual(try scope([alias.appendingPathComponent("a.xlsx").path], copy: alias.path), ["a.xlsx"])
        try fm.createSymbolicLink(at: root.appendingPathComponent("outside.xlsx"), withDestinationURL: base.appendingPathComponent("outside.xlsx"))
        expectThrows(try scope([root.appendingPathComponent("outside.xlsx").path]))
        expectEqual(WorkbookExportScope.supports("legacy.xls"), false)
        expectEqual(WorkbookExportScope.supports("macro.xlsm"), false)
        print("PASS: export selection, exact Release identity, all-or-nothing ledger scope and symlink boundaries")
    }
}
