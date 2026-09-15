import Foundation

public struct CommitTarget: Sendable {
    public let path: String
    public let url: String
}

/// Repository identity must be checked across working copies, including externals.
public enum CommitTargets {
    public static func parse(_ data: Data, root: String) throws -> [CommitTarget] {
        let delegate = CommitInfoParser(root: root)
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse(), delegate.sawInfo, !delegate.invalid else {
            throw NSError(domain: "CommitTargets", code: 1, userInfo: [NSLocalizedDescriptionKey: "无法读取提交目标的 SVN 地址"])
        }
        return delegate.targets
    }

    public static func duplicates(_ targets: [CommitTarget]) -> [[String]] {
        Dictionary(grouping: targets, by: \.url).values
            .map { Array(Set($0.map(\.path))).sorted() }
            .filter { $0.count > 1 }
            .sorted { $0[0] < $1[0] }
    }
}

private final class CommitInfoParser: NSObject, XMLParserDelegate {
    let root: String
    var sawInfo = false
    var invalid = false
    var targets: [CommitTarget] = []
    var path: String?
    var url = ""
    var readingURL = false

    init(root: String) { self.root = root }

    func parser(_ parser: XMLParser, didStartElement element: String, namespaceURI: String?, qualifiedName: String?, attributes: [String: String]) {
        if element == "info" { sawInfo = true }
        if element == "entry" { path = attributes["path"]; url = "" }
        if element == "url" { readingURL = true }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if readingURL { url += string }
    }

    func parser(_ parser: XMLParser, didEndElement element: String, namespaceURI: String?, qualifiedName: String?) {
        if element == "url" { readingURL = false }
        if element == "entry" {
            guard let path, !url.isEmpty else { invalid = true; return }
            let absolute = (path as NSString).isAbsolutePath ? path : (root as NSString).appendingPathComponent(path)
            targets.append(CommitTarget(path: (absolute as NSString).standardizingPath, url: url))
        }
    }
}
