import Foundation

struct PatchPreviewRow {
    let oldNumber: Int?
    let newNumber: Int?
    let oldText: String
    let newText: String
    let changed: Bool
}

/// Presentation of SVN's existing unified diff, pairing adjacent removed/added lines.
enum PatchPreview {
    static func rows(_ patch: String) -> [PatchPreviewRow] {
        let header = try! NSRegularExpression(pattern: #"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"#)
        var result: [PatchPreviewRow] = []
        var oldLine = 0, newLine = 0
        var inHunk = false
        var removed: [String] = [], added: [String] = []
        func flush() {
            for index in 0..<max(removed.count, added.count) {
                let hasOld = index < removed.count, hasNew = index < added.count
                result.append(.init(oldNumber: hasOld ? oldLine : nil, newNumber: hasNew ? newLine : nil,
                                    oldText: hasOld ? removed[index] : "", newText: hasNew ? added[index] : "", changed: true))
                if hasOld { oldLine += 1 }
                if hasNew { newLine += 1 }
            }
            removed = []; added = []
        }
        for line in patch.components(separatedBy: "\n") {
            if let match = header.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)) {
                flush()
                let text = line as NSString
                oldLine = Int(text.substring(with: match.range(at: 1))) ?? 1
                newLine = Int(text.substring(with: match.range(at: 2))) ?? 1
                inHunk = true
            } else if inHunk && line.hasPrefix("-") { removed.append(String(line.dropFirst())) }
            else if inHunk && line.hasPrefix("+") { added.append(String(line.dropFirst())) }
            else if inHunk && line.hasPrefix(" ") {
                flush()
                let text = String(line.dropFirst())
                result.append(.init(oldNumber: oldLine, newNumber: newLine, oldText: text, newText: text, changed: false))
                oldLine += 1; newLine += 1
            } else if !line.hasPrefix("\\") {
                flush()
                inHunk = false
            }
        }
        flush()
        return result
    }
}
