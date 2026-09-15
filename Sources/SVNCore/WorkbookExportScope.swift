import Foundation

/// Converts workspace selection into the export target's relative paths.
public enum WorkbookExportScope {
    public static func supports(_ path: String) -> Bool {
        (path as NSString).pathExtension.lowercased() == "xlsx"
    }

    public static func paths(selection: Set<String>, workingCopy: String, target: String,
                             accepted: Set<String>? = nil) throws -> Set<String> {
        func resolved(_ path: String) -> String {
            URL(fileURLWithPath: path).standardizedFileURL.resolvingSymlinksInPath().path
        }
        func fail(_ text: String) -> NSError {
            NSError(domain: "WorkbookExportScope", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
        }
        guard !workingCopy.isEmpty, !target.isEmpty, resolved(workingCopy) == resolved(target) else {
            throw fail("请在当前导出目标对应的工作副本选择 Excel 后导出。")
        }
        let root = resolved(target)
        let prefix = root == "/" ? root : root + "/"
        let workbooks = selection.filter(supports)
        guard !workbooks.isEmpty else { throw fail("请选择 .xlsx 格式的 Excel 配置。") }
        var paths = Set<String>()
        for file in workbooks.sorted() {
            let absolute = resolved(file)
            guard absolute.hasPrefix(prefix) else { throw fail("所选 Excel 不在当前工作副本内：\(file)") }
            let relative = String(absolute.dropFirst(prefix.count))
            if let accepted, !accepted.contains(relative) {
                throw fail("所选 Excel 尚无可导出的确认合入记录，请先确认合入：\(relative)")
            }
            guard FileManager.default.isReadableFile(atPath: absolute),
                  (try? URL(fileURLWithPath: absolute).resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true else {
                throw fail("所选 Excel 不存在或无法读取：\(relative)")
            }
            paths.insert(relative)
        }
        return paths
    }
}
