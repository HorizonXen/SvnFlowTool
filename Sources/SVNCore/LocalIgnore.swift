import Foundation

/// Absolute local paths keep display preferences isolated between working copies.
public enum LocalIgnore {
    public static let storageKey = "SvnFlow.hiddenLocalPaths.v1"
    public static func contains(_ path: String, rules: Set<String>) -> Bool {
        guard !rules.isEmpty else { return false }
        var candidate = path
        while !candidate.isEmpty {
            if rules.contains(candidate) { return true }
            let parent = (candidate as NSString).deletingLastPathComponent
            if parent == candidate { break }
            candidate = parent
        }
        return false
    }
}
