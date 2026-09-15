import Foundation
import SVNCore
struct WorkingCopy { let path: String }
struct LocalEntry: Identifiable, Hashable, Sendable {
    var id: String { path }
    let path: String
    let relative: String
    let name: String
    let isDirectory: Bool
    let size: Int64
    let modified: Date?
    let state: ItemState
    let revision: String?
    let propertyState: String
}

enum Baseline {
    static func buildLocalEntries(_ c: WorkingCopy, entries: [StatusItem], previousDirectories: Set<String>) -> [LocalEntry] {
        let fm = FileManager.default
        let keys: Set<URLResourceKey> = [.isDirectoryKey, .fileSizeKey, .contentModificationDateKey, .isHiddenKey]
        let statusByPath = Dictionary(entries.map { ($0.path, $0) }, uniquingKeysWith: { _, latest in latest })
        let root = URL(fileURLWithPath: c.path)
        let topLevel = (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: Array(keys), options: [.skipsHiddenFiles])) ?? []
        let changedURLs = entries.filter { !$0.relative.isEmpty && $0.state != .ignored }.map { URL(fileURLWithPath: $0.path) }
        var directoryPaths = Set<String>()
        for url in changedURLs {
            var parent = (url.path as NSString).deletingLastPathComponent
            while parent.hasPrefix(c.path + "/") {
                guard directoryPaths.insert(parent).inserted else { break }
                parent = (parent as NSString).deletingLastPathComponent
            }
        }
        let changedDirectories = directoryPaths.map { URL(fileURLWithPath: $0) }
        let inferredDirectories = Set(changedDirectories.map(\.path)).union(previousDirectories)
        return (topLevel.filter { (try? $0.resourceValues(forKeys: keys).isDirectory) == true } + changedDirectories + changedURLs + (statusByPath[root.path]?.hasLocalChange == true ? [root] : [])).uniqued(by: \.path).compactMap { url in
            guard !url.pathComponents.contains(".svn") else { return nil }
            let v = try? url.resourceValues(forKeys: keys)
            let item = statusByPath[url.standardizedFileURL.path]
            let relative = url.path == root.path ? "" : String(url.path.dropFirst(c.path.count + 1))
            return LocalEntry(path: url.path, relative: relative, name: url.lastPathComponent,
                isDirectory: v?.isDirectory ?? inferredDirectories.contains(url.path),
                size: Int64(v?.fileSize ?? 0), modified: v?.contentModificationDate,
                state: item?.state ?? .normal, revision: item?.revision, propertyState: item?.propertyState ?? "none")
        }.sorted { ($0.relative.localizedStandardCompare($1.relative)) == .orderedAscending }
    }
}
extension Array {
    func uniqued<Key: Hashable>(by key: (Element) -> Key) -> [Element] {
        var seen = Set<Key>(); return filter { seen.insert(key($0)).inserted }
    }
}
if CommandLine.arguments[1] == "--text" {
    let start = Date()
    let comparison = try await RepositoryQuery().compareFile(CommandLine.arguments[2])
    let compared = Date()
    let expanded = comparison.expandingLua(true)
    let finished = Date()
    print("rows=\(comparison.rows.count) changes=\(comparison.changeStarts.count) expandedRows=\(expanded.rows.count) compare=\(compared.timeIntervalSince(start)) expand=\(finished.timeIntervalSince(compared)) total=\(finished.timeIntervalSince(start))")
    exit(0)
}
if CommandLine.arguments[1] == "--workbook" {
    let start = Date()
    let comparison = try await RepositoryQuery().compareWorkbook(CommandLine.arguments[2])
    print("sheets=\(comparison.sheets.count) changedCells=\(comparison.sheets.reduce(0) { $0 + $1.changedCount }) seconds=\(Date().timeIntervalSince(start))")
    exit(0)
}
let root = CommandLine.arguments[1]
let start = Date()
let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/opt/homebrew/bin/svn"), arguments: ["status", "--xml", "--verbose", "--no-ignore", "--", root + "@"]).checked()
let scanned = Date()
let status = try WorkingCopyStatus.parse(result.standardOutput, root: root)
let parsed = Date()
let entries = WorkspaceCatalog.build(root: root, status: status)
let built = Date()
print("entries=\(entries.count) svn=\(scanned.timeIntervalSince(start)) parse=\(parsed.timeIntervalSince(scanned)) build=\(built.timeIntervalSince(parsed)) total=\(built.timeIntervalSince(start))")

if CommandLine.arguments.contains("--update-refresh") {
    let begin = Date()
    let targets = Set(status.filter(\.hasLocalChange).map(\.path)).union([root])
    var fresh: [StatusItem] = []
    let paths = targets.sorted()
    for offset in stride(from: 0, to: paths.count, by: 100) {
        let args = paths[offset..<min(offset + 100, paths.count)].map { $0 + "@" }
        let data = try CommandRunner().run(executable: URL(fileURLWithPath: "/opt/homebrew/bin/svn"), arguments: ["status", "--xml", "--verbose", "--no-ignore", "--ignore-externals", "--depth", "empty", "--"] + args).checked().standardOutput
        fresh += try WorkingCopyStatus.parse(data, root: root)
    }
    let read = Date()
    let patch = UpdateRefresh.merge(root: root, previous: status, entries: entries, refreshed: fresh, queried: targets, deleted: [])
    let index = WorkspaceListingIndex(patch.1)
    print("local_refresh_status=\(read.timeIntervalSince(begin)) merge_index=\(Date().timeIntervalSince(read)) foreground_refresh_total=\(Date().timeIntervalSince(begin)) queried=\(targets.count) changes=\(index.list(directory: "", recursive: true, unchanged: false, unversioned: true, filter: "").shown.count)")
    exit(0)
}

let again = Date()
let repeated = WorkspaceCatalog.build(root: root, status: status, previous: entries)
print("repeat_build=\(Date().timeIntervalSince(again)) entries=\(repeated.count)")

let indexed = Date()
let index = WorkspaceListingIndex(entries)
print("index=\(Date().timeIntervalSince(indexed))")
let queryStart = Date()
var matches = 0
for _ in 0..<1000 {
    matches += index.list(directory: "Assets", recursive: true, unchanged: false, unversioned: true, filter: "").shown.count
}
print("1000_change_queries=\(Date().timeIntervalSince(queryStart)) matches=\(matches)")
if CommandLine.arguments.contains("--compare") {
    let oldStart = Date()
    let old = Baseline.buildLocalEntries(WorkingCopy(path: root), entries: status, previousDirectories: [])
    print("same_payload_old_build=\(Date().timeIntervalSince(oldStart))")
    let oldValues = Dictionary(old.map { ($0.path, "\($0.isDirectory):\($0.state):\($0.revision ?? "")") }, uniquingKeysWith: { _, b in b })
    let newValues = Dictionary(entries.map { ($0.path, "\($0.isDirectory):\($0.state):\($0.revision ?? "")") }, uniquingKeysWith: { _, b in b })
    print("catalog_equivalent=\(oldValues == newValues)")
}
