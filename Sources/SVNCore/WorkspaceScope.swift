import Foundation

public enum WorkspaceScope {
    /// Local changes always include descendants; the recursion option only limits unchanged files.
    public static func includes(relative: String, directory: String, isDirectory: Bool, state: ItemState, recursive: Bool) -> Bool {
        let changed = ![ItemState.normal, .ignored, .external].contains(state)
        let within = directory.isEmpty || relative == directory || relative.hasPrefix(directory + "/")
        guard within else { return false }
        if changed { return true }
        guard !isDirectory else { return false }
        return recursive || (relative as NSString).deletingLastPathComponent == directory
    }
}
