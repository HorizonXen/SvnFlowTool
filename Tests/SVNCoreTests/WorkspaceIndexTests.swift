import Foundation
import SVNCore

enum WorkspaceIndexTests {
    static func run() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("index-test-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root.appendingPathComponent("Assets/Deep"), withIntermediateDirectories: true)
        for name in ["Assets/a.txt", "Assets/Deep/b.txt", "Assets/Deep/c.txt"] {
            try "data".write(to: root.appendingPathComponent(name), atomically: true, encoding: .utf8)
        }
        let xml = """
        <status><target path="\(root.path)">
        <entry path="\(root.path)"><wc-status item="normal" props="modified" revision="3"/></entry>
        <entry path="\(root.path)/Assets"><wc-status item="normal" props="none" revision="3"/></entry>
        <entry path="\(root.path)/Assets/Deep"><wc-status item="normal" props="modified" revision="3"/></entry>
        <entry path="\(root.path)/Assets/a.txt"><wc-status item="normal" props="none" revision="3"/></entry>
        <entry path="\(root.path)/Assets/Deep/b.txt"><wc-status item="modified" props="none" revision="3"/></entry>
        <entry path="\(root.path)/Assets/Deep/c.txt"><wc-status item="normal" props="none" revision="3"/></entry>
        </target></status>
        """
        let catalog = WorkspaceCatalog.build(root: root.path, status: try WorkingCopyStatus.parse(Data(xml.utf8), root: root.path))
        let index = WorkspaceListingIndex(catalog)
        func list(_ dir: String, _ recursive: Bool, _ unchanged: Bool, _ filter: String = "") -> WorkspaceListingIndex.Listing {
            index.list(directory: dir, recursive: recursive, unchanged: unchanged, unversioned: true, filter: filter)
        }
        expectEqual(list("Assets", true, false).scopedCount, 4)
        expectEqual(list("Assets", false, false).scopedCount, 3)
        expectEqual(Set(list("Assets", false, false).shown.map(\.relative)), ["Assets/Deep", "Assets/Deep/b.txt"])
        expectEqual(list("", true, false).scopedCount, 5)
        expectEqual(list("Assets", true, true).shown.count, 4)
        expectEqual(list("Assets", true, true, "b.txt").shown.count, 1)
        expectEqual(list("AssetsOther", true, true).shown.count, 0)
        print("PASS: indexed subtree counts, changed directories, recursion and search")
        let hidden: Set<String> = [root.path + "/Assets/Deep"]
        expectEqual(index.list(directory: "Assets", recursive: true, unchanged: true, unversioned: true, filter: "", ignored: hidden).shown.map(\.relative), ["Assets/a.txt"])
        expectEqual(index.list(directory: "Assets", recursive: true, unchanged: false, unversioned: true, filter: "", ignored: hidden).shown.count, 0)
        expectEqual(LocalIgnore.contains(root.path + "/Assets/DeepOther/x", rules: hidden), false)
        expectEqual(LocalIgnore.contains(root.path + "/Assets/Deep/中文 @.txt", rules: hidden), true)
        expectEqual(LocalIgnore.contains(root.path + "Other/Assets/Deep/b.txt", rules: hidden), false)
        let fileRule: Set<String> = [root.path + "/Assets/Deep/b.txt"]
        expectEqual(index.list(directory: "Assets", recursive: true, unchanged: false, unversioned: true, filter: "", ignored: fileRule).shown.map(\.relative), ["Assets/Deep"])
        expectEqual(index.list(directory: "Assets", recursive: true, unchanged: false, unversioned: true, filter: "", ignored: []).shown.count, 2)
        let suite = "ignore-test-" + UUID().uuidString
        let store = UserDefaults(suiteName: suite)!
        defer { store.removePersistentDomain(forName: suite) }
        store.set(hidden.sorted(), forKey: LocalIgnore.storageKey)
        expectEqual(Set(UserDefaults(suiteName: suite)!.stringArray(forKey: LocalIgnore.storageKey) ?? []), hidden)
        print("PASS: persistent local ignore, directory descendants, sibling/copy boundaries, single file and restoration")
        var scroll = ScrollDirectionLock()
        expectEqual(scroll.direction(x: 0.4, y: 12, startsGesture: true, continuous: true), .vertical)
        expectEqual(scroll.direction(x: 7, y: 2, startsGesture: false, continuous: true), .vertical)
        expectEqual(scroll.direction(x: 0.8, y: 0.2, startsGesture: false, continuous: true), .vertical)
        expectEqual(scroll.direction(x: 12, y: 1, startsGesture: true, continuous: true), .horizontal)
        expectEqual(scroll.direction(x: 1, y: 8, startsGesture: false, continuous: true), .horizontal)
        expectEqual(scroll.direction(x: 0, y: 10, startsGesture: false, continuous: false), .vertical)
        expectEqual(scroll.direction(x: 0, y: 10, startsGesture: false, continuous: false, shift: true), .horizontal)
        print("PASS: scroll axis lock, gesture drift, momentum, new gesture, wheel and shift scrolling")
    }
}
