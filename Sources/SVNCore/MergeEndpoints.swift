import Foundation

public enum MergeEndpoints {
    public static func displayName(for path: String, fallback: String) -> String {
        let normalized = path.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\", with: "/")
        let trimmed = normalized.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !trimmed.isEmpty else { return fallback }
        let name = trimmed.split(separator: "/", omittingEmptySubsequences: true).last.map(String.init) ?? ""
        guard !name.isEmpty, !name.hasSuffix(":") else { return fallback }
        return name
    }

    public static func direction(sourcePath: String, targetPath: String) -> String {
        let source = displayName(for: sourcePath, fallback: "源目录")
        let target = displayName(for: targetPath, fallback: "目标目录")
        return "\(source) → \(target)"
    }
}
