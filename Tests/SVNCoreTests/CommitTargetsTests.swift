import Foundation
import SVNCore

enum CommitTargetsTests {
    static func run() throws {
        let fixture = Data("""
        <status><target path="/wc">
        <entry path="Client"><wc-status item="normal" props="modified"/></entry>
        <entry path="Client/a.lua"><wc-status item="modified" props="none"/></entry>
        <entry path="Client/sub/deleted.lua"><wc-status item="deleted" props="none"/></entry>
        <entry path="Client/conflict.lua"><wc-status item="conflicted" props="none"/></entry>
        <entry path="Client/new.lua"><wc-status item="unversioned" props="none"/></entry>
        <entry path="Client/normal.lua"><wc-status item="normal" props="none"/></entry>
        <entry path="ClientOther/a.lua"><wc-status item="modified" props="none"/></entry>
        <entry path="Server/a.lua"><wc-status item="modified" props="none"/></entry>
        </target></status>
        """.utf8)
        let entries = try WorkingCopyStatus.parse(fixture, root: "/wc")
        let scoped = CommitScope.files(entries, directory: "Client")
        expectEqual(scoped.count, 6)
        expectEqual(CommitScope.selection(in: scoped, selected: []), Set(["/wc/Client", "/wc/Client/a.lua", "/wc/Client/sub/deleted.lua"]))
        expectEqual(CommitScope.selection(in: scoped, selected: ["/wc/Server/a.lua"]), Set<String>())
        expectEqual(CommitScope.selection(in: scoped, selected: ["/wc/Client/a.lua", "/wc/Server/a.lua"]), Set(["/wc/Client/a.lua"]))
        expectEqual(CommitScope.files(entries, directory: "").count, entries.count)
        expectEqual(CommitScope.files(entries, directory: "Client/sub").map(\.relative), ["Client/sub/deleted.lua"])
        print("PASS: commit scope, sibling boundaries, directory properties, explicit selection and ineligible files")
        let fm = FileManager.default
        let base = fm.temporaryDirectory.appendingPathComponent("commit-targets-" + UUID().uuidString)
        try fm.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: base) }
        let bin = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"].first { fm.isExecutableFile(atPath: $0 + "/svnadmin") }!
        func svn(_ args: [String]) throws -> CommandResult {
            try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svn"), arguments: ["--non-interactive"] + args).checked()
        }
        let repo = base.appendingPathComponent("repo"), a = base.appendingPathComponent("client"), b = base.appendingPathComponent("server")
        _ = try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svnadmin"), arguments: ["create", repo.path]).checked()
        _ = try svn(["checkout", repo.absoluteString, a.path])
        let name = "中文 @ file.txt"
        let first = a.appendingPathComponent(name).path, second = b.appendingPathComponent(name).path
        try "before".write(toFile: first, atomically: true, encoding: .utf8)
        _ = try svn(["add", first + "@"])
        _ = try svn(["commit", "-m", "seed", a.path])
        _ = try svn(["checkout", repo.absoluteString, b.path])
        for path in [first, second] { try "after".write(toFile: path, atomically: true, encoding: .utf8) }
        let info = try svn(["info", "--xml", "--depth", "infinity", "--", a.path + "@", second + "@", first + "@"])
        let targets = try CommitTargets.parse(info.standardOutput, root: base.path)
        expectEqual(CommitTargets.duplicates(targets), [[first, second].sorted()])
        let single = try svn(["info", "--xml", "--", first + "@", first + "@"])
        expectEqual(CommitTargets.duplicates(try CommitTargets.parse(single.standardOutput, root: base.path)).isEmpty, true)
        expectThrows(try CommitTargets.parse(Data("<info><entry>".utf8), root: base.path))
        let failure = try CommandRunner().run(executable: URL(fileURLWithPath: bin + "/svn"), arguments: ["commit", "-m", "duplicate", "--", first + "@", second + "@"])
        expectEqual(failure.exitCode == 0, false)
        expectEqual(failure.errorText.contains("E195003"), true)
        print("PASS: duplicate commit targets across working copies, directories, and literal @ paths")
    }
}
