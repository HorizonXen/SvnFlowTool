import Foundation
import Darwin

public struct WorkspaceEntry: Identifiable, Hashable, Codable, Sendable {
    public var id: String { path }
    public let path: String
    public let relative: String
    public let name: String
    public let isDirectory: Bool
    public let size: Int64
    public let modified: Date?
    public let state: ItemState
    public let revision: String?
    public let propertyState: String
}

public enum WorkspaceCatalog {
    /// Use one cheap lstat per entry instead of repeated URL resource lookups and path normalization.
    public static func build(root: String, status: [StatusItem], previous: [WorkspaceEntry] = []) -> [WorkspaceEntry] {
        let oldDirectories = Set(previous.filter(\.isDirectory).map(\.path))
        var items = Dictionary(status.map { ($0.path, $0) }, uniquingKeysWith: { _, b in b })
        var paths = Set(status.filter { $0.state != .ignored }.map(\.path))
        var inferred = Set<String>()
        for path in paths {
            var parent = (path as NSString).deletingLastPathComponent
            while parent.hasPrefix(root + "/") {
                if !inferred.insert(parent).inserted { break }
                parent = (parent as NSString).deletingLastPathComponent
            }
        }
        paths.formUnion(inferred)
        // Preserve unversioned top-level directories in the tree, as in the existing browser.
        for name in (try? FileManager.default.contentsOfDirectory(atPath: root)) ?? [] where !name.hasPrefix(".") {
            let path = root + "/" + name
            var info = stat()
            if lstat(path, &info) == 0 && (info.st_mode & S_IFMT) == S_IFDIR { paths.insert(path) }
        }
        if items[root]?.hasLocalChange != true { paths.remove(root); items.removeValue(forKey: root) }
        return paths.compactMap { path -> WorkspaceEntry? in
            guard path == root || path.hasPrefix(root + "/") else { return nil }
            let relative = path == root ? "" : String(path.dropFirst(root.count + 1))
            if relative.split(separator: "/").contains(".svn") { return nil }
            let item = items[path]
            var info = stat()
            let found = lstat(path, &info) == 0
            let directory = found ? (info.st_mode & S_IFMT) == S_IFDIR : (inferred.contains(path) || oldDirectories.contains(path))
            return WorkspaceEntry(path: path, relative: relative, name: (path as NSString).lastPathComponent, isDirectory: directory,
                                  size: found ? Int64(info.st_size) : 0,
                                  modified: found ? Date(timeIntervalSince1970: Double(info.st_mtimespec.tv_sec)) : nil,
                                  state: item?.state ?? .normal, revision: item?.revision, propertyState: item?.propertyState ?? "none")
        }.sorted { $0.relative < $1.relative }
    }
}
