import Foundation

public enum ItemState: String, Codable, Sendable {
    case modified, added, deleted, replaced, conflicted, missing, unversioned, ignored, normal, external, incomplete, obstructed, unknown
}

public struct StatusItem: Identifiable, Hashable, Codable, Sendable {
    public var id: String { path }
    public let path: String
    public let relative: String
    public let textState: ItemState
    public let propertyState: String
    public let revision: String?
    public let lastChangedRevision: String?
    public let author: String
    public let copied: Bool
    public let switched: Bool
    public let treeConflicted: Bool

    public var state: ItemState {
        if treeConflicted || propertyState == "conflicted" { return .conflicted }
        if textState == .normal && propertyState == "modified" { return .modified }
        return textState
    }

    public var hasLocalChange: Bool { ![.normal, .ignored, .external].contains(state) }
}

public enum StatusReadError: LocalizedError {
    case invalidXML
    public var errorDescription: String? { "无法解析 SVN 状态" }
}

public enum WorkingCopyStatus {
    public static func parse(_ data: Data, root: String) throws -> [StatusItem] {
        let delegate = StatusXMLDelegate(root: root)
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse(), delegate.sawStatus else { throw StatusReadError.invalidXML }
        return delegate.items
    }
}

private final class StatusXMLDelegate: NSObject, XMLParserDelegate {
    private let root: String
    private var entryPath: String?
    private var attributes: [String: String]?
    private var changedRevision: String?
    private var author = ""
    private var elements: [String] = []
    var items: [StatusItem] = []
    var sawStatus = false

    init(root: String) { self.root = (root as NSString).standardizingPath }

    func parser(_ parser: XMLParser, didStartElement element: String, namespaceURI: String?, qualifiedName: String?, attributes values: [String: String]) {
        elements.append(element)
        if element == "status" { sawStatus = true }
        if element == "entry" {
            entryPath = values["path"]
            attributes = nil
            changedRevision = nil
            author = ""
        }
        if element == "wc-status" { attributes = values }
        if element == "commit" && elements.contains("wc-status") { changedRevision = values["revision"] }
    }

    func parser(_ parser: XMLParser, foundCharacters text: String) {
        if elements.suffix(3).elementsEqual(["wc-status", "commit", "author"]) { author += text }
    }

    func parser(_ parser: XMLParser, didEndElement element: String, namespaceURI: String?, qualifiedName: String?) {
        if element == "entry", let entryPath, let attributes {
            let raw = entryPath.hasPrefix("/") ? entryPath : root + "/" + entryPath
            let path = raw.contains("/../") || raw.contains("/./") || raw.contains("//") || raw.hasSuffix("/.") || raw.hasSuffix("/..") ? (raw as NSString).standardizingPath : raw
            let relative = path == root ? "" : (path.hasPrefix(root + "/") ? String(path.dropFirst(root.count + 1)) : path)
            let revision = attributes["revision"].flatMap { $0 == "-1" ? nil : $0 }
            items.append(StatusItem(
                path: path, relative: relative,
                textState: ItemState(rawValue: attributes["item"] ?? "") ?? .unknown,
                propertyState: attributes["props"] ?? "none", revision: revision,
                lastChangedRevision: changedRevision, author: author,
                copied: attributes["copied"] == "true", switched: attributes["switched"] == "true",
                treeConflicted: attributes["tree-conflicted"] == "true"
            ))
        }
        if !elements.isEmpty { elements.removeLast() }
    }
}
