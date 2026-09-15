"""Exercise one-button staging and human review through the real Swift coordinator."""
import json
import pathlib
import subprocess
import tempfile
import unittest


class ReviewCoordinatorTests(unittest.TestCase):
    def test_staging_confirmation_and_recovery(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        import re
        backend = (root/'scripts/deletion_guard.py').read_text()
        version = int(re.search(r'^VERSION = (\d+)', backend, re.M)[1])
        source = (root/'Sources/SvnFlow/BranchSyncWindow.swift').read_text()
        self.assertIn(f'deletionGuardVersion == {version}', source)
        model = (root/'Sources/SvnFlow/SyncProgressView.swift').read_text().split('struct SyncProgressPanel: View')[0] + (root/'Sources/SvnFlow/BranchSyncWindow.swift').read_text().split('struct BranchSyncWindow: View')[0]
        model += (root/'Sources/SvnFlow/SyncScopeDraft.swift').read_text()
        model += (root/'Sources/SvnFlow/ComparisonReview.swift').read_text().split('/// Optional confirmation controls')[0]
        # The standalone coordinator also uses the app's notification names.
        notifications = (root/'Sources/SvnFlow/AppModel.swift').read_text().split('extension Notification.Name {', 1)[1].split('\n}', 1)[0]
        model += '\nextension Notification.Name {' + notifications + '\n}\n'
        model = model.replace('UserDefaults.standard', 'testDefaults').replace('Bundle.main.bundleURL.deletingLastPathComponent()', 'Bundle.main.resourceURL!')
        # Deliver the same broad invalidation caused by SVN's wc.db writes,
        # deterministically between successful writes in the real coordinator.
        model = model.replace('entries[path] = entry\n            blocked.remove(path)', '''if testDefaults.bool(forKey: "batchEvents"), let root = report?.config.target {
                releaseFilesChanged([(root + "/.svn/wc.db", 0)], root: root)
            }
            if batchAccepting {
                assert(writeBatch?.currentPath == path)
                assert(progress.total == writeBatch?.paths.count && progress.ended == nil)
                assert(progress.completed == writeBatch?.completed)
                let started = writeBatch?.started
                await confirmLowRisk()
                returnToWriteSelection()
                assert(writeBatch?.started == started, "repeated confirm and return cannot replace a live batch")
                if testDefaults.bool(forKey: "stopBatch") { requestStopWriting() }
            }
            entries[path] = entry
            blocked.remove(path)''')
        main = r'''
let testDefaults = UserDefaults(suiteName: "svnflow-review-test-" + UUID().uuidString)!
extension BranchSyncModel {
    func fixtureIgnore(_ path: String, revisions: [Int]?) { ignoredRevisions[path] = revisions }
    func recordFixturePublication(_ path: String) {
        exportRecords[path]?.publicationHash = "verified-test-receipt"
    }
}
@MainActor final class ComparisonReviewActions {
    var progress: SyncProgressModel?
    var targetPath = ""
    var resultSummary: () -> String = { "" }
    var confirmationHint = ""
    var withdrawnRows: [String: Set<Int>] = [:]
    var withdrawRow: ((String, Int) async throws -> String)?
    var loadTextReview: (() async throws -> TextReviewInfo)?
    var chooseText: ((String, Int) async throws -> String)?
    let accept: () async throws -> Void
    let skip: () async throws -> Void
    let next: () -> Void
    let pause: () -> Void
    init(title: String, summary: String, accept: @escaping () async throws -> Void, skip: @escaping () async throws -> Void, next: @escaping () -> Void, pause: @escaping () -> Void) {
        self.accept = accept; self.skip = skip; self.next = next; self.pause = pause
    }
}
@MainActor final class QueryWindows {
    static let shared = QueryWindows()
    var review: ComparisonReviewActions?
    var paths: [String] = []
    func compare(_ path: String) {}
    func compare(_ path: String, files: ComparisonFiles, review: ComparisonReviewActions? = nil) {
        paths.append(path); self.review = review
    }
}
@main struct Checks {
    @MainActor static func main() async throws {
        let model = BranchSyncModel()
        let scope = model.scopeDraft
        scope.choose(SyncScopeDraft.lua)
        assert(scope.contains("Client/Assets/Script/Lua/a.lua"))
        assert(!scope.contains("Client/Assets/Script/LuaExtra/a.lua"))
        scope.directories.insert("Client/Assets/Script/Lua/sub")
        assert(scope.normalizedDirectories == [SyncScopeDraft.lua])
        scope.choose(nil)
        assert(scope.contains("any/file"))
        scope.allDirectories = false; scope.directories = []
        assert(!scope.contains("any/file"))

        model.author = "fixture"; model.days = 30; model.filter = ""
        await model.autoLoad()
        assert(model.files.isEmpty, "opening must not contact SVN before explicit refresh")
        await model.applyScope(author: "fixture", days: 30)
        assert(model.uncheckedPaths.isEmpty, "new scope must automatically verify all ordinary files")
        let verificationLog = Bundle.main.resourceURL!.appendingPathComponent("verification-calls")
        let verifiedCalls = try String(contentsOf: verificationLog)
        await model.autoLoad()
        assert((try? String(contentsOf: verificationLog)) == verifiedCalls, "reopening a fully checked scope must reuse evidence")
        for file in model.files { await model.verifyRemaining(file.path) }
        assert(model.files.count == 4, "catalog failed: \(model.activity)")
        let cachedFolder = model.folder
        await model.autoLoad()
        assert(model.folder == cachedFolder, "opening the same scope must reuse its report")
        await model.refresh()
        assert(model.folder == cachedFolder && model.files.count == 4, "refresh must reuse the fixed round")
        // Batch ignore is persisted, reversible and does not call the SVN pipeline.
        model.selectedPaths = ["a", "b"]
        let callsBeforeIgnore = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        model.setIgnored(true)
        assert(model.skipped == ["a", "b"] && model.selectedPaths.isEmpty)
        model.selectRemaining()
        assert(model.selectedPaths == ["c"] && model.migrationPaths == ["c"])
        let ignoredRecovery = BranchSyncModel()
        assert(ignoredRecovery.skipped == ["a", "b"] && ignoredRecovery.selectedPaths == ["c"])
        let callsAfterIgnore = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(callsBeforeIgnore == callsAfterIgnore, "ignore must never write Release or call SVN")
        await model.refresh()
        assert(model.skipped == ["a", "b"], "unchanged revisions retain ignore on refresh")
        model.selectedPaths = ["a", "b"]
        model.busy = true; model.setIgnored(false)
        assert(model.skipped == ["a", "b"], "active operations must prevent ignore changes")
        model.busy = false; model.setIgnored(false)
        assert(model.skipped.isEmpty && model.ignoredRevisions.isEmpty)
        model.selectedPaths = []
        model.focusAndSelect("a")
        model.focusAndSelect("a")
        assert(model.selectedPaths == ["a"] && model.selection == "a")
        let selectedRecovery = BranchSyncModel()
        assert(selectedRecovery.selectedPaths == ["a"] && selectedRecovery.selection == "a")
        model.toggle("a", checked: false)
        try model.load()
        assert(model.selectedPaths.isEmpty)
        let emptyRecovery = BranchSyncModel()
        assert(emptyRecovery.selectedPaths.isEmpty, "explicitly cleared selection must stay empty on reopen")
        model.busy = true
        model.focusAndSelect("b")
        assert(model.selectedPaths.isEmpty, "viewing a row during an operation must not alter its batch")
        model.busy = false
        model.selectVisible()
        assert(model.migrationPaths == ["a", "b", "c"])
        assert(model.canMerge)
        // Verified no-op candidates disappear without deleting their report or ledger records.
        model.verifiedNoDiffPaths = ["a"]
        for state in ["ready", "accepted", "invalidated", "skipped"] {
            model.entries["a"] = try JSONDecoder().decode(SyncReviewEntry.self, from: Data("{\"path\":\"a\",\"status\":\"\(state)\",\"revision\":1,\"revisions\":[1],\"same\":true,\"summary\":\"no changes\"}".utf8))
            assert(model.files.count == 4 && model.listedFiles.count == 3 && model.hiddenNoDiffCount == 1)
            assert(!model.visibleFiles.contains { $0.path == "a" })
            model.selectRemaining()
            assert(!model.selectedPaths.contains("a"))
        }
        model.interrupted = true
        assert(model.listedFiles.count == 4, "unfinished writes remain visible")
        model.interrupted = false
        model.verifiedNoDiffPaths = []
        model.entries["a"] = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(#"{"path":"a","status":"ready","revision":1,"revisions":[2],"same":true,"summary":"stale"}"#.utf8))
        assert(model.listedFiles.count == 4, "new source revisions must be checked again")
        model.entries["a"] = nil
        model.selectVisible()
        let oldEntry = try JSONDecoder().decode(SyncReviewEntry.self, from: Data("{\"path\":\"a\",\"status\":\"ready\",\"revision\":1,\"same\":false,\"summary\":\"legacy\"}".utf8))
        assert(!oldEntry.canResume)
        for version in [1, 3] {
            let stale = try JSONDecoder().decode(SyncReviewEntry.self, from: Data("{\"path\":\"old.xlsx\",\"status\":\"ready\",\"revision\":1,\"same\":false,\"summary\":\"stale\",\"authorIsolation\":9,\"deletionGuardVersion\":\(version)}".utf8))
            assert(!stale.canResume, "old and unknown future rules must remain blocked")
        }
        await model.merge()
        assert(!model.busy && !model.reviewing)
        assert(model.queue.isEmpty && model.blocked == ["b"])
        assert(model.done.isEmpty && model.readyPaths == ["a", "c"])
        assert(model.workflowStatus("a") == "可确认" && model.workflowStatus("c") == "待核对")
        assert(model.workflowStatus("b") == "需要处理" && !model.isTemporarilyBlocked("b"))
        assert(model.workflowStatus("pmdata.bin") == "待导出")
        assert(model.statusCategory("a") == .review && model.statusCategory("c") == .review)
        assert(model.displayStage("a") == "低风险" && model.displayStage("c") == "待确认")
        assert(model.statusCategory("b") == .attention && model.statusCategory("pmdata.bin") == .pending)
        assert(model.displayStage("b") == "待确认" && model.displayStage("pmdata.bin") == "待确认")
        assert(model.matchesConfirmationFilter("a", filter: "低风险") && !model.matchesConfirmationFilter("a", filter: "待确认"))
        assert(model.matchesConfirmationFilter("b", filter: "待确认"))
        for old in ["待处理", "需处理", "待生成", "正在核验"] {
            assert(BranchSyncModel.migratedConfirmationFilter(old) == "待确认")
        }
        for unchanged in ["全部", "低风险", "待确认", "已完成", "已忽略"] {
            assert(BranchSyncModel.migratedConfirmationFilter(unchanged) == unchanged)
        }
        model.busy = true; model.action = "stage"; model.outputPath = "a"
        assert(model.displayStage("a") == "待确认" && model.executionStage("a") == "正在生成")
        model.busy = false; model.outputPath = nil


        assert(model.activity.contains("2 个副本可核对") && model.activity.contains("1 个需要处理"), "batch result must report actual failures")
        assert(QueryWindows.shared.paths.isEmpty, "whole batch must finish before human review")
        var calls = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(!calls.contains("accept"))
        assert(calls.contains("stage b") && calls.contains("stage c"))
        model.selectedPaths = ["c"]; model.setIgnored(true)
        assert(!model.isReady("c") && model.entries["c"]?.status == "ready", "ignore preserves generated candidates")
        try model.load()
        assert(model.skipped.contains("c") && !model.readyPaths.contains("c"))
        model.selectedPaths = ["c"]; model.setIgnored(false)
        assert(model.isReady("c"), "restore returns a pending candidate to review")
        assert(model.lowRiskPaths == ["a"] && model.selectedLowRiskPaths.isEmpty)
        assert(model.queueStatus("a") == "待确认" && !model.canGenerate("a"))
        model.toggle("a", checked: true); model.focusAndSelect("c")
        assert(model.selectedPaths.contains("a") && !model.selectedPaths.contains("c"), "ready files can be selected for ignore without regenerating")
        model.selectedPaths = ["a", "c"]
        let beforeRepeat = calls
        await model.merge()
        calls = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(calls == beforeRepeat, "pending files must not run catalog, assessment or staging again")
        model.reviewSelectedPaths = ["a"]
        model.filter = "c"
        assert(model.selectedLowRiskPaths.isEmpty, "hidden files must not enter bulk confirmation")
        model.filter = ""; model.reviewSelectedPaths = ["a", "c"]
        let pendingFolder = model.folder
        await model.refresh()
        assert(model.folder == pendingFolder && model.isReady("a"), "refresh preserves unchanged pending candidates")
        await model.confirmLowRisk()
        assert(model.done == ["a"] && model.isReady("c") && !model.batchAccepting)
        calls = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(calls.contains("accept-low a") && !calls.contains("accept-low c"))
        model.openReview(["c"])
        assert(model.reviewing && QueryWindows.shared.paths == ["c"])
        QueryWindows.shared.review!.pause()
        assert(!model.reviewing)
        model.openReview(["c"])
        do { try await QueryWindows.shared.review!.accept(); assertionFailure("expected write failure") } catch {}
        assert(model.interrupted && !model.canMerge)
        let recovered = BranchSyncModel()
        assert(recovered.interrupted && recovered.done == ["a"])
        assert(recovered.blocked == ["b", "c"] && recovered.readyPaths.isEmpty)
        assert(recovered.fileOutputs["c"]?.contains("fixture write failure") == true)
        let localEntry = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(#"{"path":"a","status":"ready","authorIsolation":9,"deletionGuardVersion":2,"revision":1,"same":false,"summary":"review","local":{"item":"modified","status":{"props":"normal"}}}"#.utf8))
        let matchingEntry = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(#"{"path":"b","status":"ready","authorIsolation":9,"deletionGuardVersion":2,"revision":1,"same":false,"summary":"review","candidateHash":"digest","properties":{},"local":{"hash":"digest","properties":{},"item":"modified","status":{"props":"normal"}}}"#.utf8))
        assert(matchingEntry.localMatchesCandidate && matchingEntry.preparationIssue == nil)
        var splitJSON = try JSONSerialization.jsonObject(with: Data(#"{"path":"split","status":"ready","authorIsolation":9,"deletionGuardVersion":2,"revision":1,"same":false,"summary":"review","candidate":"candidate","baseline":"baseline","candidateHash":"result","properties":{},"includesLocalChanges":true,"risk":{"version":1,"level":"low","reasons":[]},"local":{"hash":"original","properties":{},"item":"modified","status":{"props":"modified"}}}"#.utf8)) as! [String: Any]
        func splitEntry() throws -> SyncReviewEntry {
            try JSONDecoder().decode(SyncReviewEntry.self, from: JSONSerialization.data(withJSONObject: splitJSON))
        }
        let preserved = try splitEntry()
        assert(preserved.preservesLocalChanges && preserved.preparationIssue == nil && !preserved.lowRisk)
        assert(preserved.confirmationHint.contains("自动备份"))
        splitJSON["includesLocalChanges"] = false
        assert((try! splitEntry()).preparationIssue != nil)
        splitJSON["includesLocalChanges"] = true; splitJSON["authorIsolation"] = 8
        assert((try! splitEntry()).preparationIssue != nil)

        // A fresh recovery coordinator keeps unrelated pending and completed entries.
        let recovery = BranchSyncModel()
        recovery.folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        recovery.report = nil; recovery.entries = [:]; recovery.interrupted = false
        recovery.author = "fixture"; recovery.days = 30; recovery.filter = ""
        await recovery.applyScope(author: "fixture", days: 30)
        for file in recovery.files { await recovery.verifyRemaining(file.path) }
        recovery.selectVisible(); await recovery.merge()
        assert(recovery.blocked == ["b"] && recovery.readyPaths == ["a", "c"])
        // Read real persisted failures so display and routing use the same source after restart.
        let workflowFailures = #"{"a":"作者隔离规则已更新，请重新生成并核对；旧副本已保留。","b":"Release 有其他合入任务正在运行，请稍后再试","c":"ValueError: 第 130 行缺少配置 ID；实际变化位置 U130, V130，无法匹配 Release 记录；未按行号覆盖"}"#
        try Data(workflowFailures.utf8).write(to: recovery.folder.appendingPathComponent("review-failures.json"))
        try recovery.load()
        assert(recovery.entries["a"]?.canResume == true && recovery.isReady("a"), "valid v2 candidate must recover from the persisted false version warning")
        assert(recovery.workflowStatus("b") == "暂时受阻" && recovery.isTemporarilyBlocked("b"))
        assert(recovery.workflowStatus("c") == "需要处理" && !recovery.isTemporarilyBlocked("c"))
        assert(recovery.entries["c"]?.status == "ready" && !recovery.isReady("c"), "failed ready candidates must appear only as needing attention")
        assert(recovery.shortReason("c").contains("130") && recovery.shortReason("c").contains("U130"), "row and changed cells must remain visible")
        assert(recovery.nextStep("b") == "重试生成" && recovery.nextStep("c") == "查看原因与处理")
        recovery.selectedPaths = ["b", "c"]
        assert(recovery.migrationPaths.isEmpty && !recovery.canMerge, "ordinary generation must never silently retry failed files")
        let beforeFailureRouting = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        await recovery.merge()
        let afterFailureRouting = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(beforeFailureRouting == afterFailureRouting)
        recovery.skipped.insert("b")
        assert(recovery.workflowStatus("b") == "已忽略" && !recovery.isTemporarilyBlocked("b"), "ignored files cannot remain in retry state")
        recovery.skipped.remove("b"); recovery.done.insert("b")
        assert(recovery.workflowStatus("b") == "已写入本地" && !recovery.isTemporarilyBlocked("b"), "local completion must not be labelled repository merged")
        recovery.done.remove("b")
        await recovery.retryTemporarilyBlocked(["b", "c"])
        let afterAutomaticRetry = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        let retryCalls = String(afterAutomaticRetry.dropFirst(afterFailureRouting.count))
        assert(retryCalls.contains("regenerate b") && !retryCalls.contains("stage c") && !retryCalls.contains("accept"), "retry group must only stage temporary failures and never write candidates")
        assert(recovery.workflowStatus("b") == "需要处理", "a new content failure must replace the old temporary status")
        assert(recovery.failureReason("c").contains("U130") && recovery.isReady("a"), "retry must preserve unrelated errors and pending candidates")
        assert(recovery.selectedPaths == ["b", "c"], "retry preserves batch selection for follow-up")
        try Data(#"{"b":"fixture cannot isolate file"}"#.utf8).write(to: recovery.folder.appendingPathComponent("review-failures.json"))
        try recovery.load()
        await recovery.retry("b")
        assert(recovery.blocked == ["b"] && recovery.readyPaths == ["a", "c"], "retry must preserve other pending candidates")
        recovery.blocked.insert("a")
        await recovery.retry("a")
        assert(recovery.isReady("a") && recovery.isReady("c"), "explicit recovery rebuilds only the blocked candidate")
        recovery.blocked.insert("a")
        await recovery.skipBlocked("a")
        assert(recovery.skipped == ["a"] && !recovery.blocked.contains("a"))
        assert(recovery.queueStatus("a") == "已忽略" && !recovery.canGenerate("a"))
        recovery.toggle("a", checked: true); recovery.focusAndSelect("a")
        assert(!recovery.selectedPaths.contains("a"))
        let recoveredSelection = BranchSyncModel()
        assert(recoveredSelection.skipped == ["a"] && !recoveredSelection.selectedPaths.contains("a"))
        recovery.selectedPaths = ["a", "c"]
        let beforeHandled = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        await recovery.merge()
        let afterHandled = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(afterHandled == beforeHandled)
        model.interrupted = false; model.reviewing = false; model.done = []; model.entries = [:]
        let item: (String) -> SyncReport.FileItem = { .init(path: $0, kind: "file", revisions: [1], latestRevision: 1, message: "", date: "") }
        model.report = SyncReport(dev: model.report!.dev, config: model.report!.config, fileItems: ["book.XLSX", "data.lua", "pmdata.bin"].map(item), directoryChangeCount: 0)
        model.repositoryStates = Dictionary(uniqueKeysWithValues: model.files.map { ($0.path, "different") })
        model.selectedPaths = ["book.XLSX", "data.lua", "pmdata.bin"]
        model.typeFilter = "xlsx"
        assert(model.migrationPaths == ["book.XLSX", "data.lua"], "type filters preserve the explicit selected batch")
        model.typeFilter = ""; model.selectedPaths = ["pmdata.bin"]
        assert(!model.canMerge)
        model.skipped = []; model.blocked = []; model.selectedPaths = []
        model.report = SyncReport(dev: nil, config: model.report!.config,
            fileItems: ["Client/a.lua", "Client/Sub/b.lua", "ClientExtra/c.lua", "root.txt"].map(item), directoryChangeCount: 0)
        model.repositoryStates = Dictionary(uniqueKeysWithValues: model.files.map { ($0.path, "different") })
        model.directory = "Client"
        assert(model.visibleFiles.map(\.path) == ["Client/a.lua", "Client/Sub/b.lua"], "directories include descendants but not sibling prefixes")
        model.selectVisible(); model.directory = "ClientExtra"
        assert(model.selectedPaths == ["Client/a.lua", "Client/Sub/b.lua"], "directory navigation preserves hidden selections")
        model.selectedPaths.formUnion(model.visibleFiles.map(\.path))
        model.filter = "absent"
        assert(model.migrationPaths.count == 3 && model.visibleFiles.isEmpty)
        let tree = SyncDirectoryNode.build(model.files)
        assert(tree.map(\.id) == ["Client", "ClientExtra"] && tree[0].count == 2)
        assert(tree[0].children?.first?.id == "Client/Sub")
        assert(tree.compactMap { $0.matching("Sub") }.first?.children?.first?.id == "Client/Sub")
        model.directory = ""; model.filter = ""
        // Refresh retains completed and failed records only for unchanged author revisions.
        let refreshModel = BranchSyncModel()
        refreshModel.folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        refreshModel.report = nil; refreshModel.entries = [:]; refreshModel.interrupted = false
        refreshModel.author = "fixture"; refreshModel.days = 30; refreshModel.filter = ""
        await refreshModel.applyScope(author: "fixture", days: 30)
        for file in refreshModel.files { await refreshModel.verifyRemaining(file.path) }
        let ledger = #"{"items":{"a":{"path":"a","status":"accepted","revision":1,"same":true,"summary":"done"},"b":{"path":"b","status":"skipped","revision":1,"same":false,"summary":"skip"}}}"#
        try Data(ledger.utf8).write(to: refreshModel.folder.appendingPathComponent("review.json"))
        try Data(#"{"c":"fixture failure"}"#.utf8).write(to: refreshModel.folder.appendingPathComponent("review-failures.json"))
        try refreshModel.load()
        for file in refreshModel.files { await refreshModel.verifyRemaining(file.path) }
        await refreshModel.refresh()
        assert(refreshModel.done == ["a"] && refreshModel.skipped == ["b"] && refreshModel.blocked == ["c"])
        refreshModel.selectVisible()
        assert(refreshModel.selectedPaths == ["c"], "select all excludes synced, ignored and pmdata files")
        refreshModel.toggle("a", checked: true); refreshModel.toggle("b", checked: true)
        assert(refreshModel.selectedPaths == ["c"])
        await refreshModel.merge()
        assert(refreshModel.done == ["a"] && refreshModel.skipped == ["b"], "new batches retain completed records")
        await refreshModel.skipBlocked("c")
        refreshModel.selectedPaths = ["pmdata.bin"]; refreshModel.setIgnored(true)
        assert(refreshModel.skipped.contains("pmdata.bin"))
        // Pending candidates do not lock refresh; unchanged candidates survive in a new batch.
        let pendingLedger = #"{"items":{"a":{"path":"a","status":"accepted","revision":1,"same":true,"summary":"done"},"c":{"path":"c","status":"ready","authorIsolation":9,"deletionGuardVersion":2,"revision":1,"candidate":"candidate","baseline":"baseline","same":false,"summary":"pending"}}}"#
        try Data(pendingLedger.utf8).write(to: refreshModel.folder.appendingPathComponent("review.json"))
        try refreshModel.load()
        assert(refreshModel.hasPendingReview && refreshModel.canRefresh)
        refreshModel.reviewing = true
        assert(!refreshModel.canRefresh, "active review must prevent batch replacement")
        refreshModel.reviewing = false
        let preservedPendingFolder = refreshModel.folder
        await refreshModel.refresh()
        assert(refreshModel.folder == preservedPendingFolder && refreshModel.entries["c"]?.status == "ready")
        assert(refreshModel.done == ["a"])
        let preservedLedger = try String(contentsOf: preservedPendingFolder.appendingPathComponent("review.json"), encoding: .utf8)
        assert(preservedLedger == pendingLedger, "refresh must not modify the original candidate batch")
        let fixtureURL = Bundle.main.resourceURL!.appendingPathComponent("fixture.json")
        var fixture = try JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as! [String: Any]
        var fixtureItems = fixture["fileItems"] as! [[String: Any]]
        for i in fixtureItems.indices { fixtureItems[i]["revisions"] = [1, 2]; fixtureItems[i]["latestRevision"] = 2 }
        fixture["fileItems"] = fixtureItems
        try JSONSerialization.data(withJSONObject: fixture).write(to: fixtureURL)
        await refreshModel.applyScope(author: "fixture", days: 30)
        assert(refreshModel.done.isEmpty && refreshModel.skipped.isEmpty && refreshModel.blocked.isEmpty && refreshModel.entries.isEmpty, "new author revisions must be reviewed again")
        let beforeFailure = refreshModel.folder
        try Data("invalid".utf8).write(to: fixtureURL)
        await refreshModel.applyScope(author: "fixture", days: 30)
        assert(refreshModel.folder == beforeFailure && refreshModel.files.count == 4 && !refreshModel.busy, "failed refresh must preserve the current report")
        // Exported Lua rules skip generation before any subprocess or SVN read.
        let workflow = BranchSyncModel()
        let config = refreshModel.report!.config
        let ruleFiles = ["Generated/table.lua", "Generated/sub/t.LUA", "GeneratedExtra/code.lua", "Scripts/game.lua", "Config/table.xlsx"].map(item)
        workflow.report = SyncReport(dev: nil, config: config, fileItems: ruleFiles, directoryChangeCount: 0)
        workflow.repositoryStates = Dictionary(uniqueKeysWithValues: workflow.files.map { ($0.path, "different") })
        workflow.entries = [:]; workflow.done = []; workflow.skipped = []; workflow.blocked = []
        workflow.interrupted = false; workflow.reviewing = false; workflow.filter = ""; workflow.typeFilter = ""
        workflow.saveLuaDirectories("Generated")
        assert(workflow.skipped == ["Generated/table.lua", "Generated/sub/t.LUA"])
        assert(workflow.canGenerate("GeneratedExtra/code.lua") && workflow.canGenerate("Scripts/game.lua"))
        workflow.selectedPaths = ["Generated/table.lua"]
        let callsBeforeRules = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        await workflow.merge()
        workflow.queue = ["Generated/table.lua"]; await workflow.prepareNext()
        let callsAfterRules = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(callsBeforeRules == callsAfterRules, "ignored Lua must cause zero generation commands")
        workflow.selectedPaths = ["Generated/table.lua"]; workflow.setIgnored(false)
        assert(workflow.canGenerate("Generated/table.lua") && !workflow.canGenerate("Generated/sub/t.LUA"))
        workflow.saveLuaDirectories("/absolute/path")
        assert(workflow.luaDirectories == ["Generated"], "invalid absolute paths must not replace saved rules")
        var ruleReport = try JSONSerialization.jsonObject(with: Data(contentsOf: workflow.folder.appendingPathComponent("report.json"))) as! [String: Any]
        ruleReport["fileItems"] = ruleFiles.map { ["path": $0.path, "kind": "file", "revisions": [1], "latestRevision": 1, "message": "", "date": ""] as [String: Any] }
        try JSONSerialization.data(withJSONObject: ruleReport).write(to: workflow.folder.appendingPathComponent("report.json"))
        let workflowRestored = BranchSyncModel()
        assert(workflowRestored.luaDirectories == ["Generated"])
        assert(!workflowRestored.skipped.contains("Generated/table.lua") && workflowRestored.skipped.contains("Generated/sub/t.LUA"), "rules and per-version exceptions survive restart")
        workflow.saveLuaDirectories("")
        assert(workflow.skipped.isEmpty, "removing a directory rule restores its files")
        let excel = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(#"{"path":"Config/table.xlsx","status":"accepted","revision":1,"same":false,"candidate":"batch-1/table.xlsx","summary":"written"}"#.utf8))
        workflow.repositoryStates = Dictionary(uniqueKeysWithValues: workflow.files.map { ($0.path, "different") })
        workflow.entries = [excel.path: excel]; workflow.done = [excel.path]
        workflow.recordAcceptedExcel()
        assert(workflow.pendingExports == [excel.path] && workflow.exportChecklist.contains(excel.path))
        assert(workflow.workflowStatus(excel.path) == "待导出" && workflow.nextStep(excel.path) == "查看 xtools 清单")
        workflow.setExportCompleted(excel.path, completed: true)
        workflow.recordAcceptedExcel()
        assert(workflow.pendingExports == [excel.path], "legacy manual checkmarks are not machine publication proof")
        workflow.recordFixturePublication(excel.path)
        workflow.recordAcceptedExcel()
        assert(workflow.pendingExports.isEmpty, "loading the same accepted batch must not reset export confirmation")
        assert(workflow.workflowStatus(excel.path) == "已写入本地")
        let nextExcel = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(#"{"path":"Config/table.xlsx","status":"accepted","revision":2,"same":false,"candidate":"batch-2/table.xlsx","summary":"written"}"#.utf8))
        workflow.repositoryStates = Dictionary(uniqueKeysWithValues: workflow.files.map { ($0.path, "different") })
        workflow.entries = [nextExcel.path: nextExcel]; workflow.recordAcceptedExcel()
        assert(workflow.pendingExports == [excel.path], "a new merge requires a fresh export")
        // Cancel an actual blocked child through the production Swift coordinator.
        let cancelled = BranchSyncModel()
        cancelled.folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: cancelled.folder, withIntermediateDirectories: true)
        cancelled.report = SyncReport(dev: nil, config: workflow.report!.config,
            fileItems: ["slow.lua", "after.lua"].map(item), directoryChangeCount: 0)
        cancelled.repositoryStates = ["slow.lua": "different", "after.lua": "different"]
        cancelled.entries = [:]; cancelled.done = []; cancelled.skipped = []; cancelled.blocked = []
        cancelled.interrupted = false; cancelled.filter = ""; cancelled.typeFilter = ""; cancelled.directory = ""
        cancelled.selectedPaths = ["slow.lua", "after.lua"]; cancelled.queue = ["slow.lua", "after.lua"]
        try Data(#"{"items":{}}"#.utf8).write(to: cancelled.folder.appendingPathComponent("review.json"))
        let generation = Task { await cancelled.prepareNext() }
        let ready = Bundle.main.resourceURL!.appendingPathComponent("slow-ready")
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: ready.path) { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        assert(cancelled.busy && FileManager.default.fileExists(atPath: ready.path))
        let cancellationStart = Date()
        cancelled.cancelGeneration()
        await generation.value
        assert(Date().timeIntervalSince(cancellationStart) < 3)
        assert(!cancelled.busy && cancelled.queue.isEmpty && cancelled.blocked.isEmpty)
        let finalCalls = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
        assert(!finalCalls.contains("stage after.lua"), "cancelled batches must never advance")
        let progress = SyncProgressModel()
        progress.beginBatch(total: 2)
        progress.watch(folder: cancelled.folder, token: "one", action: "stage", path: nil)
        progress.cancelGeneration()
        progress.watch(folder: cancelled.folder, token: "two", action: "stage", path: nil)
        assert(progress.cancelling && FileManager.default.fileExists(atPath: cancelled.folder.appendingPathComponent("cancel-two").path))
        progress.finish(); progress.beginBatch(total: 1)
        assert(!progress.cancelling, "a new user-started batch can proceed")
        let evidence = BranchSyncModel()
        let ep = evidence.files.first { $0.path != "pmdata.bin" }!.path
        let digest = SHA256.hash(data: try Data(contentsOf: evidence.folder.appendingPathComponent("report.json"))).map { String(format: "%02x", $0) }.joined()
        evidence.repositoryStates = [:]; evidence.verifiedNoDiffPaths = []
        assert(evidence.workflowStatus(ep) == "待核验" && !evidence.canSelect(ep))
        assert(!evidence.listedFiles.contains { $0.path == ep }, "unverified files must not appear in the actionable list")
        assert(evidence.hiddenNoDiffCount == 0, "unknown files must not be counted as no difference")
        assert(evidence.nextStep(ep) == "核验此文件" && evidence.statusCategory(ep) == .pending)
        evidence.skipped.insert(ep)
        assert(evidence.statusCategory(ep) == .ignored && evidence.displayStage(ep) == "已忽略")
        evidence.fixtureIgnore(ep, revisions: evidence.files.first(where: { $0.path == ep })!.revisions)
        assert(!evidence.canSelect(ep) && !evidence.canGenerate(ep))
        evidence.fixtureIgnore(ep, revisions: nil)

        evidence.skipped.remove(ep)

        evidence.remainingCheckFailed = true
        assert(evidence.workflowStatus(ep) == "无法确认")
        assert(evidence.listedFiles.contains { $0.path == ep }, "verification failure stays actionable rather than appearing equal")
        evidence.remainingCheckFailed = false
        evidence.applyRemaining(RemainingDiffResult(snapshot: 9, noDiffPaths: [ep], differentPaths: [], errors: [:], localIssues: [ep: "本地待更新"], reportDigest: digest, complete: false))
        assert(evidence.workflowStatus(ep) == "已合入 · 本地需处理")
        assert(evidence.listedFiles.contains { $0.path == ep } && !evidence.canSelect(ep))
        evidence.applyRemaining(RemainingDiffResult(snapshot: 9, noDiffPaths: [ep], differentPaths: [], errors: [:], localIssues: [:], reportDigest: digest, complete: false))
        assert(!evidence.listedFiles.contains { $0.path == ep }, "completed files disappear without waiting for the batch")
        evidence.applyRemaining(RemainingDiffResult(snapshot: 10, noDiffPaths: [], differentPaths: [ep], errors: [:], reportDigest: "wrong-report"))
        assert(evidence.repositoryStates[ep] == "same", "another scope cannot overwrite evidence")
        evidence.blocked.insert(ep)
        evidence.applyRemaining(RemainingDiffResult(snapshot: 10, noDiffPaths: [], differentPaths: [ep], errors: [:], localStates: [ep: "same"], localIssues: [:], reportDigest: digest))
        assert(!evidence.blocked.contains(ep), "fresh equality supersedes historical preparation failures")
        assert(!evidence.listedFiles.contains { $0.path == ep }, "local equality is removed from the list without an SVN commit")
        assert(evidence.workflowStatus(ep) == "已写入本地", "external local merge must not be blocked by repository delta")
        assert(!evidence.canGenerate(ep) && !evidence.canSelect(ep))
        assert(evidence.statusCategory(ep) == .completed)
        evidence.applyRemaining(RemainingDiffResult(snapshot: 10, noDiffPaths: [], differentPaths: [ep], errors: [:], localStates: [ep: "different"], localIssues: [:], reportDigest: digest))
        assert(!evidence.localContainsChanges(ep), "local revert removes completion evidence")
        assert(evidence.listedFiles.contains { $0.path == ep }, "changed content becomes pending again")
        let savedEvidence: [String: Any] = ["snapshot": 9, "noDiffPaths": [ep], "differentPaths": [], "errors": [String: String](), "localIssues": [String: String](), "reportDigest": digest, "complete": false]
        try JSONSerialization.data(withJSONObject: savedEvidence).write(to: evidence.folder.appendingPathComponent("remaining-last.json"))
        try evidence.load()
        assert(evidence.repositoryStates[ep] == "same" && !evidence.listedFiles.contains { $0.path == ep }, "partial results survive reopen")
        evidence.author = evidence.report!.config.author
        evidence.days = evidence.report!.config.days ?? 30
        let targetRoot = evidence.report!.config.target
        evidence.localStates[ep] = "same"
        evidence.busy = true
        let callsBeforeChange = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"))
        evidence.releaseFilesChanged([(targetRoot + "/" + ep, 0)], root: targetRoot)
        assert(!evidence.localContainsChanges(ep) && !evidence.canGenerate(ep), "disk event invalidates completion immediately")
        try await Task.sleep(for: .milliseconds(1200))
        let callsWhileBusy = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"))
        assert(callsWhileBusy == callsBeforeChange, "busy task must defer synchronization")
        evidence.busy = false
        try await Task.sleep(for: .milliseconds(500))
        assert(evidence.repositoryStates[ep] == nil && !evidence.busy, "disk events must not silently start remote verification")
        let callsAfterChange = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"))
        assert(callsAfterChange == callsBeforeChange)
        // A local write also touches wc.db: invalidate permission, not list membership.
        let remainingPaths = evidence.files.filter { $0.path != "pmdata.bin" }.map(\.path)
        evidence.applyRemaining(RemainingDiffResult(snapshot: 10, noDiffPaths: [], differentPaths: remainingPaths, errors: [:], localStates: [:], localIssues: [:], reportDigest: digest))
        evidence.releaseFilesChanged([(targetRoot + "/.svn/wc.db", 0)], root: targetRoot)
        assert(Set(evidence.listedFiles.map(\.path)).isSuperset(of: remainingPaths), "wc.db event must not empty the remaining list")
        assert(remainingPaths.allSatisfy { evidence.workflowStatus($0) == "待核验" && !evidence.canGenerate($0) && !evidence.isReady($0) }, "retained rows cannot authorize stale writes")
        evidence.releaseFilesChanged([(targetRoot, 0)], root: targetRoot)
        try evidence.load()
        assert(Set(evidence.listedFiles.map(\.path)).isSuperset(of: remainingPaths), "repeated events and reload preserve remaining rows")
        evidence.applyRemaining(RemainingDiffResult(snapshot: 11, noDiffPaths: [ep], differentPaths: [], errors: [:], localStates: [:], localIssues: [:], reportDigest: digest))
        assert(!evidence.listedFiles.contains { $0.path == ep }, "fresh equality can still hide the one completed file")
        assert(Set(evidence.listedFiles.map(\.path)).isSuperset(of: remainingPaths.filter { $0 != ep }), "single-file verification preserves other pending rows")
        let batch = BranchSyncModel()
        let batchPaths = (0..<70).map { String(format: "batch-%03d", $0) }
        let batchFolder = Bundle.main.resourceURL!.appendingPathComponent("batch-fixture")
        try FileManager.default.createDirectory(at: batchFolder, withIntermediateDirectories: true)
        var batchReport: [String: Any] = ["config": ["dev": "fake", "release": "fake", "target": Bundle.main.resourceURL!.path, "author": "fixture", "start": "", "end": "", "snapshot": 1, "days": 30]]
        batchReport["fileItems"] = batchPaths.map { ["path": $0, "kind": "file", "revisions": [1], "latestRevision": 1, "message": "", "date": ""] as [String: Any] }
        try JSONSerialization.data(withJSONObject: batchReport).write(to: batchFolder.appendingPathComponent("report.json"))
        let batchEntries = Dictionary(uniqueKeysWithValues: batchPaths.map { path in
            (path, ["path": path, "status": "ready", "authorIsolation": 9, "deletionGuardVersion": 2, "revision": 1, "same": false, "summary": "batch", "risk": ["version": 1, "level": "low", "reasons": []]] as [String: Any])
        })
        try JSONSerialization.data(withJSONObject: ["items": batchEntries]).write(to: batchFolder.appendingPathComponent("review.json"))
        batch.folder = batchFolder; batch.filter = ""; batch.typeFilter = ""
        try batch.load()
        batch.repositoryStates = Dictionary(uniqueKeysWithValues: batchPaths.map { ($0, "different") })
        batch.reviewSelectedPaths = Set(batchPaths)
        assert(batch.selectedLowRiskPaths == batchPaths)
        testDefaults.set(true, forKey: "batchEvents")
        await batch.confirmLowRisk()
        testDefaults.set(false, forKey: "batchEvents")
        assert(batchPaths.allSatisfy { batch.entries[$0]?.status == "accepted" }, "SVN notifications must not terminate the confirmed queue")
        let batchCalls = try String(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("calls"), encoding: .utf8)
            .split(separator: "\n").filter { $0.hasPrefix("accept-low batch-") }.map(String.init)
        assert(batchCalls == batchPaths.map { "accept-low " + $0 }, "one click writes every selected file exactly once, in order")
        assert(!batch.batchAccepting && !batch.busy && batch.reviewSelectedPaths.isEmpty)
        assert(batch.writeBatch?.state == .completed && batch.writeBatch?.completed == 70)
        assert(batch.progress.total == 70 && batch.progress.completed == 70 && batch.progress.ended != nil)
        assert(batch.writeBatch?.unstarted == 0 && batch.writeBatch?.currentPath == nil)
        let completedBatchStart = batch.writeBatch?.started
        await batch.confirmLowRisk() // Empty selection leaves the completed result intact.
        assert(batch.writeBatch?.started == completedBatchStart)

        @MainActor func resetBatch() throws -> BranchSyncModel {
            try JSONSerialization.data(withJSONObject: ["items": batchEntries]).write(to: batchFolder.appendingPathComponent("review.json"))
            try? FileManager.default.removeItem(at: batchFolder.appendingPathComponent("review-failures.json"))
            let value = BranchSyncModel(); value.folder = batchFolder; value.filter = ""; value.typeFilter = ""
            try value.load(repair: false)
            value.repositoryStates = Dictionary(uniqueKeysWithValues: batchPaths.map { ($0, "different") })
            value.reviewSelectedPaths = Set(batchPaths)
            return value
        }
        let stopped = try resetBatch()
        testDefaults.set(true, forKey: "stopBatch")
        testDefaults.set(true, forKey: "batchEvents")
        await stopped.confirmLowRisk()
        testDefaults.set(false, forKey: "stopBatch")
        testDefaults.set(false, forKey: "batchEvents")
        assert(stopped.writeBatch?.state == .stopped && stopped.writeBatch?.completed == 1)
        assert(stopped.writeBatch?.unstarted == 69 && stopped.entries[batchPaths[1]]?.status == "ready")
        assert(!stopped.batchAccepting && !stopped.busy && stopped.progress.ended != nil)
        // Result ownership lives in the model, independent of panel presentation.
        stopped.returnToWriteSelection()
        assert(stopped.writeBatch == nil && stopped.reviewSelectedPaths.count == 69)
        assert(stopped.selectedLowRiskPaths.count == 69, "return to selection retains the unstarted queue despite write notifications")

        let failMarker = Bundle.main.resourceURL!.appendingPathComponent("fail-batch-path")
        for index in [0, 1] {
            let failed = try resetBatch()
            try batchPaths[index].write(to: failMarker, atomically: true, encoding: .utf8)
            await failed.confirmLowRisk()
            assert(failed.writeBatch?.state == .failed && failed.writeBatch?.completed == index)
            assert(failed.writeBatch?.failedPath == batchPaths[index] && failed.writeBatch?.failures == 1)
            assert(failed.writeBatch?.unstarted == 69 - index)
            assert(failed.entries[batchPaths[index+1]]?.status == "ready")
            assert(failed.activity.contains("受阻") && !failed.activity.contains("完成 70"))
        }
        try? FileManager.default.removeItem(at: failMarker)
        let interruptedBatch = try resetBatch()
        let pendingMarker = Bundle.main.resourceURL!.appendingPathComponent("pending-batch")
        try Data().write(to: pendingMarker)
        await interruptedBatch.confirmLowRisk()
        assert(interruptedBatch.writeBatch?.state == .interrupted && interruptedBatch.interrupted)
        assert(interruptedBatch.writeBatch?.completed == 0 && interruptedBatch.writeBatch?.unstarted == 69)
        interruptedBatch.returnToWriteSelection()
        assert(interruptedBatch.writeBatch != nil && !interruptedBatch.canChangeBatch)
        try? FileManager.default.removeItem(at: pendingMarker)
        print("PASS: 70 sequential writes, stable progress, duplicate prevention, safe stop, first/middle failure and interrupted-write protection")
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='svnflow-review-model-') as folder:
            folder = pathlib.Path(folder)
            (folder/'main.swift').write_text(model+main)
            (folder/'sync_progress.py').write_bytes((root/'scripts/sync_progress.py').read_bytes())
            (folder/'branch_sync.py').write_text(r'''import json,pathlib,sys
args=sys.argv; root=pathlib.Path(__file__).parent
folder=pathlib.Path(args[args.index('--folder')+1]); action=args[1]
path=args[args.index('--path')+1] if '--path' in args else ''
if action in ('remaining-diff','repair-review'):
 if action=='remaining-diff':
  with (root/'verification-calls').open('a') as verification_log: verification_log.write(' '.join(args[1:])+'\n')
 import hashlib
 report=json.loads((folder/'report.json').read_text())
 ledger=json.loads((folder/'review.json').read_text()) if (folder/'review.json').exists() else {'items':{}}
 same=[p for p,e in ledger['items'].items() if e.get('status')=='accepted' and e.get('same') is True]
 result=dict(snapshot=1,noDiffPaths=same,differentPaths=[f['path'] for f in report['fileItems'] if f['path']!='pmdata.bin' and f['path'] not in same],errors={},localIssues={},reportDigest=hashlib.sha256((folder/'report.json').read_bytes()).hexdigest(),complete=True)
 saved=folder/'remaining-last.json'
 if action=='repair-review' and not saved.exists():
  print('[]'); sys.exit(0)
 if action=='repair-review' and saved.exists():
  previous=json.loads(saved.read_text())
  if previous.get('reportDigest')==result['reportDigest']: result=previous
 saved.write_text(json.dumps(result))
 print(json.dumps(result) if action=='remaining-diff' else '[]'); sys.exit(0)  # Local recovery is tested against real files separately.
with (root/'calls').open('a') as log: log.write(action+' '+path+'\n')
if action=='stage' and path=='slow.lua':
 import time
 (root/'slow-ready').touch(); time.sleep(60)
if action=='prefetch': print('{}'); sys.exit(0)
if action=='catalog':
 folder.mkdir(parents=True,exist_ok=True)
 (folder/'report.json').write_bytes((root/'fixture.json').read_bytes())
 (folder/'review.json').write_text(json.dumps(dict(items={})))
else:
 state=json.loads((folder/'review.json').read_text())
 if action in ('stage','regenerate'):
  if action=='regenerate': state['items'].pop(path,None)
  if path in state['items']: sys.exit('existing candidate must be preserved')
  if path=='b': sys.exit('fixture cannot isolate file')
  entry=dict(path=path,status='ready',authorIsolation=9,deletionGuardVersion=2,revision=1,candidate='candidate',baseline='baseline',same=False,summary='review me',risk=dict(version=1,level='low' if path=='a' else 'high',reasons=['fixture']))
  state['items'][path]=entry
 elif action=='defer':
  entry=state['items'][path]; entry['status']='skipped'
 elif action in ('accept','accept-low'):
  marker=root/'fail-batch-path'
  if marker.exists() and marker.read_text()==path: sys.exit('fixture preflight failure')
  if path=='c' or (root/'pending-batch').exists():
   state['pending']=path
   (folder/'review.json').write_text(json.dumps(state))
   sys.exit('fixture write failure')
  entry=state['items'][path]; entry['status']='accepted'
 (folder/'review.json').write_text(json.dumps(state))
 print(json.dumps(entry))
''')
            (folder/'fixture.json').write_text(json.dumps({'config':dict(dev='fake',release='fake',target=str(folder),author='fixture',start='',end='',snapshot=1,days=30),'fileItems':[dict(path=p,kind='file',revisions=[1],latestRevision=1,message='',date='') for p in ['a','b','c','pmdata.bin']]}))
            objects = list((root/'.build/release/SVNCore.build').glob('*.swift.o'))
            compilation = subprocess.run(['swiftc','-parse-as-library','-I',str(root/'.build/release/Modules'),str(folder/'main.swift'),str(root/'Sources/SvnFlow/WorkspaceMonitor.swift'),*map(str,objects),'-o',str(folder/'checks')],capture_output=True,text=True)
            self.assertEqual(compilation.returncode, 0, compilation.stderr)
            result = subprocess.run([str(folder/'checks')],capture_output=True,text=True)
            if result.returncode:
                import re
                for line in re.findall(r'main.swift:(\d+)', result.stderr):
                    n = int(line)
                    print('Failing Swift assertion:', (model+main).splitlines()[n-1])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout)
