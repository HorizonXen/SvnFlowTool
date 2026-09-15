import Foundation
import SVNCore

struct WorkingCopyStatusTests {
    func testPropertyOnlyChangeAndMixedRevisions() throws {
        let xml = """
        <status><target path="/tmp/wc">
        <entry path="plain.txt"><wc-status item="normal" props="none" revision="4"><commit revision="2"><author>A</author></commit></wc-status></entry>
        <entry path="props.txt"><wc-status item="normal" props="modified" revision="9"><commit revision="8"><author>B &amp; C</author></commit></wc-status></entry>
        </target></status>
        """
        let entries = try WorkingCopyStatus.parse(Data(xml.utf8), root: "/tmp/wc")
        expectEqual(entries[0].path, "/tmp/wc/plain.txt")
        expectEqual(entries[0].revision, "4")
        expectEqual(entries[0].hasLocalChange, false)
        expectEqual(entries[1].revision, "9")
        expectEqual(entries[1].lastChangedRevision, "8")
        expectEqual(entries[1].state, .modified)
        expectEqual(entries[1].hasLocalChange, true)
        expectEqual(entries[1].author, "B & C")
    }

    func testConflictAndCopiedMetadata() throws {
        let xml = """
        <status><target path="/tmp/wc">
        <entry path="/tmp/wc"><wc-status item="normal" props="conflicted" revision="2"/></entry>
        <entry path="new"><wc-status item="added" props="none" revision="-1" copied="true" switched="true" tree-conflicted="true"/></entry>
        </target></status>
        """
        let entries = try WorkingCopyStatus.parse(Data(xml.utf8), root: "/tmp/wc")
        expectEqual(entries[0].relative, "")
        expectEqual(entries[0].state, .conflicted)
        expectEqual(entries[1].revision, nil)
        expectEqual(entries[1].copied, true)
        expectEqual(entries[1].switched, true)
        expectEqual(entries[1].state, .conflicted)
    }

    func testMalformedStatusFails() {
        expectThrows(try WorkingCopyStatus.parse(Data("<status>".utf8), root: "/tmp/wc"))
        expectThrows(try WorkingCopyStatus.parse(Data("<other/>".utf8), root: "/tmp/wc"))
    }

    func testRealRepository() throws {
        let fm = FileManager.default
        let candidates = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
        guard let bin = candidates.first(where: { fm.isExecutableFile(atPath: $0 + "/svnadmin") && fm.isExecutableFile(atPath: $0 + "/svn") }) else {
            throw StatusFixtureError.missingSVN
        }
        let root = fm.temporaryDirectory.appendingPathComponent("SvnFlow-check-" + UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }
        let repository = root.appendingPathComponent("repository", isDirectory: true)
        let wc = root.appendingPathComponent("工作副本 space", isDirectory: true)
        let runner = CommandRunner()
        _ = try runner.run(executable: URL(fileURLWithPath: bin + "/svnadmin"), arguments: ["create", repository.path]).checked()
        func svn(_ args: [String]) throws -> CommandResult {
            try runner.run(executable: URL(fileURLWithPath: bin + "/svn"), arguments: ["--non-interactive"] + args).checked()
        }
        _ = try svn(["checkout", repository.absoluteString, wc.path])
        let first = wc.appendingPathComponent("first.txt")
        let second = wc.appendingPathComponent("中文 @ file.txt")
        let missing = wc.appendingPathComponent("missing.txt")
        for file in [first, second, missing] { try "one\n".write(to: file, atomically: true, encoding: .utf8) }
        _ = try svn(["add", "--force", wc.path])
        _ = try svn(["commit", "-m", "initial", wc.path])
        try "two\n".write(to: first, atomically: true, encoding: .utf8)
        _ = try svn(["commit", "-m", "first only", first.path])
        _ = try svn(["propset", "test:property", "value", second.path + "@"])
        try fm.removeItem(at: missing)
        let result = try svn(["status", "--xml", "--verbose", "--no-ignore", wc.path])
        let entries = try WorkingCopyStatus.parse(result.standardOutput, root: wc.path)
        expectEqual(entries.first { $0.relative == "first.txt" }?.revision, "2")
        expectEqual(entries.first { $0.relative == "中文 @ file.txt" }?.revision, "1")
        expectEqual(entries.first { $0.relative == "中文 @ file.txt" }?.state, .modified)
        expectEqual(entries.first { $0.relative == "missing.txt" }?.state, .missing)
    }
}

private enum StatusFixtureError: Error { case missingSVN }
