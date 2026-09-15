import Foundation

public struct UpdateTracker: Sendable {
    private var pending = Data()
    public private(set) var paths = Set<String>()
    public private(set) var deletedPaths = Set<String>()
    public private(set) var detail = "正在等待 SVN 输出…"
    public var count: Int { paths.count }
    public init() {}
    public mutating func append(_ data: Data) {
        pending.append(data)
        while let end = pending.firstIndex(of: 10) {
            consume(String(decoding: pending[..<end], as: UTF8.self))
            pending.removeSubrange(...end)
        }
    }
    public mutating func finish() { if !pending.isEmpty { consume(String(decoding: pending, as: UTF8.self)); pending.removeAll() } }
    private mutating func consume(_ line: String) {
        let text = line.trimmingCharacters(in: .newlines)
        guard !text.isEmpty else { return }
        detail = text
        let columns = Array(text.prefix(5))
        if columns.count == 5, columns[4] == " ", columns.prefix(4).allSatisfy({ " ADUGCERB".contains($0) }), columns.prefix(4).contains(where: { $0 != " " }) {
            let path = String(text.dropFirst(5)).trimmingCharacters(in: .whitespaces)
            if !path.isEmpty { paths.insert(path); if columns[0] == "D" { deletedPaths.insert(path) }; detail = path }
        }
    }
}
