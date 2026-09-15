import Foundation

public struct DirectoryChanges: Sendable {
    public var count = 0
    public var state: ItemState = .normal

    /// Aggregate each changed entry once into its directory and every ancestor.
    public static func summarize(_ changes: [StatusItem], directories: Set<String>) -> [String: DirectoryChanges] {
        var result: [String: DirectoryChanges] = [:]
        func rank(_ state: ItemState) -> Int {
            switch state {
            case .conflicted, .obstructed, .incomplete: 5
            case .deleted, .missing: 4
            case .modified, .replaced: 3
            case .added: 2
            case .unversioned: 1
            default: 0
            }
        }
        for change in changes where change.hasLocalChange {
            var relative = change.relative
            while true {
                if relative.isEmpty || directories.contains(relative) {
                    var summary = result[relative] ?? .init()
                    summary.count += 1
                    if rank(change.state) > rank(summary.state) { summary.state = change.state }
                    result[relative] = summary
                }
                if relative.isEmpty { break }
                relative = (relative as NSString).deletingLastPathComponent
            }
        }
        return result
    }
}
