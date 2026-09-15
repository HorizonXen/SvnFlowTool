import Foundation
import SVNCore

struct CommandRunnerTests {
    func testLargeErrorOutputDoesNotBlockStandardOutput() throws {
        // The old sequential reader blocks when stderr fills before stdout closes.
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/bin/sh"), arguments: [
            "-c", "dd if=/dev/zero bs=65536 count=32 1>&2 2>/dev/null; printf '<result/>'"
        ]).checked()
        expectEqual(result.standardError.count, 2_097_152)
        expectEqual(result.outputText, "<result/>")
    }

    func testWarningIsNotInsertedIntoXML() throws {
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/bin/sh"), arguments: [
            "-c", "printf '<result/>'; printf 'warning' >&2"
        ]).checked()
        expectEqual(result.outputText, "<result/>")
        expectEqual(result.errorText, "warning")
    }

    func testFailurePreservesExitCodeAndBothStreams() throws {
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/bin/sh"), arguments: [
            "-c", "printf 'partial'; printf 'rejected' >&2; exit 7"
        ])
        expectThrows(try result.checked()) { error in
            let failure = error as? CommandFailure
            expectEqual(failure?.result.exitCode, 7)
            expectEqual(failure?.result.outputText, "partial")
            expectEqual(failure?.result.errorText, "rejected")
        }
    }

    func testArgumentsAreNotEvaluatedByShell() throws {
        let value = "中文 path @ $HOME `whoami` ; &"
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/usr/bin/printf"), arguments: ["%s", value]).checked()
        expectEqual(result.outputText, value)
    }

    func testWorkingDirectory() throws {
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/bin/pwd"), arguments: [], directory: URL(fileURLWithPath: "/private/tmp")).checked()
        expectEqual(result.outputText.trimmingCharacters(in: .whitespacesAndNewlines), "/private/tmp")
    }

    func testUTF8EnvironmentAndErrorPresentation() throws {
        let env = try CommandRunner().run(executable: URL(fileURLWithPath: "/usr/bin/env"), arguments: [], environment: ["LANG": "zh_CN.UTF-8", "LC_CTYPE": "C", "LANGUAGE": "zh_CN", "SVNFLOW_TEST_VALUE": "preserved"]).checked()
        expectEqual(Set(env.outputText.split(separator: "\n").map(String.init)), Set(["LC_ALL=en_US.UTF-8", "LC_CTYPE=en_US.UTF-8", "LC_MESSAGES=en_US.UTF-8", "LANG=en_US.UTF-8", "LANGUAGE=en", "SVNFLOW_TEST_VALUE=preserved"]))
        let result = try CommandRunner().run(executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "printf 'partial diff'; printf 'actual diagnostic' >&2; exit 1"])
        expectThrows(try result.checked()) { expectEqual($0.localizedDescription, "actual diagnostic") }
        expectEqual(result.outputText, "partial diff")
    }
    func testMissingExecutableThrows() {
        expectThrows(try CommandRunner().run(executable: URL(fileURLWithPath: "/nonexistent/svnflow-command"), arguments: []))
    }

    func testPythonChildrenDoNotRewriteSignedResources() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let executable = directory.appendingPathComponent("python3-fixture")
        try FileManager.default.createSymbolicLink(atPath: executable.path, withDestinationPath: "/usr/bin/env")
        let result = try CommandRunner().run(executable: executable, arguments: [], environment: ["PYTHONDONTWRITEBYTECODE": "0"]).checked()
        expectEqual(result.outputText.contains("PYTHONDONTWRITEBYTECODE=1"), true)
    }
}

func expectEqual<T: Equatable>(_ actual: T, _ expected: T, file: StaticString = #file, line: UInt = #line) {
    guard actual == expected else { fatalError("Expected \(expected), received \(actual)", file: file, line: line) }
}

func expectThrows(_ expression: @autoclosure () throws -> Any, file: StaticString = #file, line: UInt = #line, inspect: (Error) -> Void = { _ in }) {
    do { _ = try expression() } catch { inspect(error); return }
    fatalError("Expected an error", file: file, line: line)
}

@main struct CoreChecks {
    static func main() async throws {
        let suite = CommandRunnerTests()
        let status = WorkingCopyStatusTests()
        let checks: [(String, () throws -> Void)] = [
            ("large stderr", suite.testLargeErrorOutputDoesNotBlockStandardOutput),
            ("XML diagnostics", suite.testWarningIsNotInsertedIntoXML),
            ("failure details", suite.testFailurePreservesExitCodeAndBothStreams),
            ("literal arguments", suite.testArgumentsAreNotEvaluatedByShell),
            ("UTF-8 environment and diagnostic isolation", suite.testUTF8EnvironmentAndErrorPresentation),
            ("working directory", suite.testWorkingDirectory),
            ("launch failure", suite.testMissingExecutableThrows),
            ("signed Python resources stay read-only", suite.testPythonChildrenDoNotRewriteSignedResources),
            ("property-only and mixed revisions", status.testPropertyOnlyChangeAndMixedRevisions),
            ("conflict metadata", status.testConflictAndCopiedMetadata),
            ("invalid status", status.testMalformedStatusFails),
            ("real SVN repository", status.testRealRepository)
        ]
        for (name, check) in checks { try check(); print("PASS: \(name)") }
        try await RepositoryQueryTests.run()
        try WorkspaceIndexTests.run()
        try await WorkbookComparisonTests.run()
        try UpdateRefreshTests.run()
        try CommitTargetsTests.run()
        try RevertScopeTests.run()
        try WorkbookExportScopeTests.run()
        print("Passed \(checks.count + 16) checks")
    }
}
