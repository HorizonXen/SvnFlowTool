import Foundation
import SVNCore

enum UpdateRefreshTests {
    static func run() throws {
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("update-test-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let bin = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"].first { FileManager.default.isExecutableFile(atPath: $0 + "/svnadmin") }!
        func svn(_ args: [String]) throws -> Data { try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svn"), arguments: ["--non-interactive"] + args).checked().standardOutput }
        let repo = base.appendingPathComponent("repo"), a = base.appendingPathComponent("a"), b = base.appendingPathComponent("b")
        _ = try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svnadmin"), arguments: ["create", repo.path]).checked()
        _ = try svn(["checkout", repo.absoluteString, a.path])
        for path in ["selected/old/file.txt", "selected/edit @ 中文.txt", "sibling/file.txt"] {
            let url = a.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("before".utf8).write(to: url)
        }
        _ = try svn(["add", a.appendingPathComponent("selected").path, a.appendingPathComponent("sibling").path])
        _ = try svn(["commit", a.path, "-m", "seed"])
        _ = try svn(["checkout", repo.absoluteString, b.path])
        func status(_ args: [String]) throws -> [StatusItem] { try WorkingCopyStatus.parse(svn(["status", "--xml", "--verbose"] + args), root: b.path) }
        _ = try svn(["propset", "test", "local", b.path])
        let before = try status([b.path]), catalog = WorkspaceCatalog.build(root: b.path, status: before)
        _ = try svn(["propdel", "test", b.path])
        _ = try svn(["delete", a.appendingPathComponent("selected/old").path])
        try Data("after".utf8).write(to: a.appendingPathComponent("selected/edit @ 中文.txt"))
        try Data("after".utf8).write(to: a.appendingPathComponent("sibling/file.txt"))
        try Data("new".utf8).write(to: a.appendingPathComponent("selected/new.txt"))
        _ = try svn(["add", a.appendingPathComponent("selected/new.txt").path])
        _ = try svn(["commit", a.path, "-m", "change"])
        let target = UpdateRefresh.target(root: b.path, directory: "selected")
        expectEqual(UpdateRefresh.target(root: b.path, directory: "../outside"), b.path)
        expectEqual(UpdateRefresh.contains(b.path + "/selected-other", in: target), false)
        var tracker = UpdateTracker()
        tracker.append(try svn(["update", "--accept", "postpone", "--", target + "@"])); tracker.finish()
        expectEqual(String(decoding: try Data(contentsOf: b.appendingPathComponent("sibling/file.txt")), as: UTF8.self), "before")
        expectEqual(tracker.paths.contains(b.appendingPathComponent("selected/new.txt").path), true)
        expectEqual(tracker.deletedPaths.contains(b.appendingPathComponent("selected/old").path), true)
        let queried = tracker.paths.union([target, b.path])
        let fresh = try status(["--depth", "empty", "--"] + queried.sorted().map { $0 + "@" })
        let merged = UpdateRefresh.merge(root: b.path, previous: before, entries: catalog, refreshed: fresh, queried: queried, deleted: tracker.deletedPaths)
        expectEqual(merged.1.contains { $0.path == b.path }, false)
        expectEqual(merged.1.contains { $0.relative == "selected/old/file.txt" }, false)
        expectEqual(merged.1.first { $0.relative == "selected/new.txt" }?.state, .normal)
        expectEqual(merged.1.first { $0.relative == "sibling/file.txt" }?.revision, "1")
        let full = WorkspaceCatalog.build(root: b.path, status: try status([b.path]), previous: catalog)
        expectEqual(merged.1.map(\.relative), full.map(\.relative))
        expectEqual(merged.1.map(\.state), full.map(\.state))
        var noChange = UpdateTracker()
        noChange.append(try svn(["update", "--", target + "@"])); noChange.finish()
        expectEqual(noChange.count, 0)
        try Data("local conflict".utf8).write(to: b.appendingPathComponent("selected/edit @ 中文.txt"))
        try Data("remote conflict".utf8).write(to: a.appendingPathComponent("selected/edit @ 中文.txt"))
        _ = try svn(["commit", a.path, "-m", "conflict input"])
        var conflict = UpdateTracker()
        conflict.append(try svn(["update", "--accept", "postpone", "--", target + "@"])); conflict.finish()
        let affected = conflict.paths.union([target])
        let conflictItems = try status(["--depth", "empty", "--"] + affected.sorted().map { $0 + "@" })
        let result = UpdateRefresh.merge(root: b.path, previous: merged.0, entries: merged.1, refreshed: conflictItems, queried: affected, deleted: [])
        expectEqual(result.1.first { $0.relative == "selected/edit @ 中文.txt" }?.state, .conflicted)
        print("PASS: scoped update, sibling preservation, deletion, new files, special paths, cleared root property, no-op and conflict")
    }
}
