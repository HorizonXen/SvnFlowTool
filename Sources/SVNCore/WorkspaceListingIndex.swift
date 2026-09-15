import Foundation

/// Immutable per-scan index. Change-only browsing never traverses the full file list.
public struct WorkspaceListingIndex: Sendable {
    private let entries: [WorkspaceEntry]
    private let changes: [WorkspaceEntry]
    private let directCounts: [String: Int]
    private let totalCounts: [String: Int]
    public init(_ entries: [WorkspaceEntry]) {
        self.entries = entries
        changes = entries.filter { ![ItemState.normal, .ignored, .external].contains($0.state) }
        var direct: [String: Int] = [:]
        var directories = Set<String>()
        for entry in entries {
            if entry.isDirectory { directories.insert(entry.relative) }
            else { direct[(entry.relative as NSString).deletingLastPathComponent, default: 0] += 1 }
        }
        var totals = direct
        for directory in directories.sorted(by: >) where !directory.isEmpty {
            totals[(directory as NSString).deletingLastPathComponent, default: 0] += totals[directory, default: 0]
        }
        directCounts = direct; totalCounts = totals
    }
    public struct Listing: Sendable {
        public let scopedCount: Int
        public let shown: [WorkspaceEntry]
    }
    public func list(directory: String, recursive: Bool, unchanged: Bool, unversioned: Bool, filter: String, ignored: Set<String> = []) -> Listing {
        let scopedChanges = changes.filter { WorkspaceScope.includes(relative: $0.relative, directory: directory, isDirectory: $0.isDirectory, state: $0.state, recursive: recursive) }
        let count = (recursive ? totalCounts[directory, default: 0] : directCounts[directory, default: 0]) + scopedChanges.filter {
            $0.isDirectory || (!recursive && ($0.relative as NSString).deletingLastPathComponent != directory)
        }.count
        let candidates: [WorkspaceEntry]
        if unchanged {
            candidates = entries.filter { WorkspaceScope.includes(relative: $0.relative, directory: directory, isDirectory: $0.isDirectory, state: $0.state, recursive: recursive) }
        } else { candidates = scopedChanges }
        let shown = candidates.filter {
            !LocalIgnore.contains($0.path, rules: ignored) && (unversioned || $0.state != .unversioned) && (filter.isEmpty || $0.name.localizedCaseInsensitiveContains(filter))
        }.sorted { $0.name == $1.name ? $0.relative < $1.relative : $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        return Listing(scopedCount: count, shown: shown)
    }
}
