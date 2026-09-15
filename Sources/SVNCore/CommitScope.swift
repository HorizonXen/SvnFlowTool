import Foundation

/// Capture the directory when opening the sheet; filtering must never widen it.
public enum CommitScope {
    public static func files(_ statuses: [StatusItem], directory: String) -> [StatusItem] {
        statuses.filter {
            directory.isEmpty || $0.relative == directory || $0.relative.hasPrefix(directory + "/")
        }
    }

    public static func selection(in files: [StatusItem], selected: Set<String>) -> Set<String> {
        let eligible = Set(files.filter {
            [.modified, .added, .deleted, .replaced].contains($0.state)
        }.map(\.path))
        return selected.isEmpty ? eligible : selected.intersection(eligible)
    }
}
