import Foundation

public struct RepositoryEntry: Sendable {
    public let name: String
    public let kind: String
    public let size: Int64
    public let revision: String
    public let author: String
    public let date: String
}
public struct ChangedPath: Sendable, Equatable {
    public let kind: String
    public let path: String
    public let action: String
    public let copyFrom: String
    public let copyRevision: String
}
public struct RevisionRecord: Sendable {
    public let revision: String
    public let author: String
    public let date: String
    public let message: String
    public let paths: [ChangedPath]
}

public enum RepositoryXML {
    public static func entries(_ data: Data) throws -> [RepositoryEntry] { try parse(data, root: "lists").entries }
    public static func history(_ data: Data) throws -> [RevisionRecord] { try parse(data, root: "log").records }
    private static func parse(_ data: Data, root: String) throws -> QueryParser {
        let delegate = QueryParser()
        let parser = XMLParser(data: data); parser.delegate = delegate
        guard parser.parse(), delegate.root == root else { throw NSError(domain: "SVN XML", code: 1, userInfo: [NSLocalizedDescriptionKey: "无效的 SVN XML 响应"] ) }
        return delegate
    }
}
private final class QueryParser: NSObject, XMLParserDelegate {
    var root = "", stack: [String] = [], value = ""
    var entries: [RepositoryEntry] = [], records: [RevisionRecord] = []
    var name = "", kind = "", revision = "", author = "", date = "", message = "", size: Int64 = 0
    var pathKind = ""
    var paths: [ChangedPath] = [], action = "", copyFrom = "", copyRevision = ""
    func parser(_ parser: XMLParser, didStartElement element: String, namespaceURI: String?, qualifiedName: String?, attributes: [String: String]) {
        if stack.isEmpty { root = element }; stack.append(element); value = ""
        if element == "entry" || element == "logentry" { name = ""; kind = attributes["kind"] ?? ""; revision = attributes["revision"] ?? ""; author = ""; date = ""; message = ""; size = 0; paths = [] }
        if element == "commit" { revision = attributes["revision"] ?? "" }
        if element == "path" { pathKind = attributes["kind"] ?? ""; action = attributes["action"] ?? ""; copyFrom = attributes["copyfrom-path"] ?? ""; copyRevision = attributes["copyfrom-rev"] ?? "" }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { value += string }
    func parser(_ parser: XMLParser, didEndElement element: String, namespaceURI: String?, qualifiedName: String?) {
        switch element {
        case "name": name = value
        case "size": size = Int64(value) ?? 0
        case "author": author = value
        case "date": date = value
        case "msg": message = value
        case "path": paths.append(.init(kind: pathKind, path: value, action: action, copyFrom: copyFrom, copyRevision: copyRevision))
        case "entry": entries.append(.init(name: name, kind: kind, size: size, revision: revision, author: author, date: date))
        case "logentry": records.append(.init(revision: revision, author: author, date: date, message: message, paths: paths))
        default: break
        }
        stack.removeLast(); value = ""
    }
}

/// Each actor executes blocking commands off the UI actor; windows own independent clients.
public actor RepositoryQuery {
    public init() {}
    private func run(_ args: [String]) throws -> Data {
        let candidates = ["/opt/homebrew/bin/svn", "/usr/local/bin/svn", "/usr/bin/svn"]
        guard let path = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { throw NSError(domain: "SVN", code: 1, userInfo: [NSLocalizedDescriptionKey: "未找到 SVN 命令行工具"]) }
        return try CommandRunner().run(executable: URL(fileURLWithPath: path), arguments: ["--non-interactive"] + args).checked().standardOutput
    }
    public func comparisonData(_ path: String) throws -> ComparisonData {
        let status = try WorkingCopyStatus.parse(run(["status", "--xml", "--verbose", "--", path + "@"]), root: (path as NSString).deletingLastPathComponent).first
        let emptyBase = status?.textState == .unversioned || (status?.textState == .added && status?.copied != true)
        let base = emptyBase ? Data() : try run(["cat", "-r", "BASE", "--", path + "@"])
        let missing = status?.textState == .missing || status?.textState == .deleted
        let local = missing && !FileManager.default.fileExists(atPath: path) ? Data() : try Data(contentsOf: URL(fileURLWithPath: path))
        return ComparisonData(old: base, new: local, label: emptyBase ? "Empty — new file" : "BASE · r" + (status?.revision ?? "?"))
    }
    public func compareFile(_ path: String) throws -> FileComparison {
        let data = try comparisonData(path)
        return try data.textComparison()
    }
    public func repositoryComparisonData(_ url: String, revision: String, change: ChangedPath? = nil) throws -> ComparisonData {
        if let change {
            guard change.kind != "dir", let number = Int(revision), number > 0 else {
                throw NSError(domain: "Compare", code: 4, userInfo: [NSLocalizedDescriptionKey: "请选择文件查看版本差异。"])
            }
            let previous = String(number - 1)
            let new = change.action == "D" ? Data() : try run(["cat", "-r", revision, "--", url + "@" + revision])
            let old: Data
            let label: String
            if change.action == "A", !change.copyFrom.isEmpty {
                let root = try info(url, item: "repos-root-url", revision: revision)
                let source = URL(string: root)!.appendingPathComponent(String(change.copyFrom.dropFirst())).absoluteString
                old = try run(["cat", "-r", change.copyRevision, "--", source + "@" + change.copyRevision])
                label = "Copy source · r" + change.copyRevision
            } else if change.action == "A" {
                old = Data(); label = "Empty — added in r" + revision
            } else {
                // Use each side's own peg so deleted/replaced nodes remain addressable.
                old = try run(["cat", "-r", previous, "--", url + "@" + previous])
                label = "Previous · r" + previous
            }
            return ComparisonData(old: old, new: new, label: label)
        }
        let records = try history(url, peg: revision, start: revision)
        guard let change = records.first, let changedRevision = Int(change.revision) else { throw NSError(domain: "Compare", code: 4, userInfo: [NSLocalizedDescriptionKey: "无法确定文件的上一版本。"]) }
        let root = try info(url, item: "repos-root-url", revision: revision)
        let path = String((url.removingPercentEncoding ?? url).dropFirst((root.removingPercentEncoding ?? root).count))
        let entry = change.paths.first { $0.path == path }
        let new = try run(["cat", "-r", revision, "--", url + "@" + revision])
        let old: Data
        let label: String
        if let entry, ["A", "R"].contains(entry.action), entry.copyFrom.isEmpty {
            old = Data(); label = "Empty — added in r" + change.revision
        } else if let entry, !entry.copyFrom.isEmpty {
            let source = URL(string: root)!.appendingPathComponent(String(entry.copyFrom.dropFirst())).absoluteString
            old = try run(["cat", "-r", entry.copyRevision, "--", source + "@" + entry.copyRevision]); label = "Copy source · r" + entry.copyRevision
        } else {
            let previous = String(max(0, changedRevision - 1))
            old = try run(["cat", "-r", previous, "--", url + "@" + revision]); label = "Previous · r" + previous
        }
        return ComparisonData(old: old, new: new, label: label)
    }
    public func compareRepositoryFile(_ url: String, revision: String, change: ChangedPath? = nil) throws -> FileComparison {
        try repositoryComparisonData(url, revision: revision, change: change).textComparison()
    }
    public func compareWorkbook(_ path: String, revision: String? = nil, change: ChangedPath? = nil) throws -> WorkbookComparison {
        let data = try revision.map { try repositoryComparisonData(path, revision: $0, change: change) } ?? comparisonData(path)
        return try WorkbookComparison(old: data.old, new: data.new, label: data.label)
    }
    public func list(_ url: String, revision: String) throws -> [RepositoryEntry] {
        try RepositoryXML.entries(run(["list", "--xml", "-r", revision, "--", url + "@" + revision]))
    }
    public func history(_ target: String, peg: String = "HEAD", start: String = "HEAD") throws -> [RevisionRecord] {
        try RepositoryXML.history(run(["log", "--xml", "--verbose", "--limit", "100", "-r", start + ":0", "--", target + "@" + peg]))
    }
    public func revisionDetails(_ target: String, revision: String) throws -> [RevisionRecord] {
        try RepositoryXML.history(run(["log", "--xml", "--verbose", "-r", revision, "--", target + "@" + revision]))
    }
    public func info(_ target: String, item: String, revision: String? = nil) throws -> String {
        var args = ["info", "--show-item", item]
        if let revision { args += ["-r", revision] }
        args += ["--", target + "@" + (revision ?? "")]
        return String(decoding: try run(args), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    public func content(_ url: String, revision: String) throws -> String {
        let data = try run(["cat", "-r", revision, "--", url + "@" + revision])
        guard !data.contains(0), let text = String(data: data, encoding: .utf8) else { return "此文件为二进制文件或非 UTF-8 文本，无法显示文本预览。" }
        return text
    }
}

public struct ComparisonFiles: Sendable {
    public let old: String?
    public let new: String?
    public let oldLabel: String
    public let newLabel: String
    public init(old: String?, new: String?, oldLabel: String, newLabel: String) {
        self.old = old; self.new = new; self.oldLabel = oldLabel; self.newLabel = newLabel
    }
    fileprivate func read() throws -> ComparisonData {
        try ComparisonData(old: old.map { try Data(contentsOf: URL(fileURLWithPath: $0)) } ?? Data(),
                           new: new.map { try Data(contentsOf: URL(fileURLWithPath: $0)) } ?? Data(), label: oldLabel)
    }
}
extension RepositoryQuery {
    public func compareFiles(_ files: ComparisonFiles) throws -> FileComparison { try files.read().textComparison() }
    public func compareWorkbookFiles(_ files: ComparisonFiles) throws -> WorkbookComparison {
        let data = try files.read()
        return try WorkbookComparison(old: data.old, new: data.new, label: data.label)
    }
}

public struct ComparisonData: Sendable {
    public let old: Data
    public let new: Data
    public let label: String
    func textComparison() throws -> FileComparison {
        func decode(_ data: Data) throws -> String {
            guard data.count <= 32 * 1_048_576 else {
                throw NSError(domain: "Compare", code: 5, userInfo: [NSLocalizedDescriptionKey: "文本文件超过 32 MB，暂不支持内置对比。"])
            }
            guard !data.contains(0), let text = String(data: data, encoding: .utf8) else {
                throw NSError(domain: "Compare", code: 5, userInfo: [NSLocalizedDescriptionKey: "文件为二进制或非 UTF-8 编码，无法进行文本对比。"])
            }
            return text
        }
        return try FileComparison(old: decode(old), new: decode(new), baseLabel: label)
    }
}
