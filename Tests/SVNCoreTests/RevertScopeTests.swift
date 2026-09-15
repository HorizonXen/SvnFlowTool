import Foundation
import SVNCore

enum RevertScopeTests {
    static func run() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("revert-scope-" + UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }
        let bin = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"].first { fm.isExecutableFile(atPath: $0 + "/svnadmin") }!
        func svn(_ args: [String]) throws -> CommandResult {
            try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svn"), arguments: ["--non-interactive"] + args).checked()
        }
        let repo = root.appendingPathComponent("repo"), wc = root.appendingPathComponent("工作副本 space")
        _ = try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svnadmin"), arguments: ["create", repo.path]).checked()
        _ = try svn(["checkout", repo.absoluteString, wc.path])
        let folder = wc.appendingPathComponent("folder")
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        let selected = folder.appendingPathComponent("中文 @ file.txt"), hidden = folder.appendingPathComponent("hidden.txt")
        let missing = wc.appendingPathComponent("missing.txt"), deleted = wc.appendingPathComponent("deleted.txt")
        let conflict = wc.appendingPathComponent("conflict.txt")
        for file in [selected, hidden, missing, deleted, conflict] { try "base\n".write(to: file, atomically: true, encoding: .utf8) }
        _ = try svn(["add", "--force", wc.path])
        _ = try svn(["commit", "-m", "seed", wc.path])
        let remote = root.appendingPathComponent("other-copy")
        _ = try svn(["checkout", repo.absoluteString, remote.path])
        try "remote\n".write(to: remote.appendingPathComponent("conflict.txt"), atomically: true, encoding: .utf8)
        _ = try svn(["commit", "-m", "fixture conflict", remote.path])
        for file in [selected, hidden, conflict] { try "local\n".write(to: file, atomically: true, encoding: .utf8) }
        _ = try svn(["update", "--accept", "postpone", wc.path])
        try fm.removeItem(at: missing)
        _ = try svn(["delete", deleted.path])
        _ = try svn(["propset", "fixture:prop", "local", folder.path])
        let unversioned = wc.appendingPathComponent("keep-unversioned.txt")
        try "keep\n".write(to: unversioned, atomically: true, encoding: .utf8)
        let added = wc.appendingPathComponent("added")
        try fm.createDirectory(at: added, withIntermediateDirectories: true)
        let addedChild = added.appendingPathComponent("child.txt")
        try "added\n".write(to: addedChild, atomically: true, encoding: .utf8)
        _ = try svn(["add", added.path])
        func status() throws -> [StatusItem] {
            try WorkingCopyStatus.parse(try svn(["status", "--xml", "--verbose", wc.path]).standardOutput, root: wc.path)
        }
        let before = try status()
        let selection = Set([selected, folder, missing, deleted, conflict, unversioned, added, addedChild].map(\.path))
        let paths = RevertScope.paths(in: before, selected: selection)
        expectEqual(paths.count, 7)
        expectEqual(paths.contains(hidden.path), false)
        expectEqual(paths.contains(unversioned.path), false)
        expectEqual(RevertScope.paths(in: before, selected: []).isEmpty, true)
        expectEqual(paths.firstIndex(of: addedChild.path)! < paths.firstIndex(of: added.path)!, true)
        _ = try svn(RevertScope.arguments(for: paths))
        expectEqual(try String(contentsOf: selected, encoding: .utf8), "base\n")
        expectEqual(try String(contentsOf: hidden, encoding: .utf8), "local\n")
        expectEqual(try String(contentsOf: conflict, encoding: .utf8), "remote\n")
        expectEqual(try String(contentsOf: unversioned, encoding: .utf8), "keep\n")
        expectEqual(try String(contentsOf: addedChild, encoding: .utf8), "added\n")
        expectEqual(fm.fileExists(atPath: missing.path), true)
        expectEqual(fm.fileExists(atPath: deleted.path), true)
        let after = try status()
        expectEqual(after.first { $0.path == folder.path }?.propertyState, "none")
        expectEqual(after.first { $0.path == hidden.path }?.state, .modified)
        expectEqual(after.first { $0.path == added.path }?.state, .unversioned)
        // A property-only change and conflict are supported; foreign/unknown states are not.
        for state in [ItemState.normal, .ignored, .external, .unversioned, .incomplete, .obstructed, .unknown] {
            expectEqual(RevertScope.supports(state), false)
        }
        print("PASS: batch revert restores selected content/properties/deletions/conflicts, preserves unselected children and unversioned files, supports literal @ paths and added hierarchies")
    }
}
