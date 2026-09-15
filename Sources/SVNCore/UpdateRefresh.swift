import Foundation

public enum UpdateRefresh {
    public static func contains(_ path: String, in root: String) -> Bool { path == root || path.hasPrefix(root + "/") }
    public static func target(root: String, directory: String) -> String {
        let path = (root + "/" + directory as NSString).standardizingPath
        return contains(path, in: root) ? path : root
    }
    public static func merge(root: String, previous: [StatusItem], entries: [WorkspaceEntry], refreshed: [StatusItem], queried: Set<String>, deleted: Set<String>) -> ([StatusItem], [WorkspaceEntry]) {
        let deletedDirectories = Set(entries.filter { $0.isDirectory && deleted.contains($0.path) }.map(\.path))
        func removed(_ path: String) -> Bool {
            if deleted.contains(path) { return true }
            guard !deletedDirectories.isEmpty else { return false }
            var parent = (path as NSString).deletingLastPathComponent
            while contains(parent, in: root) {
                if deletedDirectories.contains(parent) { return true }
                if parent == root { break }
                parent = (parent as NSString).deletingLastPathComponent
            }
            return false
        }
        var statuses = Dictionary(previous.filter { !queried.contains($0.path) && !removed($0.path) }.map { ($0.path, $0) }, uniquingKeysWith: { _, b in b })
        for item in refreshed { statuses[item.path] = item }
        var catalog = Dictionary(entries.filter { !removed($0.path) && !queried.contains($0.path) }.map { ($0.path, $0) }, uniquingKeysWith: { _, b in b })
        for entry in WorkspaceCatalog.build(root: root, status: refreshed, previous: entries) {
            if queried.contains(entry.path) || catalog[entry.path] == nil { catalog[entry.path] = entry }
        }
        return (Array(statuses.values), catalog.values.sorted { $0.relative < $1.relative })
    }
}
