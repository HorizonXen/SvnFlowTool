import Foundation

/// Revert only explicit, versioned local changes; never widen an empty selection.
public enum RevertScope {
    public static func supports(_ state: ItemState) -> Bool {
        [.modified, .added, .deleted, .replaced, .conflicted, .missing].contains(state)
    }

    public static func paths(in statuses: [StatusItem], selected: Set<String>) -> [String] {
        Array(Set(statuses.filter { selected.contains($0.path) && supports($0.state) }.map(\.path)))
            .sorted { left, right in
                // Children first so explicitly selected added/deleted parents cannot
                // invalidate a later target. depth empty protects unselected children.
                let l = left.split(separator: "/").count, r = right.split(separator: "/").count
                return l == r ? left < right : l > r
            }
    }

    public static func arguments(for paths: [String]) -> [String] {
        ["revert", "--depth", "empty", "--"] + paths.map { $0 + "@" }
    }
}
