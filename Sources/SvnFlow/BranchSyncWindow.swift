import AppKit
import SwiftUI
import SVNCore
import CryptoKit

enum SyncMergeType: String, CaseIterable, Identifiable {
    case excel, lua, project, text, binary, pmdata
    var id: String { rawValue }
    static func classify(_ path: String) -> Self {
        if (path as NSString).lastPathComponent.lowercased() == "pmdata.bin" { return .pmdata }
        switch (path as NSString).pathExtension.lowercased() {
        case "xlsx", "xlsm": return .excel
        case "lua": return .lua
        case "asset", "prefab", "unity", "meta", "mat", "controller", "anim", "overridecontroller", "shader", "cs", "compute", "cginc": return .project
        case "xls", "bin", "bytes", "png", "jpg", "jpeg", "zip", "dll", "exe", "pdf", "fbx", "psd", "tga", "wav", "mp3", "mp4", "7z": return .binary
        default: return .text
        }
    }
    var title: String {
        switch self {
        case .excel: return "Excel 表格"
        case .lua: return "Lua 数据"
        case .project: return "工程文件"
        case .text: return "其他文本"
        case .binary: return "二进制文件"
        case .pmdata: return "pmdata"
        }
    }
    var symbol: String { self == .excel ? "tablecells" : self == .lua ? "curlybraces" : self == .project ? "hammer" : self == .binary ? "doc.zipper" : self == .pmdata ? "arrow.clockwise" : "doc.text" }
    var supportsConflictChoice: Bool { self != .binary && self != .pmdata }
    var function: String {
        switch self {
        case .excel: return "按单元格与工作表合并"
        case .lua: return "按表键与字段合并"
        case .project: return "按文本行与改动片段合并"
        case .text: return "文本差异合并与编码检查"
        case .binary: return "文件一致性与可隔离性检查"
        case .pmdata: return "在 Release 使用 xtools 重新导出"
        }
    }
    var explanation: String {
        switch self {
        case .excel: return "公式转值先使用 Release 自身已保存的计算结果，再合并数值与样式改动；整页转值同步处理对应工作表。"
        case .lua: return "数据表按键合并，保留 Release 独有字段；非数据表脚本使用文本差异合并。"
        case .project: return "适用于文本格式工程资源与代码；遇到二进制内容自动进行可隔离性检查。"
        case .text: return "仅合并作者改动片段；未知格式会检查实际内容，无法隔离时停止。"
        case .binary: return "仅在目标与来源基线等条件一致时迁移；不同内容无法拆分作者修改时停止。旧版 .xls 也属于此类。"
        case .pmdata: return "此文件不直接合入。Excel 合入完成后，在 Release 分支使用 xtools 导出。"
        }
    }
    var conflictLabel: String { self == .excel ? "单元格或工作表冲突" : self == .lua ? "字段冲突" : "文本片段冲突" }
}

struct SyncReport: Decodable {
    struct Config: Decodable { let dev: String; let release: String; let target: String; let author: String; let start: String; let end: String; let snapshot: Int; var sourceName: String? = nil; var targetName: String? = nil; var days: Int? = nil; var scopeDirectories: [String]? = nil; var scopeTotal: Int? = nil; var scopeExcluded: Int? = nil; var scopeRevisions: [Int]? = nil }
    struct FileItem: Decodable, Identifiable {
        let path: String
        let kind: String
        let revisions: [Int]
        let latestRevision: Int
        let message: String
        let date: String
        var id: String { path }
        var mergeType: SyncMergeType { .classify(path) }
        var fileExtension: String { let ext = (path as NSString).pathExtension.lowercased(); return ext.isEmpty ? "(none)" : ext }
        var name: String { (path as NSString).lastPathComponent }
        var directory: String { (path as NSString).deletingLastPathComponent }
        var versions: String { revisions.map { "r\($0)" }.joined(separator: ", ") }
    }
    struct Commit: Decodable, Identifiable {
        struct Path: Decodable {
            let path: String
            let action: String
            let kind: String?
            let copyFrom: String?
            var actionLabel: String { ["M": "已修改", "A": "已添加", "D": "已删除", "R": "已替换"][action] ?? action }
        }
        let revision: Int
        let date: String
        let message: String
        let paths: [Path]
        let outsideScope: [String]?
        var id: String { String(revision) }
    }
    let dev: [Commit]?
    let config: Config
    let fileItems: [FileItem]?
    let directoryChangeCount: Int?
    var files: [FileItem] { fileItems ?? [] }
}

struct SyncWithdrawnRow: Decodable { let sheet: String; let row: Int }
struct SyncReviewEntry: Decodable {
    struct LocalState: Decodable {
        let item: String
        let status: [String: String]
        let hash: String?
        let properties: [String: String]?
        var preventsAccept: Bool {
            !["normal", "none"].contains(item)
                || ![nil, "none", "normal"].contains(status["props"])
                || status["tree-conflicted"] == "true"
        }
    }
    struct Risk: Decodable { let version: Int; let level: String; let reasons: [String] }
    let risk: Risk?
    var lowRisk: Bool { includesLocalChanges != true && risk?.version == 1 && risk?.level == "low" }
    let local: LocalState?
    let candidateHash: String?
    let properties: [String: String]?
    let acceptedExisting: Bool?
    let includesLocalChanges: Bool?
    var localMatchesCandidate: Bool {
        guard let local, let candidateHash, let properties, let localProperties = local.properties else { return false }
        return ["normal", "modified"].contains(local.item)
            && [nil, "none", "normal", "modified"].contains(local.status["props"])
            && local.status["tree-conflicted"] != "true"
            && local.hash == candidateHash && localProperties == properties
    }
    var preservesLocalChanges: Bool {
        guard includesLocalChanges == true, canResume, candidate != nil, baseline != nil,
              candidateHash != nil, properties != nil, let local, local.hash != nil,
              local.properties != nil else { return false }
        return ["normal", "modified"].contains(local.item)
            && [nil, "none", "normal", "modified"].contains(local.status["props"])
            && local.status["tree-conflicted"] != "true"
    }
    var confirmationHint: String {
        if preservesLocalChanges {
            return "待合入结果已保留可独立合并的本地修改。确认后工具自动备份、更新并写入此文件；尚不提交 SVN。"
        }
        return localMatchesCandidate
            ? "目标分支本地内容已与待合入结果一致。确认时重新核对，仅记录确认结果，不重复写入；尚未提交 SVN。"
            : "左侧：目标分支 SVN 快照　右侧：待合入结果。确认后写入本地目标分支，尚不提交 SVN。"
    }
    var withdrawnRows: [SyncWithdrawnRow]?
    let authorIsolation: Int?
    let galaxyMergeVersion: Int?
    let deletionGuardVersion: Int?
    let path: String
    let status: String
    let revision: Int
    let candidate: String?
    let baseline: String?
    let same: Bool
    let revisions: [Int]?
    let summary: String
    var canResume: Bool {
        let isGalaxyAsset = path.lowercased().hasSuffix(".asset") && ("/" + path.lowercased()).contains("/config/galaxy/")
        return status == "ready" && authorIsolation == 9 && deletionGuardVersion == 2 && (!isGalaxyAsset || galaxyMergeVersion == 1)
    }
    var preparationIssue: String? {
        guard status == "ready" else { return nil }
        if !canResume { return "作者隔离规则已更新，请重新生成并核对；旧副本已保留。" }
        if local?.preventsAccept == true && !localMatchesCandidate && !preservesLocalChanges {
            return "Release 文件有本地修改或异常状态。请先查看并处理本地修改，再重新生成并核对；也可跳过此文件继续。待合入副本已保留。"
        }
        return nil
    }
}

struct SyncExportRecord: Codable {
    let token: String
    var completed: Bool
    var publicationHash: String? = nil
}

struct XToolsCandidate: Decodable {
    struct Output: Decodable {
        let target: String
        let candidate: String
        let before: String?
        let after: String
    }
    let status: String
    let receipt: String
    let sha256: String
    let message: String
    let fields: Int
    let outputs: [Output]
    let publishedWorkbooks: [String: String]?
}

struct SyncWriteBatch {
    enum State { case running, stopping, completed, stopped, failed, interrupted }
    enum Outcome: String { case written = "已写入本地", existing = "本地一致，已确认", failed = "需要处理" }
    let paths: [String]
    let target: String
    let started = Date()
    var ended: Date?
    var state: State = .running
    var currentPath: String?
    var outcomes: [String: Outcome] = [:]
    var failure: String?
    var failedPath: String?
    var active: Bool { state == .running || state == .stopping }
    var completed: Int { outcomes.values.filter { $0 != .failed }.count }
    var failures: Int { outcomes.values.filter { $0 == .failed }.count }
    var unstarted: Int { max(0, paths.count - outcomes.count - (currentPath == nil ? 0 : 1)) }
    var title: String {
        switch state {
        case .running: return "正在批量写入"
        case .stopping: return "正在安全停止"
        case .completed: return "批量写入完成"
        case .stopped: return "批量写入已停止"
        case .failed: return "批量写入受阻"
        case .interrupted: return "写入中断，请检查现场"
        }
    }
    var summary: String { "已完成 \(completed) / \(paths.count) · 失败 \(failures) · 未开始 \(unstarted)" }
}

@MainActor final class BranchSyncModel: ObservableObject {
    let scopeDraft = SyncScopeDraft()
    let progress = SyncProgressModel()
    @Published private(set) var endpointDisplay = MergeEndpointDisplay.current()
    private var resultMonitor: WorkspaceMonitor?
    private var resultMonitorRoot: String?
    private var localChangeGeneration = 0
    private var pendingLocalChecks = Set<String>()
    private var invalidatedLocalPaths = Set<String>()
    // Display continuity is not verification evidence or permission to write.
    private var retainedVisiblePaths = Set<String>()
    private var localCheckTask: Task<Void, Never>?

    private func watchAcceptedResults() {
        guard let root = report?.config.target, root != resultMonitorRoot else { return }
        resultMonitor?.stop()
        resultMonitorRoot = root
        invalidatedLocalPaths.removeAll()
        resultMonitor = WorkspaceMonitor(root: root, since: UInt64.max) { [weak self] events in
            guard let self else { return }
            self.releaseFilesChanged(events, root: root)
        }
    }

    func releaseFilesChanged(_ events: [(String, UInt32)], root: String) {
        guard root == report?.config.target else { return }
        let changed = events.map { "/" + $0.0.trimmingCharacters(in: CharacterSet(charactersIn: "/")) }
        let admin = changed.contains { $0 == root || $0.hasPrefix(root + "/.svn/") }
        let affected = files.filter { file in
            let absolute = URL(fileURLWithPath: root).appendingPathComponent(file.path).path
            return admin || changed.contains { absolute == $0 || absolute.hasPrefix($0 + "/") }
        }.filter { $0.mergeType != .pmdata }.map(\.path)
        guard !affected.isEmpty else { return }
        retainedVisiblePaths.formUnion(listedFiles.map(\.path))
        localChangeGeneration += 1
        invalidatedLocalPaths.formUnion(affected)
        for path in affected {
            localStates.removeValue(forKey: path)
            repositoryStates.removeValue(forKey: path)
            verifiedNoDiffPaths.remove(path)
            done.remove(path)
        }
        selectedPaths.subtract(affected)
        pendingLocalChecks.formUnion(affected)
        if busy && action == "remaining-diff", let requested = remainingRequestedPaths { pendingLocalChecks.formUnion(requested) }
        scheduleResultCheck()
    }

    func scheduleResultCheck() {
        // File-system events invalidate evidence; only an explicit operation may
        // perform remote verification. Window focus must never start a full scan.
        guard !pendingLocalChecks.isEmpty else { return }
        activity = "本地文件发生变化 · 生成或确认前将重新核验相关文件"
        pendingLocalChecks.removeAll()
    }

    @Published var author = UserDefaults.standard.string(forKey: "SvnFlow.syncAuthor.v1") ?? ""
    @Published var days = UserDefaults.standard.integer(forKey: "SvnFlow.syncDays.v1") == 0 ? 30 : UserDefaults.standard.integer(forKey: "SvnFlow.syncDays.v1")
    @Published var report: SyncReport?
    @Published var selection: String? = UserDefaults.standard.string(forKey: "SvnFlow.syncFile.v1") { didSet { UserDefaults.standard.set(selection, forKey: "SvnFlow.syncFile.v1") } }
    @Published var selectedPaths = Set<String>() { didSet { if !loadingSelection { saveSelection() } } }
    private var loadingSelection = false
    private var restoredSelection = false
    @Published var reviewSelectedPaths = Set<String>()
    @Published var busy = false
    @Published var reviewing = false
    @Published var batchAccepting = false
    @Published var interrupted = false
    @Published var output = "选择文件后点击“生成副本”，生成完成后核对并确认。"
    @Published var done = Set<String>()
    @Published var skipped = Set<String>()
    @Published var blocked = Set<String>()
    @Published var filter = UserDefaults.standard.string(forKey: "SvnFlow.syncFilter.v1") ?? "" { didSet { UserDefaults.standard.set(filter, forKey: "SvnFlow.syncFilter.v1"); pruneFilteredSelection() } }
    @Published var pendingOnly = false { didSet { pruneFilteredSelection() } }
    @Published var directory = "" { didSet { pruneFilteredSelection() } }
    @Published private(set) var ignoredRevisions: [String: [Int]] = [:]
    @Published private(set) var luaDirectories: [String] = []
    @Published private(set) var exportRecords: [String: SyncExportRecord] = [:]
    private var luaExceptions: [String: [Int]] = [:]
    private var workflowKey: String? {
        guard let config = report?.config else { return nil }
        let identity = [config.dev, config.release, config.target].joined(separator: "\n")
        return "SvnFlow.xtools.v1." + Data(identity.utf8).base64EncodedString()
    }
    private struct LuaRules: Codable {
        var directories: [String]
        var exceptions: [String: [Int]]
    }
    func matchesLuaRule(_ path: String) -> Bool {
        guard (path as NSString).pathExtension.lowercased() == "lua" else { return false }
        if let revisions = luaExceptions[path], files.first(where: { $0.path == path })?.revisions == revisions { return false }
        return luaDirectories.contains { path.hasPrefix($0 + "/") }
    }
    private func rebuildIgnored() {
        skipped = Set(entries.values.filter { $0.status == "skipped" }.map(\.path))
            .union(ignoredRevisions.keys)
            .union(files.filter { !done.contains($0.path) && matchesLuaRule($0.path) }.map(\.path))
        selectedPaths.subtract(skipped); reviewSelectedPaths.subtract(skipped)
        queue.removeAll { skipped.contains($0) }
    }
    func saveLuaDirectories(_ text: String) {
        guard canChangeBatch, let key = workflowKey else { return }
        let lines = text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "\\", with: "/") }.filter { !$0.isEmpty }
        guard !lines.contains(where: { $0.hasPrefix("/") }) else { activity = "请输入工作副本内的相对目录"; return }
        let directories = lines.map { $0.trimmingCharacters(in: CharacterSet(charactersIn: "/")) }
        guard directories.allSatisfy({ !$0.split(separator: "/").contains("..") && !$0.contains(":") }) else {
            activity = "请输入工作副本内的相对目录，不包含 .."; return
        }
        luaDirectories = Array(Set(directories)).sorted()
        if let data = try? JSONEncoder().encode(LuaRules(directories: luaDirectories, exceptions: luaExceptions)) {
            UserDefaults.standard.set(data, forKey: key + ".rules")
        }
        rebuildIgnored()
        activity = "已保存导出 Lua 目录规则；匹配文件在生成前跳过"
    }
    private func loadWorkflow() {
        guard let key = workflowKey else { return }
        let rules = UserDefaults.standard.data(forKey: key + ".rules").flatMap { try? JSONDecoder().decode(LuaRules.self, from: $0) }
        luaDirectories = rules?.directories ?? []; luaExceptions = rules?.exceptions ?? [:]
        exportRecords = UserDefaults.standard.data(forKey: key + ".exports").flatMap { try? JSONDecoder().decode([String: SyncExportRecord].self, from: $0) } ?? [:]
        rebuildIgnored()
        recordAcceptedExcel()
        exportCandidate = (try? Data(contentsOf: folder.appendingPathComponent(exportLatestName))).flatMap { try? JSONDecoder().decode(XToolsCandidate.self, from: $0) }
        exportCandidateReceipt = exportCandidate?.receipt
    }
    func recordAcceptedExcel() {
        guard !workspaceExport, let key = workflowKey else { return }
        for entry in entries.values where entry.status == "invalidated" { exportRecords.removeValue(forKey: entry.path) }
        for entry in entries.values where entry.status == "accepted" && !entry.same && SyncMergeType.classify(entry.path) == .excel {
            let token = entry.candidate ?? "delete:\(entry.revision):\(entry.path)"
            if exportRecords[entry.path]?.token != token { exportRecords[entry.path] = SyncExportRecord(token: token, completed: false) }
        }
        if let data = try? JSONEncoder().encode(exportRecords) { UserDefaults.standard.set(data, forKey: key + ".exports") }
    }
    var pendingExports: [String] { if workspaceExport { return workspaceExportPaths.sorted() }; return exportRecords.keys.filter { exportRecords[$0]?.completed != true || exportRecords[$0]?.publicationHash == nil }.sorted() }
    @Published var exportCandidateReceipt: String?
    @Published var exportCandidate: XToolsCandidate?
    @Published var selectedExports = Set<String>() {
        didSet {
            if oldValue != selectedExports {
                exportCandidate = nil
                exportCandidateReceipt = nil
            }
        }
    }
    var exportablePaths: Set<String> {
        if workspaceExport { return workspaceExportPaths }
        return Set(exportRecords.keys.filter { WorkbookExportScope.supports($0) && entries[$0]?.status == "accepted" && entries[$0]?.same == false && exportRecords[$0]?.token.hasPrefix("delete:") == false })
    }
    func exportXTools() async {
        guard canChangeBatch, !selectedExports.isEmpty, selectedExports.isSubset(of: exportablePaths) else { return }
        busy = true
        exportCandidateReceipt = nil
        exportCandidate = nil
        activity = "正在按规则生成并核验，随后自动写入 Lua、pmdata 到对应目录"
        defer { busy = false }
        do {
            if workspaceExport {
                _ = try await command("xtools-local-init", folder: folder, path: workspaceExportTarget)
            }
            let value = try await command(workspaceExport ? "xtools-local-export" : "xtools-export", folder: folder, workbooks: selectedExports.sorted())
            let result = try JSONDecoder().decode(XToolsCandidate.self, from: Data(value.utf8))
            guard result.status == "published" else { throw NSError(domain: "XTools", code: 1, userInfo: [NSLocalizedDescriptionKey: "导出未完成写后核验"]) }
            exportCandidateReceipt = result.receipt
            completeXTools(result)
        } catch {
            // Keep a verified receipt available if publication was interrupted.
            exportCandidate = (try? Data(contentsOf: folder.appendingPathComponent(exportLatestName))).flatMap { try? JSONDecoder().decode(XToolsCandidate.self, from: $0) }
            exportCandidateReceipt = exportCandidate?.receipt
            activity = "导出未完成：\(error.localizedDescription)。已保留处理状态，可重新导出或继续未完成的导出。"
        }
    }
    func publishXTools(resume: Bool) async {
        guard canChangeBatch, let candidate = exportCandidate else { return }
        busy = true
        defer { busy = false }
        do {
            let value = try await command(workspaceExport ? (resume ? "xtools-local-resume" : "xtools-local-publish") : (resume ? "xtools-resume" : "xtools-publish"), folder: folder, reviewHash: candidate.sha256)
            let result = try JSONDecoder().decode(XToolsCandidate.self, from: Data(value.utf8))
            guard result.status == "published" else { throw NSError(domain: "XTools", code: 2, userInfo: [NSLocalizedDescriptionKey: "发布未通过写后核验"]) }
            completeXTools(result)
        } catch {
            activity = "发布未完成：\(error.localizedDescription)。保留已写入状态；核对后可选择继续发布，不会自动回滚。"
        }
    }
    private func completeXTools(_ result: XToolsCandidate) {
        exportCandidate = result
        for (path, digest) in result.publishedWorkbooks ?? [:] where !workspaceExport && entries[path]?.candidateHash == digest {
            if var record = exportRecords[path] {
                record.completed = true
                record.publicationHash = result.sha256
                exportRecords[path] = record
            }
        }
        if !workspaceExport, let key = workflowKey, let data = try? JSONEncoder().encode(exportRecords) {
            UserDefaults.standard.set(data, forKey: key + ".exports")
        }
        activity = result.message
        NotificationCenter.default.post(name: .refreshWorkingCopy, object: nil)
    }
    func compareExport(_ item: XToolsCandidate.Output) {
        QueryWindows.shared.compare(item.target, files: ComparisonFiles(old: item.before == nil ? nil : item.target, new: item.candidate, oldLabel: workspaceExport ? "当前工作副本" : "当前 \(targetName)", newLabel: "XTools 待发布"))
    }
    var exportChecklist: String {
        ([(workspaceExport ? "工作副本：" + workspaceExportTarget : targetName + "：" + (report?.config.target ?? "")), workspaceExport ? "请在 xtools 中导出以下本地 Excel（含相关依赖），并核对生成结果：" : "请在 xtools 中导出以下实际已合入的配置（含相关依赖），并核对生成结果："] + pendingExports.map { (exportRecords[$0]?.token.hasPrefix("delete:") == true ? "[已删除配置，请核对并清理对应导出产物] " : "") + $0 }).joined(separator: "\n")
    }
    func setExportCompleted(_ path: String, completed: Bool) {
        guard canChangeBatch, let key = workflowKey, var record = exportRecords[path] else { return }
        record.completed = completed; exportRecords[path] = record
        if let data = try? JSONEncoder().encode(exportRecords) { UserDefaults.standard.set(data, forKey: key + ".exports") }
    }
    @Published var typeFilter = UserDefaults.standard.string(forKey: "SvnFlow.syncTypeFilter.v1") ?? "" { didSet { UserDefaults.standard.set(typeFilter, forKey: "SvnFlow.syncTypeFilter.v1"); pruneFilteredSelection() } }
    @Published var action = ""
    @Published var activity = "等待选择文件"
    @Published var outputState = "idle"
    @Published var outputPath: String?
    @Published var fileOutputs: [String: String] = [:]
    @Published var entries: [String: SyncReviewEntry] = [:]
    private var reviewFailures: [String: String] = [:]
    var readyPaths: [String] { listedFiles.map(\.path).filter { isReady($0) } }
    func isReady(_ path: String) -> Bool {
        if repositoryStates[path] != "different" || localRemainingIssues[path] != nil { return false }
        return !interrupted && !blocked.contains(path) && !done.contains(path) && !skipped.contains(path)
            && entries[path]?.canResume == true && entries[path]?.preparationIssue == nil
    }
    private func saveReviewFailures() {
        do { try JSONEncoder().encode(reviewFailures).write(to: folder.appendingPathComponent("review-failures.json"), options: .atomic) }
        catch { output += "\n无法保存失败记录：" + error.localizedDescription }
    }
    func compareLocal(_ path: String) {
        guard let target = report?.config.target else { return }
        QueryWindows.shared.compare(URL(fileURLWithPath: target).appendingPathComponent(path).path)
    }
    func retry(_ path: String) async {
        guard canChangeBatch, blocked.contains(path), !done.contains(path), !skipped.contains(path) else { return }
        selectedPaths = [path]
        await merge(regenerating: path)
    }
    func skipBlocked(_ path: String) async {
        guard canChangeBatch, entries[path]?.status == "ready" else { return }
        do {
            try await decide(path, accept: false)
            queue.removeAll { $0 == path }
            await prepareNext()
        } catch { activity = "跳过失败 · 请查看原因" }
    }
    private var regenerationPaths = Set<String>()
    var queue: [String] = []
    var folder: URL
    var backupRoot: URL { Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("合入备份", isDirectory: true) }
    let workspaceExport: Bool
    @Published var workspaceExportTarget = ""
    @Published var workspaceExportLabel = ""
    @Published var workspaceExportPaths = Set<String>()
    var displayedExportPaths: [String] { workspaceExport ? workspaceExportPaths.sorted() : exportRecords.keys.sorted() }
    private var exportLatestName: String { workspaceExport ? "xtools-local-latest.json" : "xtools-latest.json" }
    init(workspaceExport: Bool = false) {
        self.workspaceExport = workspaceExport
        if workspaceExport {
            folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("SvnFlow/WorkspaceExports/" + UUID().uuidString, isDirectory: true)
            return
        }
        folder = UserDefaults.standard.string(forKey: "SvnFlow.branchSyncReport.v1").map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("SvnFlow-catalog-" + UUID().uuidString)
        try? load(repair: false)
        queue = files.map(\.path).filter { selectedPaths.contains($0) && canGenerate($0) && !skipped.contains($0) }
    }
    func refreshEndpointDisplay() { endpointDisplay = .current() }
    var sourceName: String { report?.config.sourceName ?? endpointDisplay.sourceName }
    var targetName: String { report?.config.targetName ?? endpointDisplay.targetName }
    var directionTitle: String { "\(sourceName) → \(targetName)" }
    var files: [SyncReport.FileItem] { report?.files ?? [] }
    @Published var verifiedNoDiffPaths = Set<String>()
    private var currentRemainingIssues: [String: String] = [:]
    @Published var repositoryStates: [String: String] = [:]
    @Published var localStates: [String: String] = [:]
    @Published var localRemainingIssues: [String: String] = [:]
    @Published var remainingCheckFailed = false
    private var remainingReportDigest = ""
    private var remainingCheckedPaths = Set<String>()
    private var remainingRequestedPaths: Set<String>?
    private var remainingSnapshot: Int?

    func remainingFailed(_ path: String) -> Bool {
        repositoryStates[path] == "error" || (remainingCheckFailed && (remainingRequestedPaths?.contains(path) ?? true))
    }

    func applyRemaining(_ result: RemainingDiffResult) {
        guard !interrupted, result.reportDigest == remainingReportDigest else { return }
        remainingSnapshot = result.snapshot
        let completed = Set(result.noDiffPaths + result.differentPaths + Array(result.errors.keys))
        remainingCheckedPaths.formUnion(completed)
        for path in completed {
            localStates[path] = result.localStates?[path]
            localRemainingIssues[path] = result.localIssues?[path]
            currentRemainingIssues[path] = result.errors[path]
            if result.noDiffPaths.contains(path) {
                repositoryStates[path] = "same"
                verifiedNoDiffPaths.insert(path)
            } else {
                repositoryStates[path] = result.errors[path] == nil ? "different" : "error"
                verifiedNoDiffPaths.remove(path)
                if result.errors[path] == nil && ["accepted", "invalidated"].contains(entries[path]?.status ?? "") {
                    blocked.remove(path)
                    if result.localStates?[path] != "same" && result.localIssues?[path] == nil { done.remove(path) }
                }
            }
        }
        let finished = Set(completed.filter { localContainsChanges($0) }).union(verifiedNoDiffPaths.filter { localRemainingIssues[$0] == nil })
        // Fresh equality evidence supersedes failures from older preparation attempts.
        blocked.subtract(finished)
        selectedPaths.subtract(finished)
        reviewSelectedPaths.subtract(finished)
    }

    func localContainsChanges(_ path: String) -> Bool {
        localStates[path] == "same" && localRemainingIssues[path] == nil
    }

    // Historical `same` compares old artifacts, not the current Release branch.
    func hasNoDiff(_ file: SyncReport.FileItem) -> Bool {
        !interrupted && workflowStatus(file.path) != "待导出"
            && (verifiedNoDiffPaths.contains(file.path) || localContainsChanges(file.path))
            && localRemainingIssues[file.path] == nil
    }
    func hasVisibleResult(_ file: SyncReport.FileItem) -> Bool {
        file.mergeType == .pmdata || repositoryStates[file.path] != nil || remainingFailed(file.path) || retainedVisiblePaths.contains(file.path)
    }
    var uncheckedPaths: [String] {
        files.filter { $0.mergeType != .pmdata && repositoryStates[$0.path] == nil && !remainingFailed($0.path) }.map(\.path)
    }
    var listedFiles: [SyncReport.FileItem] { files.filter { hasVisibleResult($0) && !hasNoDiff($0) } }
    var hiddenNoDiffCount: Int { files.filter { hasNoDiff($0) }.count }
    var verificationSummary: String {
        if busy && action == "remaining-diff" { return "正在核验 Release · 结果逐项显示" }
        if interrupted { return "上次写入中断，请先查看活动记录" }
        if !uncheckedPaths.isEmpty { return "核验尚未完成 · 点击刷新继续" }
        return listedFiles.isEmpty ? "本轮没有需要合入的文件" : "仅显示已核验的差异与需处理文件"
    }
    var visibleFiles: [SyncReport.FileItem] { listedFiles.filter { (directory.isEmpty || $0.path.hasPrefix(directory + "/")) && (typeFilter.isEmpty || $0.fileExtension == typeFilter) && (!pendingOnly || (!done.contains($0.path) && !localContainsChanges($0.path))) && (filter.isEmpty || $0.path.localizedCaseInsensitiveContains(filter)) } }
    var current: SyncReport.FileItem? { listedFiles.first { $0.id == selection } }
    var operationPaths: [String] { files.map(\.path).filter { selectedPaths.contains($0) && !done.contains($0) && !skipped.contains($0) } }
    // Lifecycle is independent of risk and transient progress.
    func queueStatus(_ path: String) -> String {
        if done.contains(path) || localContainsChanges(path) { return "已同步" }
        if skipped.contains(path) { return "已忽略" }
        if entries[path]?.status == "ready" { return "待确认" }
        return "未处理"
    }
    // Display one actionable state; a failed generation is not also “unprocessed”.
    func isTemporarilyBlocked(_ path: String) -> Bool {
        guard blocked.contains(path), !done.contains(path), !skipped.contains(path) else { return false }
        return failureReason(path).contains("其他合入任务正在运行")
    }
    func failureReason(_ path: String) -> String {
        currentRemainingIssues[path] ?? reviewFailures[path] ?? entries[path]?.preparationIssue ?? fileOutputs[path] ?? "请查看处理详情"
    }
    func workflowStatus(_ path: String) -> String {
        if done.contains(path) && pendingExports.contains(path) { return "待导出" }
        if SyncMergeType.classify(path) != .pmdata {
            if localContainsChanges(path), repositoryStates[path] != "same" { return "已写入本地" }
            if repositoryStates[path] == "same" {
                return localRemainingIssues[path] == nil ? "已合入" : "已合入 · 本地需处理"
            }
            if repositoryStates[path] == "error" { return "无法确认" }
            if repositoryStates[path] == nil {
                if remainingFailed(path) { return "无法确认" }
                return busy && action == "remaining-diff" && (progress.activity?.activePaths?.contains(path) == true) ? "核验中" : "待核验"
            }
            if localRemainingIssues[path] != nil { return "待合入 · 本地需处理" }
        }
        if done.contains(path) { return exportRecords[path]?.completed == false ? "待导出" : "已写入本地" }
        if skipped.contains(path) { return "已忽略" }
        if blocked.contains(path) { return isTemporarilyBlocked(path) ? "暂时受阻" : "需要处理" }
        if isReady(path) { return entries[path]?.lowRisk == true ? "可确认" : "待核对" }
        return SyncMergeType.classify(path) == .pmdata ? "待导出" : "待合入"
    }
    func isProcessingFile(_ path: String) -> Bool {
        busy && (outputPath == path || (action == "remaining-diff" && progress.activity?.activePaths?.contains(path) == true))
    }
    func statusCategory(_ path: String) -> SyncStatusCategory {
        SyncStatusCategory.classify(workflowStatus(path), ignored: skipped.contains(path), processing: isProcessingFile(path))
    }
    static func migratedConfirmationFilter(_ value: String) -> String {
        if ["全部", "待确认", "低风险", "已完成", "已忽略"].contains(value) { return value }
        let category = SyncStatusCategory.classify(value)
        return category == .completed || category == .ignored ? category.rawValue : "待确认"
    }
    func confirmationCategory(_ path: String) -> String {
        if skipped.contains(path) { return "已忽略" }
        if statusCategory(path) == .completed { return "已完成" }
        return !isProcessingFile(path) && isReady(path) && entries[path]?.lowRisk == true ? "低风险" : "待确认"
    }
    func matchesConfirmationFilter(_ path: String, filter: String) -> Bool {
        filter == "全部" || confirmationCategory(path) == filter
    }
    func displayStage(_ path: String) -> String {
        let category = confirmationCategory(path)
        return category == "已完成" ? executionStage(path) : category
    }
    func executionStage(_ path: String) -> String {
        if skipped.contains(path) { return "已忽略" }
        if isProcessingFile(path) {
            if ["accept", "accept-low"].contains(action) { return "正在写入" }
            return action == "remaining-diff" ? "正在核验" : "正在生成"
        }
        switch workflowStatus(path) {
        case "可确认", "待核对": return "待确认"
        case "待合入": return "待生成"
        case "无法确认", "已合入 · 本地需处理", "待合入 · 本地需处理", "暂时受阻", "需要处理": return "需处理"
        default: return workflowStatus(path)
        }
    }
    func shortReason(_ path: String) -> String {
        if skipped.contains(path) {
            return ignoredRevisions[path] != nil || matchesLuaRule(path)
                ? "本轮不合入；恢复后按当前核验结果继续"
                : "本轮已暂不合入，副本与处理记录保留"
        }
        if isProcessingFile(path) { return progress.activity?.phase ?? progress.phase }
        if done.contains(path) && pendingExports.contains(path) { return "已写入本地，等待 xtools 导出；尚未提交 SVN" }
        if SyncMergeType.classify(path) != .pmdata {
            if localContainsChanges(path), repositoryStates[path] != "same" { return "\(targetName) 本地已包含所需改动；尚未提交 SVN，可查看本地差异" }
            if let issue = localRemainingIssues[path] { return issue }
            if repositoryStates[path] == "same" { return "\(targetName) 仓库已包含所需改动，无需重复合入" }
            if repositoryStates[path] == "error" { return currentRemainingIssues[path] ?? "核验未完成，不能判断为未合入" }
            if repositoryStates[path] == "different" && ["accepted", "invalidated"].contains(entries[path]?.status ?? "") { return "当前 \(targetName) 仓库仍有剩余差异，请重新生成并核对" }
            if repositoryStates[path] == nil { return remainingFailed(path) ? "核验未完成，请重试；不能判断为未合入" : "尚未核对当前 \(targetName)；点击“核验此文件”开始" }
            if busy && action == "remaining-diff" && (remainingRequestedPaths?.contains(path) ?? true) && !remainingCheckedPaths.contains(path) { return "上次核验仍有差异，正在复核" }
        }
        if blocked.contains(path) && !done.contains(path) && !skipped.contains(path) {
            let reason = failureReason(path)
            if isTemporarilyBlocked(path) { return "其他合入任务占用 \(targetName)" }
            if reason.contains("缺少配置 ID") {
                let line = reason.split(separator: "\n").last(where: { $0.contains("缺少配置 ID") }).map(String.init) ?? reason
                return line.replacingOccurrences(of: "ValueError: ", with: "")
            }
            if reason.contains("本地修改") { return "\(targetName) 有本地修改，需先核对" }
            return reason.split(separator: "\n").last.map(String.init) ?? reason
        }
        if done.contains(path) { return pendingExports.contains(path) ? "已写入本地，等待 xtools 导出" : "已写入 \(targetName) 本地，尚未提交 SVN" }
        if skipped.contains(path) { return "本轮不合入" }
        if let entry = entries[path], isReady(path) { return entry.lowRisk ? "副本已生成，风险评估通过" : (entry.risk?.reasons.first ?? "副本已生成，需要逐个核对") }
        return SyncMergeType.classify(path) == .pmdata ? "由 \(targetName) 的 xtools 生成" : "尚未生成待合入副本"
    }
    func nextStep(_ path: String) -> String {
        if skipped.contains(path) { return "查看忽略记录" }
        if isProcessingFile(path) { return "查看进度" }
        switch workflowStatus(path) {
        case "待核验": return "核验此文件"
        case "核验中": return "查看进度"
        case "无法确认": return "查看核验原因"
        case "已合入", "已合入 · 本地需处理", "待合入 · 本地需处理": return "查看本地状态"
        case "暂时受阻": return "重试生成"
        case "需要处理": return "查看原因与处理"
        case "可确认": return "查看差异并确认"
        case "待核对": return "查看差异并确认"
        case "待导出": return "查看 xtools 清单"
        case "已同步", "已写入本地": return "查看结果"
        case "已忽略": return "查看忽略记录"
        default: return "生成副本"
        }
    }
    func retryTemporarilyBlocked(_ paths: [String]) async {
        let originalSelection = selectedPaths
        for path in paths {
            guard canChangeBatch, matchesScope else { break }
            if isTemporarilyBlocked(path) { await retry(path) }
            if progress.cancelling { break }
        }
        selectedPaths = originalSelection.filter { canSelect($0) }
    }
    func canGenerate(_ path: String) -> Bool {
        if repositoryStates[path] != "different" || localRemainingIssues[path] != nil { return false }
        return queueStatus(path) == "未处理" && SyncMergeType.classify(path) != .pmdata
    }
    func canSelect(_ path: String) -> Bool {
        if SyncMergeType.classify(path) != .pmdata && repositoryStates[path] == nil && !remainingFailed(path) { return false }
        if localContainsChanges(path) { return false }
        // Restoring an ignore is a selection action, not permission to generate or write.
        if !done.contains(path) && skipped.contains(path) && (ignoredRevisions[path] != nil || matchesLuaRule(path)) { return true }
        if SyncMergeType.classify(path) != .pmdata && (repositoryStates[path] == "same" || localRemainingIssues[path] != nil) { return false }
        return !done.contains(path) && (!skipped.contains(path) || ignoredRevisions[path] != nil || matchesLuaRule(path))
    }
    var migrationPaths: [String] { operationPaths.filter { SyncMergeType.classify($0) != .pmdata && !blocked.contains($0) && reviewFailures[$0] == nil && entries[$0]?.preparationIssue == nil } }
    var availableExtensions: [String] { Set(listedFiles.map(\.fileExtension)).sorted() }
    var visibleMergeTypes: [SyncMergeType] { SyncMergeType.allCases.filter { type in visibleFiles.contains { $0.mergeType == type } } }
    var canChangeBatch: Bool { !busy && !reviewing && !batchAccepting && !interrupted }
    var hasPendingReview: Bool { entries.values.contains { $0.status == "ready" && !skipped.contains($0.path) } }
    var matchesScope: Bool { author == report?.config.author && days == report?.config.days }
    var canRefresh: Bool { canChangeBatch && !author.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var refreshHelp: String {
        "重新核验本轮 Release，只显示差异与需处理文件；新的提交通过新建轮次纳入。"
    }
    var lastRefresh: String {
        guard let end = report?.config.end, let date = ISO8601DateFormatter().date(from: end) else { return "尚未刷新" }
        return "本轮固定截止 " + date.formatted(.dateTime.month().day().hour().minute())
    }
    func saveSelection() {
        guard report != nil else { return }
        do { try JSONEncoder().encode(selectedPaths.sorted()).write(to: folder.appendingPathComponent("selection.json"), options: .atomic) }
        catch { output = "无法保存文件选择：" + error.localizedDescription }
    }
    var canMerge: Bool { canChangeBatch && author == report?.config.author && report?.config.days == days && !migrationPaths.isEmpty }
    func pruneFilteredSelection() {
        if canChangeBatch { selectedPaths.formIntersection(Set(files.filter { canSelect($0.path) }.map(\.path))) }
        reviewSelectedPaths.formIntersection(Set(files.map(\.path)))
        if !visibleFiles.contains(where: { $0.path == selection }) { selection = visibleFiles.first?.path }
    }
    func selectVisible() { selectedPaths = Set(visibleFiles.filter { canGenerate($0.path) }.map(\.path)) }
    func selectRemaining() {
        guard canChangeBatch else { return }
        selectedPaths = Set(listedFiles.filter { !done.contains($0.path) && !skipped.contains($0.path) && $0.mergeType != .pmdata }.map(\.path))
    }
    var ignorablePaths: [String] { files.map(\.path).filter { selectedPaths.contains($0) && !done.contains($0) && !skipped.contains($0) } }
    var restorablePaths: [String] { files.map(\.path).filter { selectedPaths.contains($0) && (ignoredRevisions[$0] != nil || matchesLuaRule($0)) } }
    func setIgnored(_ ignored: Bool) {
        guard canChangeBatch else { return }
        let paths = ignored ? ignorablePaths : restorablePaths
        guard !paths.isEmpty else { return }
        var records = ignoredRevisions
        for file in files where paths.contains(file.path) {
            records[file.path] = ignored ? file.revisions : nil
        }
        do {
            try JSONEncoder().encode(records).write(to: folder.appendingPathComponent("ignored-files.json"), options: .atomic)
            ignoredRevisions = records
            for path in paths {
                luaExceptions[path] = ignored ? nil : files.first(where: { $0.path == path })?.revisions
            }
            saveLuaDirectories(luaDirectories.joined(separator: "\n"))
            rebuildIgnored()
            selectedPaths.subtract(paths); reviewSelectedPaths.subtract(paths)
            queue.removeAll { skipped.contains($0) }
            activity = ignored ? "已忽略 \(paths.count) 个文件" : "已恢复 \(paths.count) 个文件"
        } catch { output = "无法保存忽略记录：" + error.localizedDescription; activity = "忽略记录保存失败" }
    }
    func focusAndSelect(_ path: String) {
        selection = path
        if canChangeBatch && canGenerate(path) { selectedPaths.insert(path) }
    }
    func toggle(_ path: String, checked: Bool) {
        guard canChangeBatch, canSelect(path) else { return }
        if checked { selectedPaths.insert(path) } else { selectedPaths.remove(path) }
        selection = path
    }
    func status(_ path: String) -> String {
        if SyncMergeType.classify(path) != .pmdata && (repositoryStates[path] != "different" || localRemainingIssues[path] != nil || done.contains(path)) { return workflowStatus(path) }
        if (busy || batchAccepting) && outputPath == path { return action == "accept" ? "正在写入" : "生成待合入" }
        if blocked.contains(path) { return workflowStatus(path) }
        if done.contains(path) { return entries[path]?.same == true ? "已同步 · 内容相同" : "已同步 · 已写入本地" }
        if skipped.contains(path) { return "已忽略" }
        if let entry = entries[path], entry.status == "ready" { return entry.canResume ? (entry.lowRisk ? "低风险 · 可批量确认" : "高风险 · 需打开确认") : "需重新合入" }
        return SyncMergeType.classify(path) == .pmdata ? "xtools 导出" : "待合入"
    }
    private struct ReviewLedger: Decodable { let items: [String: SyncReviewEntry]; let pending: String? }
    func load(repair: Bool = false) throws {
        let ledgerURL = folder.appendingPathComponent("review.json")
        let decodedLedger = FileManager.default.fileExists(atPath: ledgerURL.path)
            ? try JSONDecoder().decode(ReviewLedger.self, from: Data(contentsOf: ledgerURL)) : nil
        loadingSelection = true
        defer { loadingSelection = false }
        let previousResult = (try? Data(contentsOf: folder.appendingPathComponent("remaining-last.json")))
            .flatMap { try? JSONDecoder().decode(RemainingDiffResult.self, from: $0) }
        let previouslyChecked = Set((previousResult?.noDiffPaths ?? []) + (previousResult?.differentPaths ?? []) + Array((previousResult?.errors ?? [:]).keys))
        // Local-only recovery runs before comparison paths are exposed to the UI.
        // This also materializes records inherited by carryRecords in a new batch.
        if repair, FileManager.default.fileExists(atPath: folder.appendingPathComponent("review.json").path),
           let resources = Bundle.main.resourceURL,
           FileManager.default.fileExists(atPath: resources.appendingPathComponent("branch_sync.py").path) {
            let invocation = try PythonRuntime.invocation(resources: resources, arguments: [
                resources.appendingPathComponent("branch_sync.py").path, "repair-review", "--folder", folder.path
            ])
            _ = try CommandRunner().run(
                executable: invocation.executable,
                arguments: invocation.arguments
            ).checked()
        }
        let nextReport = try JSONDecoder().decode(SyncReport.self, from: Data(contentsOf: folder.appendingPathComponent("report.json")))
        let reportData = try Data(contentsOf: folder.appendingPathComponent("report.json"))
        let digest = SHA256.hash(data: reportData).map { String(format: "%02x", $0) }.joined()
        if remainingReportDigest != digest {
            retainedVisiblePaths.removeAll()
            verifiedNoDiffPaths = []; repositoryStates = [:]; localStates = [:]; localRemainingIssues = [:]
            currentRemainingIssues = [:]; remainingCheckedPaths = []; remainingReportDigest = digest
        }
        verifiedNoDiffPaths = []; repositoryStates = [:]; localStates = [:]; localRemainingIssues = [:]; currentRemainingIssues = [:]
        report = nextReport
        watchAcceptedResults()
        entries = [:]; done = []; skipped = []; blocked = []; fileOutputs = [:]; interrupted = false
        reviewFailures = (try? JSONDecoder().decode([String: String].self, from: Data(contentsOf: folder.appendingPathComponent("review-failures.json")))) ?? [:]
        if let ledger = decodedLedger {
            entries = ledger.items; interrupted = ledger.pending != nil
            done = Set(entries.values.filter { $0.status == "accepted" }.map(\.path))
            skipped = Set(entries.values.filter { $0.status == "skipped" }.map(\.path))
            fileOutputs = entries.mapValues(\.summary)
            for entry in entries.values where entry.status == "ready" && !entry.canResume {
                fileOutputs[entry.path] = "作者隔离规则已更新。旧副本已保留，请重新生成副本并核对。\n\n" + entry.summary
            }
            if interrupted { output = "上次写入未完成，请检查 Release 现场与本地原件备份；不会自动重试。"; activity = "需检查现场"; outputState = "blocked" }
        } else if let data = try? Data(contentsOf: folder.appendingPathComponent("session.json")),
                  let ledger = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            interrupted = ledger["pending"] != nil
            if interrupted { output = "旧版合入有未完成写入，请先核对原会话现场。"; activity = "需检查现场"; outputState = "blocked" }
        }
        let savedIgnores = (try? JSONDecoder().decode([String: [Int]].self, from: Data(contentsOf: folder.appendingPathComponent("ignored-files.json")))) ?? [:]
        ignoredRevisions = savedIgnores.filter { path, revisions in files.contains { $0.path == path && $0.revisions == revisions } && !done.contains(path) }
        loadWorkflow()
        reviewFailures = reviewFailures.filter { !done.contains($0.key) && !skipped.contains($0.key) }
        // Earlier versions rejected even an exact local copy of the candidate.
        // Reopen only that specific failure; accept still rechecks live SVN state.
        // A stale version warning must not hide a candidate accepted by the
        // current engine contract. Other failures still require fresh evidence.
        reviewFailures = reviewFailures.filter { path, reason in
            !(entries[path]?.canResume == true
              && reason == "作者隔离规则已更新，请重新生成并核对；旧副本已保留。")
        }
        reviewFailures = reviewFailures.filter { path, reason in
            !(entries[path]?.canResume == true && entries[path]?.localMatchesCandidate == true
              && reason == "Release 文件有本地修改或异常状态。请先查看并处理本地修改，再重新生成并核对；也可跳过此文件继续。待合入副本已保留。")
        }
        for (path, reason) in reviewFailures { blocked.insert(path); fileOutputs[path] = reason }
        for entry in entries.values where entry.preparationIssue != nil && !skipped.contains(entry.path) {
            blocked.insert(entry.path)
            if reviewFailures[entry.path] == nil { fileOutputs[entry.path] = entry.preparationIssue }
        }
        for path in repositoryStates.keys where repositoryStates[path] == "different"
            && ["accepted", "invalidated"].contains(entries[path]?.status ?? "") {
            blocked.remove(path)
        }
        if let data = try? Data(contentsOf: folder.appendingPathComponent("remaining-last.json")),
           let saved = try? JSONDecoder().decode(RemainingDiffResult.self, from: data) {
            applyRemaining(saved)
        }
        for path in invalidatedLocalPaths {
            localStates.removeValue(forKey: path); repositoryStates.removeValue(forKey: path)
            verifiedNoDiffPaths.remove(path); done.remove(path)
        }
        if !restoredSelection {
            if let data = try? Data(contentsOf: folder.appendingPathComponent("selection.json")),
               let saved = try? JSONDecoder().decode([String].self, from: data) {
                selectedPaths = Set(saved)
            } else {
                selectedPaths = Set(entries.values.filter { $0.status == "ready" }.map(\.path))
            }
            restoredSelection = true
        }
        selectedPaths.formIntersection(Set(listedFiles.filter { canSelect($0.path) }.map(\.path)))
        reviewSelectedPaths.formIntersection(Set(readyPaths))
        if repair && !workspaceExport && !interrupted {
            pendingLocalChecks.formUnion(previouslyChecked.filter { path in
                repositoryStates[path] == nil && files.contains { $0.path == path && $0.mergeType != .pmdata }
            })
            scheduleResultCheck()
        }
        if !availableExtensions.contains(typeFilter) { typeFilter = "" }
        pruneFilteredSelection()
        UserDefaults.standard.set(folder.path, forKey: "SvnFlow.branchSyncReport.v1")
    }
    private func command(_ action: String, folder: URL, path: String? = nil, sheet: String? = nil, row: Int? = nil, watch: Bool = true, reviewHash: String? = nil, workbooks: [String] = [], verificationPaths: [String] = [], scopeDirectories: [String]? = nil, scopePreview: URL? = nil, scopeRevisions: [Int]? = nil) async throws -> String {
        guard let resources = Bundle.main.resourceURL else { throw NSError(domain: "Sync", code: 1, userInfo: [NSLocalizedDescriptionKey: "缺少合入运行环境"]) }
        let script = resources.appendingPathComponent("branch_sync.py")
        var arguments = [script.path, action, "--folder", folder.path]
        if ["catalog", "authors"].contains(action) { arguments += ["--author", author, "--days", String(days)] }
        for directory in scopeDirectories ?? [] { arguments += ["--scope-directory", directory] }
        for revision in scopeRevisions ?? [] { arguments += ["--scope-revision", String(revision)] }
        if let scopePreview { arguments += ["--scope-preview", scopePreview.path] }
        if let path { arguments += ["--path", path] }
        if let sheet, let row { arguments += ["--sheet", sheet, "--row", String(row)] }
        if ["accept", "accept-low", "xtools-export", "xtools-local-export"].contains(action) { arguments.append("--confirm") }
        if let reviewHash { arguments += ["--review-hash", reviewHash, "--confirm"] }
        for workbook in workbooks { arguments += ["--workbook", workbook] }
        for verificationPath in verificationPaths { arguments += ["--verify-path", verificationPath] }
        // The supervisor only supports preparation, never confirmed Release writes.
        let args = ["catalog", "stage", "regenerate", "assess", "remaining-diff"].contains(action)
            ? [resources.appendingPathComponent("sync_progress.py").path] + arguments : arguments
        let invocation = try PythonRuntime.invocation(resources: resources, arguments: args)
        let token = UUID().uuidString
        var environment = ProcessInfo.processInfo.environment
        environment["SVNFLOW_PROGRESS_TOKEN"] = token
        let childEnvironment = environment
        if watch { progress.watch(folder: folder, token: token, action: action, path: path) }
        defer { if watch { progress.stopWatching() } }
        return try await Task.detached {
            try CommandRunner().run(executable: invocation.executable, arguments: invocation.arguments, environment: childEnvironment).checked().outputText
        }.value
    }
    func autoLoad() async {
        guard canChangeBatch, matchesScope, !uncheckedPaths.isEmpty else { return }
        let paths = uncheckedPaths
        busy = true; outputPath = nil
        progress.beginBatch(total: paths.count)
        defer { busy = false; progress.finish() }
        do { try await checkRemainingDiff(paths: paths) }
        catch {
            output = error.localizedDescription
            activity = progress.cancelling ? "核验已停止 · 点击刷新继续" : "核验未完成 · 请查看原因或刷新重试"
        }
    }
    func verifyRemaining(_ path: String) async {
        guard canChangeBatch, matchesScope, files.contains(where: { $0.path == path }) else { return }
        let inspectedPath = path
        busy = true; outputPath = path
        progress.beginBatch(total: 0)
        defer {
            busy = false; progress.finish()
            // Keep the inspected object visible even when it is now hidden as no-diff.
            if files.contains(where: { $0.path == inspectedPath }) { selection = inspectedPath }
        }
        do {
            _ = try await command("repair-review", folder: folder, watch: false)
            try load(repair: false)
            try await checkRemainingDiff(paths: [path])
            output = "当前文件核验结果已更新，其他文件的已有结果与副本已保留。"
        } catch {
            output = error.localizedDescription
            activity = progress.cancelling ? "核验已停止 · 可继续核验" : "核验未完成 · 可重新核验"
            outputState = "blocked"
        }
    }

    private func checkRemainingDiff(paths: [String]? = nil) async throws {
        if let paths, paths.isEmpty { return }
        remainingCheckedPaths = []; remainingCheckFailed = false
        remainingRequestedPaths = paths.map { Set($0) }
        progress.verificationScope = paths.map { $0.count == 1 ? "当前文件核验" : "所选文件核验" }
        action = "remaining-diff"; activity = "核验当前 \(targetName) · 保留上次结果，逐文件复核"
        let generation = localChangeGeneration
        progress.onRemaining = { [weak self] result in
            guard let self, self.localChangeGeneration == generation else { return }
            self.invalidatedLocalPaths.subtract(result.noDiffPaths + result.differentPaths)
            self.applyRemaining(result)
        }
        defer { progress.onRemaining = nil }
        do {
            let value = try await command("remaining-diff", folder: folder,
                                          path: paths?.count == 1 ? paths?.first : nil,
                                          verificationPaths: paths ?? [])
            try Task.checkCancellation()
            guard generation == localChangeGeneration else {
                throw NSError(domain: "Sync", code: 1, userInfo: [NSLocalizedDescriptionKey: "核验期间本地文件发生变化，请重新核验。"])
            }
            let result = try JSONDecoder().decode(RemainingDiffResult.self, from: Data(value.utf8))
            invalidatedLocalPaths.subtract(result.noDiffPaths + result.differentPaths)
            applyRemaining(result)
            pruneFilteredSelection()
            activity = "已核验 Release r\(result.snapshot) · 隐藏已合入且本地正常 \(hiddenNoDiffCount) 个"
            outputState = result.errors.isEmpty ? "success" : "blocked"
        } catch {
            remainingCheckFailed = !progress.cancelling && !Task.isCancelled
            throw error
        }
    }
    // Carry only records for the exact same author revisions. Candidate batches stay immutable.
    private func carryRecords(to destination: URL, excluding excludedPath: String? = nil) throws {
        guard let previous = report else { return }
        let next = try JSONDecoder().decode(SyncReport.self, from: Data(contentsOf: destination.appendingPathComponent("report.json")))
        guard previous.config.author == next.config.author, previous.config.days == next.config.days,
              previous.config.dev == next.config.dev, previous.config.release == next.config.release,
              previous.config.target == next.config.target,
              previous.config.scopeRevisions == next.config.scopeRevisions else { return }
        let oldRevisions = Dictionary(uniqueKeysWithValues: previous.files.map { ($0.path, $0.revisions) })
        let unchanged = Set(next.files.filter { oldRevisions[$0.path] == $0.revisions }.map(\.path))
        try JSONEncoder().encode(ignoredRevisions.filter { unchanged.contains($0.key) && $0.key != excludedPath })
            .write(to: destination.appendingPathComponent("ignored-files.json"), options: .atomic)
        let ledgerURL = destination.appendingPathComponent("review.json")
        if let data = try? Data(contentsOf: folder.appendingPathComponent("review.json")),
           let oldLedger = try JSONSerialization.jsonObject(with: data) as? [String: Any],
           let items = oldLedger["items"] as? [String: Any] {
            var ledger = try JSONSerialization.jsonObject(with: Data(contentsOf: ledgerURL)) as! [String: Any]
            ledger["items"] = items.filter { unchanged.contains($0.key) && $0.key != excludedPath }
            try JSONSerialization.data(withJSONObject: ledger).write(to: ledgerURL, options: .atomic)
        }
        try JSONEncoder().encode(reviewFailures.filter { unchanged.contains($0.key) })
            .write(to: destination.appendingPathComponent("review-failures.json"), options: .atomic)
    }
    func refresh() async {
        guard canRefresh else { return }
        guard report != nil else { activity = "请先确认合入范围"; return }
        busy = true; action = "refresh"; outputPath = nil
        progress.beginBatch(total: files.count)
        defer { busy = false; progress.finish() }
        do {
            try load(repair: false)
            try await checkRemainingDiff()
        } catch {
            activity = progress.cancelling ? "核验已停止 · 点击刷新继续" : "核验未完成 · 已保留成功结果，请刷新重试"
            output = error.localizedDescription
        }
    }
    func applyScope(author: String, days: Int, directories: [String]? = nil, preview: URL? = nil, revisions: [Int]? = nil) async {
        guard revisions == nil || revisions?.isEmpty == false else { activity = "请选择至少一条 SVN 提交记录"; return }
        guard directories == nil || directories?.isEmpty == false else { activity = "请选择至少一个合并目录"; return }
        guard canChangeBatch, (1...365).contains(days), !author.isEmpty else { return }
        let previousAuthor = self.author, previousDays = self.days, previousFolder = folder
        self.author = author; self.days = days
        busy = true; action = "catalog"; activity = "正在读取本轮文件清单"; outputPath = nil
        progress.beginBatch(total: 0)
        defer { busy = false; progress.finish() }
        do {
            if report != nil { try await preserveRound() }
            let destination = backupRoot.appendingPathComponent("轮次-" + UUID().uuidString)
            _ = try await command("catalog", folder: destination, scopeDirectories: directories, scopePreview: preview, scopeRevisions: revisions)
            try carryRecords(to: destination)
            _ = try await command("repair-review", folder: destination, watch: false)
            folder = destination; restoredSelection = false; writeBatch = nil; retainedWriteCandidates = []
            try load(repair: false)
            activity = "范围已保存 · 正在核验 Release"
            UserDefaults.standard.set(author, forKey: "SvnFlow.syncAuthor.v1")
            UserDefaults.standard.set(days, forKey: "SvnFlow.syncDays.v1")
            do { try await checkRemainingDiff(paths: uncheckedPaths) }
            catch {
                activity = progress.cancelling ? "核验已停止 · 范围已保存，点击刷新继续" : "范围已保存 · 核验未完成，请刷新重试"
                output = error.localizedDescription
            }
        } catch {
            folder = previousFolder; self.author = previousAuthor; self.days = previousDays
            activity = "读取清单未完成 · 原轮次保留"; output = error.localizedDescription
        }
    }

    func restoreRound(_ url: URL) {
        guard canChangeBatch else { return }
        let previous = folder
        do {
            // Decode first so a broken historical record cannot replace the current round.
            let saved = try JSONDecoder().decode(SyncReport.self, from: Data(contentsOf: url.appendingPathComponent("report.json")))
            folder = url; restoredSelection = false; writeBatch = nil; retainedWriteCandidates = []
            try load(repair: false)
            author = saved.config.author; days = saved.config.days ?? 30
            activity = "已恢复本轮记录 · 生成与确认前按需复核"
        } catch { folder = previous; activity = "无法恢复该轮次：" + error.localizedDescription }
    }

    private func preserveRound() async throws {
        guard !folder.path.hasPrefix(backupRoot.path + "/") else { return }
        let source = folder
        let destination = backupRoot.appendingPathComponent("恢复轮次-" + UUID().uuidString)
        try await Task.detached {
            try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try FileManager.default.copyItem(at: source, to: destination)
        }.value
        folder = destination
        // repair-review safely materializes inherited absolute candidate paths.
        _ = try await command("repair-review", folder: destination, watch: false)
        try load(repair: false)
    }

    func merge(regenerating path: String? = nil, only: String? = nil) async {
        let retrying = path.map { blocked.contains($0) && !done.contains($0) && !skipped.contains($0) } == true
        guard canMerge || ((retrying || only.map(canSelect) == true) && canChangeBatch && matchesScope) else { return }
        let paths = retrying ? [path!] : only.map { [$0] } ?? migrationPaths
        regenerationPaths = retrying ? Set(paths) : []
        busy = true; action = "remaining-diff"; activity = "核验所选文件"; outputPath = nil
        progress.beginBatch(total: paths.count)
        defer { busy = false; progress.finish() }
        do {
            try await preserveRound()
            _ = try await command("repair-review", folder: folder, watch: false)
            try load(repair: false)
            try await checkRemainingDiff(paths: paths)
            // Only requested, still-unprocessed files enter the new generation batch.
            selectedPaths = Set(paths.filter { repositoryStates[$0] == "different" && localRemainingIssues[$0] == nil && !done.contains($0) && !skipped.contains($0) })
            for path in selectedPaths { blocked.remove(path); reviewFailures.removeValue(forKey: path) }
            saveReviewFailures()
            queue = paths.filter { selectedPaths.contains($0) }
            try JSONEncoder().encode(queue).write(to: folder.appendingPathComponent("selection.json"), options: .atomic)
            if progress.cancelling { queue = []; activity = "已取消生成 · 副本与日志已保留"; return }
            await prepareNext()
        } catch { output = error.localizedDescription; activity = "合入已停止"; outputState = "blocked" }
    }
    @Published var stopAfterCurrentWrite = false
    @Published var writeBatch: SyncWriteBatch?
    // A stopped, explicitly confirmed batch may return untouched candidates to
    // selection even when our own writes invalidated the display-only SVN cache.
    private var retainedWriteCandidates = Set<String>()
    func requestStopWriting() {
        guard batchAccepting else { return }
        stopAfterCurrentWrite = true
        writeBatch?.state = .stopping
    }
    func returnToWriteSelection() {
        guard canChangeBatch else { return }
        if let batch = writeBatch {
            retainedWriteCandidates = Set(batch.paths.filter { batch.outcomes[$0] == nil })
            reviewSelectedPaths = retainedWriteCandidates
        }
        writeBatch = nil
    }
    func cancelGeneration() { progress.cancelGeneration() }
    var lowRiskPaths: [String] {
        // A stopped, explicitly confirmed queue survives display-evidence invalidation.
        // The accept command still rechecks every retained candidate before writing.
        files.filter { file in
            (visibleFiles.contains { $0.path == file.path } || retainedWriteCandidates.contains(file.path))
                && !hasNoDiff(file)
                && (directory.isEmpty || file.path.hasPrefix(directory + "/"))
                && (typeFilter.isEmpty || file.fileExtension == typeFilter)
                && (filter.isEmpty || file.path.localizedCaseInsensitiveContains(filter))
        }.map(\.path).filter { path in
            let candidate = !interrupted && !blocked.contains(path) && !done.contains(path) && !skipped.contains(path)
                && entries[path]?.canResume == true && entries[path]?.preparationIssue == nil && entries[path]?.lowRisk == true
            return candidate && (isReady(path) || retainedWriteCandidates.contains(path))
        }
    }
    var selectedLowRiskPaths: [String] { lowRiskPaths.filter { reviewSelectedPaths.contains($0) } }
    func confirmLowRisk() async {
        guard canChangeBatch else { return }
        let paths = selectedLowRiskPaths
        guard !paths.isEmpty else { return }
        stopAfterCurrentWrite = false
        batchAccepting = true
        writeBatch = SyncWriteBatch(paths: paths, target: report?.config.target ?? "Release")
        progress.beginBatch(total: paths.count)
        defer {
            writeBatch?.currentPath = nil
            writeBatch?.ended = Date()
            if writeBatch?.active == true {
                writeBatch?.state = writeBatch?.completed == paths.count ? .completed : .stopped
            }
            activity = (writeBatch?.title ?? "") + " · " + (writeBatch?.summary ?? "")
            batchAccepting = false
            progress.finish()
        }
        for path in paths {
            // The confirmed queue is independent of working-copy display caches.
            // Every accept-low still checks live content, properties and history.
            if stopAfterCurrentWrite { break }
            guard !interrupted, !blocked.contains(path), !done.contains(path), !skipped.contains(path),
                  entries[path]?.canResume == true, entries[path]?.preparationIssue == nil,
                  entries[path]?.lowRisk == true else {
                writeBatch?.state = interrupted ? .interrupted : .failed
                writeBatch?.failedPath = path
                writeBatch?.outcomes[path] = .failed
                writeBatch?.failure = "该文件已不满足确认条件，请返回文件列表核验；后续文件未开始。"
                progress.failures += 1
                break
            }
            writeBatch?.currentPath = path
            activity = "批量写入 · 第 \((writeBatch?.completed ?? 0) + 1) / \(paths.count) 个"
            do {
                try await decide(path, accept: true, lowRisk: true)
                writeBatch?.outcomes[path] = entries[path]?.acceptedExisting == true ? .existing : .written
                progress.completed += 1
            } catch {
                writeBatch?.outcomes[path] = .failed
                writeBatch?.failedPath = path
                writeBatch?.failure = error.localizedDescription
                writeBatch?.state = interrupted ? .interrupted : .failed
                progress.failures += 1
                break
            }
            writeBatch?.currentPath = nil
        }
    }
    func openReview(_ paths: [String]) {
        guard canChangeBatch else { return }
        queue = paths.filter { isReady($0) }
        showNext()
    }
    func prepareNext() async {
        reviewing = false; busy = true
        defer { busy = false; queue = []; progress.finish() }
        let paths = queue
        progress.beginBatch(total: paths.count)
        for path in paths {
            if progress.cancelling { activity = "已取消生成 · 副本与日志已保留"; return }
            if blocked.contains(path) || repositoryStates[path] != "different" || localRemainingIssues[path] != nil || done.contains(path) || skipped.contains(path) { continue }
            selection = path; outputPath = path; action = "stage"
            activity = "生成副本并评估风险 · \((path as NSString).lastPathComponent)"
            output = "正在准备整批文件并评估风险，完成后可在外层批量确认低风险文件。"
            do {
                if regenerationPaths.contains(path) || !isReady(path) || entries[path]?.risk == nil {
                    let operation = regenerationPaths.contains(path) ? "regenerate" : isReady(path) ? "assess" : entries[path] == nil ? "stage" : "regenerate"
                    let value = try await command(operation, folder: folder, path: path)
                    let entry = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(value.utf8))
                    entries[path] = entry; fileOutputs[path] = entry.summary
                    if entry.same && entry.localMatchesCandidate && entry.local?.preventsAccept == false { verifiedNoDiffPaths.insert(path) }
                    selectedPaths.remove(path)
                    if let issue = entry.preparationIssue {
                        blocked.insert(path); reviewFailures[path] = issue; fileOutputs[path] = issue
                        saveReviewFailures()
                    }
                }
            } catch {
                fileOutputs[path] = error.localizedDescription; output = error.localizedDescription
                if progress.cancelling {
                    try? load()
                    activity = "已取消生成 · 副本与日志已保留"; return
                }
                blocked.insert(path); reviewFailures[path] = error.localizedDescription; saveReviewFailures()
            }
            progress.completed += 1; progress.failures = blocked.count
            if progress.cancelling { activity = "生成已暂停"; return }
        }
        queue = []
        let ready = paths.filter { isReady($0) }.count
        let waiting = paths.filter { isTemporarilyBlocked($0) }.count
        let problems = paths.filter { blocked.contains($0) && !isTemporarilyBlocked($0) }.count
        activity = "本批结束 · \(ready) 个副本可核对 · \(waiting) 个任务占用 · \(problems) 个需要处理"
        outputState = blocked.isEmpty ? "success" : "blocked"
    }
    func showNext() {
        guard let path = queue.first, let entry = entries[path], isReady(path) else {
            reviewing = false; activity = blocked.isEmpty ? "本批处理完成" : "本批结束 · 有文件需处理"; return
        }
        reviewing = true; selection = path; activity = "等待确认 · 剩余 \(queue.count) 个文件"
        let actions = ComparisonReviewActions(title: "合入确认 · 剩余 \(queue.count) 个文件", summary: entry.summary,
            accept: { [weak self] in try await self?.decide(path, accept: true) },
            skip: { [weak self] in try await self?.decide(path, accept: false) },
            next: { [weak self] in
                guard let self else { return }; self.queue.removeFirst()
                self.showNext()
            },
            pause: { [weak self] in self?.reviewing = false; self?.activity = "确认已暂停 · 可从风险列表继续打开对比" })
        actions.progress = progress
        actions.targetPath = URL(fileURLWithPath: report?.config.target ?? "Release").appendingPathComponent(path).path
        actions.resultSummary = { [weak self] in self?.fileOutputs[path] ?? "已确认，尚未提交 SVN。" }
        actions.confirmationHint = entry.confirmationHint
        actions.withdrawnRows = Dictionary(grouping: entry.withdrawnRows ?? [], by: \.sheet).mapValues { Set($0.map(\.row)) }
        actions.withdrawRow = { [weak self, weak actions] sheet, row in
            guard let self else { throw NSError(domain: "Sync", code: 1, userInfo: [NSLocalizedDescriptionKey: "合入会话已关闭"]) }
            let value = try await self.command("withdraw-row", folder: self.folder, path: path, sheet: sheet, row: row)
            let updated = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(value.utf8))
            self.entries[path] = updated; self.fileOutputs[path] = updated.summary
            actions?.confirmationHint = updated.confirmationHint
            actions?.withdrawnRows = Dictionary(grouping: updated.withdrawnRows ?? [], by: \.sheet).mapValues { Set($0.map(\.row)) }
            return updated.summary
        }
        if path.lowercased().hasSuffix(".lua") {
            actions.loadTextReview = { [weak self] in
                guard let self else { throw NSError(domain: "Sync", code: 1) }
                let value = try await self.command("text-review", folder: self.folder, path: path)
                return try JSONDecoder().decode(TextReviewInfo.self, from: Data(value.utf8))
            }
            actions.chooseText = { [weak self, weak actions] key, side in
                guard let self else { throw NSError(domain: "Sync", code: 1) }
                let value = try await self.command("choose-text", folder: self.folder, path: path, sheet: key, row: side)
                let updated = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(value.utf8))
                self.entries[path] = updated; self.fileOutputs[path] = updated.summary
                actions?.confirmationHint = updated.confirmationHint
                return updated.summary
            }
        }
        QueryWindows.shared.compare(path, files: ComparisonFiles(old: entry.baseline, new: entry.candidate,
            oldLabel: "Release SVN · r\(entry.revision)" + (entry.baseline == nil ? " · 文件不存在" : ""),
            newLabel: "待合入" + (entry.candidate == nil ? " · 删除文件" : "")), review: actions)
    }
    private func decide(_ path: String, accept: Bool, lowRisk: Bool = false) async throws {
        busy = true; action = accept ? "accept" : "defer"; outputPath = path
        if !batchAccepting { progress.beginBatch(total: 0) }
        defer { busy = false; if !batchAccepting { progress.finish() } }
        do {
            progress.activity = nil
            progress.phase = "准备批次记录与写入前校验"
            try await preserveRound()
            _ = try await command("repair-review", folder: folder, watch: false)
            let value = try await command(lowRisk ? "accept-low" : action, folder: folder, path: path)
            let entry = try JSONDecoder().decode(SyncReviewEntry.self, from: Data(value.utf8))
            entries[path] = entry
            blocked.remove(path); reviewFailures.removeValue(forKey: path); saveReviewFailures()
            if accept { done.insert(path); recordAcceptedExcel() } else { skipped.insert(path) }
            selectedPaths.remove(path); reviewSelectedPaths.remove(path)
            output = accept ? (entry.acceptedExisting == true ? "已确认：本地内容已与待合入结果一致，未重复写入，尚未提交 SVN。" : "已确认并写入本地 Release，尚未提交 SVN。") : "暂不合入，副本仍保留在备份目录。"
            fileOutputs[path] = output; outputState = "success"
        } catch {
            let reason = error.localizedDescription
            reviewFailures[path] = reason; saveReviewFailures()
            try? load()
            blocked.insert(path); output = reason; outputState = "blocked"
            fileOutputs[path] = reason
            throw error
        }
    }
}

struct SyncDirectoryNode: Identifiable {
    let id: String
    let name: String
    let count: Int
    let children: [SyncDirectoryNode]?

    static func build(_ files: [SyncReport.FileItem], parent: String = "") -> [Self] {
        let prefix = parent.isEmpty ? "" : parent + "/"
        let groups = Dictionary(grouping: files.filter { $0.path.hasPrefix(prefix) && $0.directory != parent }) {
            String($0.path.dropFirst(prefix.count).split(separator: "/").first ?? "")
        }
        return groups.keys.sorted { $0.localizedStandardCompare($1) == .orderedAscending }.map { name in
            let path = prefix + name
            let members = groups[name] ?? []
            let children = build(members, parent: path)
            return Self(id: path, name: name, count: members.count, children: children.isEmpty ? nil : children)
        }
    }
    func matching(_ query: String) -> Self? {
        if query.isEmpty || id.localizedCaseInsensitiveContains(query) { return self }
        let matches = children?.compactMap { $0.matching(query) } ?? []
        return matches.isEmpty ? nil : Self(id: id, name: name, count: count, children: matches)
    }
}

/// Read the cell's actual system highlight, including keyboard focus and inactive windows.
private struct SyncTableForeground: ViewModifier {
    @Environment(\.backgroundProminence) private var prominence
    let normal: Color

    func body(content: Content) -> some View {
        content.foregroundStyle(prominence == .increased ? Color.white : normal)
    }
}

struct BranchSyncWindow: View {
    @ObservedObject var model: BranchSyncModel
    @ObservedObject var progress: SyncProgressModel
    private enum Sheet: Identifiable {
        case workflow, activity, history, backups, detail(String)
        var id: String {
            switch self {
            case .history: return "history"
            case .backups: return "backups"
            case .workflow: return "workflow"
            case .activity: return "activity"
            case .detail(let tab): return "detail-" + tab
            }
        }
    }
    @State private var activeSheet: Sheet?
    @State private var showScope = false
    @State private var showSelectedOnly = false
    @State private var directorySearch = ""
    @State private var highlightedPaths = Set<String>()
    @State private var workflowDraftLoaded = false
    @AppStorage("SvnFlow.syncStatusFilter.v2") private var statusFilter = "全部"
    private let accent = SyncOrbit.cyan
    init(model: BranchSyncModel) { self.model = model; self.progress = model.progress }
    private let workflowFilters = ["待确认", "低风险", "已完成"]
    private var readyCount: Int { model.visibleFiles.filter { model.isReady($0.path) }.count }
    private var selectedVisible: [String] { model.visibleFiles.map(\.path).filter { model.selectedPaths.contains($0) } }
    private var selectedRetryPaths: [String] { selectedVisible.filter { model.isTemporarilyBlocked($0) } }
    private var selectedReviewPaths: [String] { selectedVisible.filter { model.isReady($0) } }
    private var selectedProblemPaths: [String] { selectedVisible.filter { model.workflowStatus($0) == "需要处理" } }
    private var displayed: [SyncReport.FileItem] {
        model.visibleFiles.filter { (!showSelectedOnly || model.selectedPaths.contains($0.path)) && model.matchesConfirmationFilter($0.path, filter: statusFilter) }
    }
    private var currentBusy: Bool { model.busy && (model.outputPath == nil || model.outputPath == model.selection) }
    private var currentBlocked: Bool { model.selection.map { model.blocked.contains($0) } == true }
    private var stage: Int {
        if currentBusy { return model.action == "accept" ? 3 : ["catalog", "authors"].contains(model.action) ? 0 : 1 }
        guard let path = model.selection else { return 0 }
        if model.done.contains(path) { return 4 }
        if currentBlocked { return 1 }
        if model.isReady(path) { return 2 }
        return model.report == nil ? 0 : 1
    }
    var body: some View {
        VStack(spacing: 0) {
            header
            if let config = model.report?.config, config.scopeTotal != nil {
                VStack(alignment: .leading, spacing: 4) {
                    Text("本轮范围：" + (config.scopeDirectories?.joined(separator: "、") ?? "全部目录"))
                        .font(.system(size: 12, weight: .medium)).textSelection(.enabled)
                    if let revisions = config.scopeRevisions {
                        Text("本轮所选 SVN：" + revisions.map { "r\($0)" }.joined(separator: "、"))
                            .font(.system(size: 11)).textSelection(.enabled).lineLimit(2)
                            .help(revisions.map { "r\($0)" }.joined(separator: "、"))
                    }
                    Text("待核验范围 \(model.files.filter { $0.mergeType != .pmdata }.count) 个文件 · \(config.scopeExcluded ?? 0) 个文件未纳入本轮")
                        .font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 26).padding(.vertical, 8)
            }
            HStack(spacing: 12) {
                Text(model.lastRefresh)
                Text("显示本轮已保存记录；生成与确认前复核所选文件，新提交请新建轮次。")
                Spacer(minLength: 0)
            }.font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                .padding(.horizontal, 26).padding(.bottom, 10)
            Rectangle().fill(SyncOrbit.line).frame(height: 1)
            HSplitView {
                directoryList.frame(minWidth: 170, idealWidth: 200, maxWidth: 280)
                fileList.frame(minWidth: 570, maxWidth: .infinity)
                inlineDetail.frame(minWidth: 290, idealWidth: 320, maxWidth: 400)
            }
            Rectangle().fill(SyncOrbit.line).frame(height: 1)
            footer
        }
        .background(SyncOrbit.background).foregroundStyle(SyncOrbit.text)
        .tint(accent).environment(\.colorScheme, .light)
        .sheet(item: $activeSheet) { sheet in
            switch sheet {
            case .history: SyncRoundHistory(model: model) { activeSheet = nil }
            case .backups: SyncBackupPanel(model: model)
            case .workflow: workflowPanel
            case .activity:
                SyncActivityDrawer(progress: progress, summary: model.activity, author: model.author,
                                   snapshot: model.report?.config.snapshot, close: { activeSheet = nil })
            case .detail(let initialTab):
                if initialTab == "同步确认" {
                    if model.writeBatch != nil {
                        SyncBatchWritePanel(model: model, progress: progress, close: { activeSheet = nil }, inspectFailure: {
                            model.selection = model.writeBatch?.failedPath
                            activeSheet = .detail("处理进度")
                        })
                    } else {
                        batchReviewPanel
                    }
                } else {
                    SyncFocusedDetail(model: model, progress: progress, close: { activeSheet = nil }, export: {
                        prepareWorkflowDraft()
                        activeSheet = .workflow
                    })
                }
            }
        }

        .onAppear { statusFilter = BranchSyncModel.migratedConfirmationFilter(statusFilter) }
        .task(id: model.folder.path) { await model.autoLoad() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.scheduleResultCheck()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            model.scheduleResultCheck()
        }
        .onChange(of: model.author) { _, value in UserDefaults.standard.set(value, forKey: "SvnFlow.syncAuthor.v1") }
        .onChange(of: model.days) { _, value in UserDefaults.standard.set(value, forKey: "SvnFlow.syncDays.v1") }
    }
    private var header: some View {
        HStack(spacing: 22) {
            HStack(spacing: 12) {
                Image(systemName: "arrow.triangle.branch").font(.system(size: 24, weight: .light))
                    .foregroundStyle(accent).frame(width: 44, height: 44)
                    .background(accent.opacity(0.025), in: Circle())
                    .overlay { Circle().strokeBorder(accent.opacity(0.3)) }
                VStack(alignment: .leading, spacing: 5) {
                    Text("分支合入").font(.system(size: 20, weight: .semibold))
                    Text(model.directionTitle).font(.system(size: 12)).foregroundStyle(SyncOrbit.muted)
                }
            }
            Spacer(minLength: 0)
            Text("生成副本 → 核对确认 → 写入本地").font(.system(size: 12)).foregroundStyle(SyncOrbit.muted)
            Spacer(minLength: 0)
            HStack(spacing: 8) {
                Button { activeSheet = .activity } label: { Label("活动", systemImage: "waveform.path") }
                    .help("查看任务上下文和实时活动记录")
                Button { Task { await model.refresh() } } label: { Label("刷新", systemImage: "arrow.clockwise") }
                    .disabled(!model.canRefresh).help(model.refreshHelp).accessibilityLabel("刷新文件列表")
                Menu("轮次与备份") {
                    Button("历史轮次") { activeSheet = .history }
                    Button("本轮备份记录") { activeSheet = .backups }
                }.disabled(!model.canChangeBatch)
                Button("新建轮次") { showScope.toggle() }.disabled(!model.canChangeBatch)
                    .help("选择作者与时间范围，旧轮次及副本保留")
                    .sheet(isPresented: $showScope) { SyncScopeView(model: model) { showScope = false } }
            }.buttonStyle(SyncOrbitButton())
        }.padding(.horizontal, 26).padding(.vertical, 18).background(SyncOrbit.sidebar)
    }
    private var inlineDetail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("当前文件").font(.caption).foregroundStyle(.secondary)
                if let file = model.current {
                    Text(file.name).font(.headline).textSelection(.enabled)
                    Text(file.directory).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    Divider()
                    Text(model.executionStage(file.path)).font(.headline)
                    Text(model.shortReason(file.path)).font(.callout).textSelection(.enabled)
                    if model.isProcessingFile(file.path) {
                        Text(progress.activity?.phase ?? progress.phase).font(.caption)
                        if !["accept", "accept-low"].contains(model.action) {
                            Button(progress.cancelling ? "正在停止…" : "停止并保留结果") { model.cancelGeneration() }.disabled(progress.cancelling)
                        }
                    } else if model.isReady(file.path) {
                        Button("查看差异并确认") { model.openReview([file.path]) }.buttonStyle(.borderedProminent).disabled(!model.canChangeBatch)
                    } else {
                        Button("核验此文件") { Task { await model.verifyRemaining(file.path) } }.disabled(!model.canChangeBatch)
                        Button("生成此文件副本") {
                            Task { await model.merge(only: file.path) }
                        }.disabled(!model.canChangeBatch || !model.canSelect(file.path))
                    }
                    Button("查看本轮备份") { activeSheet = .backups }.disabled(!model.canChangeBatch)
                    Button("完整文件详情") { activeSheet = .detail("处理进度") }
                    Divider()
                    Text("写入前复核目标状态并保存原件。\n本地写入与 SVN 提交分别确认。")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("选择文件查看处理进度与下一步。")
                }
            }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
        }.background(SyncOrbit.panel)
    }
    private var workflowPanel: some View {
        ConfigurationExportPanel(model: model) { activeSheet = nil }
    }
    private var directoryList: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("目录").font(.headline).padding(.top, 24)
            TextField("搜索目录或路径", text: $directorySearch).textFieldStyle(.roundedBorder)
            Button {
                model.directory = ""
            } label: {
                HStack {
                    Label("全部目录", systemImage: "folder")
                    Spacer()
                    Text("\(model.listedFiles.count)").monospacedDigit()
                }.padding(9).background(model.directory.isEmpty ? WorkbenchTheme.selection : .clear)
            }.buttonStyle(.plain)
            List(selection: Binding<String?>(get: { model.directory.isEmpty ? nil : model.directory }, set: { model.directory = $0 ?? "" })) {
                OutlineGroup(SyncDirectoryNode.build(model.listedFiles).compactMap { $0.matching(directorySearch) }, children: \.children) { node in
                    HStack(spacing: 7) {
                        Image(systemName: "folder").foregroundStyle(accent)
                        Text(node.name).lineLimit(1)
                        Spacer(minLength: 4)
                        Text("\(node.count)").font(.caption).monospacedDigit().foregroundStyle(SyncOrbit.muted)
                    }.tag(node.id).help(node.id)
                }
            }.listStyle(.sidebar).scrollContentBackground(.hidden)
            Text("选择目录查看其下全部文件，包含子目录。")
                .font(.caption).foregroundStyle(SyncOrbit.muted).padding(.bottom, 18)
        }.padding(.horizontal, 14).background(SyncOrbit.sidebar)
    }
    private var fileList: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(displayed.count) 个文件").font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                        Text(model.directory.isEmpty ? "本轮处理文件" : (model.directory as NSString).lastPathComponent)
                            .font(.system(size: 22, weight: .semibold))
                        Text(model.directory.isEmpty ? model.verificationSummary : model.directory)
                            .font(.caption).foregroundStyle(SyncOrbit.muted).lineLimit(1).truncationMode(.head)
                    }
                    Spacer()
                    Button("配置导出（\(model.pendingExports.count)）") {
                        prepareWorkflowDraft(); activeSheet = .workflow
                    }.buttonStyle(SyncOrbitButton()).disabled(!model.canChangeBatch)
                    Button("文件详情") { activeSheet = .detail("处理进度") }.buttonStyle(SyncOrbitButton()).disabled(model.current == nil)
                }
                HStack(spacing: 12) {
                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass").foregroundStyle(SyncOrbit.muted)
                        TextField("搜索文件名或路径", text: $model.filter).textFieldStyle(.plain)
                    }.padding(9).background(SyncOrbit.panel, in: RoundedRectangle(cornerRadius: 5))
                    Picker("类型", selection: $model.typeFilter) {
                        Text("全部类型").tag("")
                        ForEach(model.availableExtensions, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden().frame(width: 125)
                }
                VStack(alignment: .leading, spacing: 5) {
                    Text("先核验 → 生成副本 → 查看差异并确认 → 写入本地").font(.system(size: 12))
                    Text("写入本地后仍需提交 SVN；分类只影响显示，不会触发合入。")
                        .font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                }
                HStack(spacing: 4) {
                        statusButton("全部", count: model.visibleFiles.count)
                        ForEach(workflowFilters, id: \.self) { state in
                            statusButton(state, count: model.visibleFiles.filter { model.matchesConfirmationFilter($0.path, filter: state) }.count)
                        }
                        Spacer(minLength: 16)
                        statusButton("已忽略", count: model.visibleFiles.filter { model.statusCategory($0.path) == .ignored }.count)
                }
                HStack(spacing: 8) {
                    Menu("选择文件") {
                        Button("全选当前列表") { model.selectedPaths.formUnion(displayed.filter { model.canSelect($0.path) }.map(\.path)) }
                        Button("取消选择当前列表") { model.selectedPaths.subtract(displayed.map(\.path)) }
                        Button("清空全部选择") { model.selectedPaths.removeAll() }
                    }.fixedSize()
                    Button(showSelectedOnly ? "显示全部" : "查看所选（\(model.selectedPaths.count)）") {
                        showSelectedOnly.toggle()
                        if showSelectedOnly { model.directory = ""; model.filter = ""; model.typeFilter = ""; statusFilter = "全部" }
                    }.disabled(model.selectedPaths.isEmpty && !showSelectedOnly)
                    Button("忽略所选（\(model.ignorablePaths.count)）") { model.setIgnored(true) }
                        .disabled(model.ignorablePaths.isEmpty)
                    Button("恢复所选") { model.setIgnored(false) }.disabled(model.restorablePaths.isEmpty)
                    Spacer(minLength: 0)
                    Button("选择全部剩余文件") {
                        model.directory = ""; model.filter = ""; model.typeFilter = ""; statusFilter = "全部"
                        model.selectRemaining()
                    }
                        .help("跨全部目录和筛选，选中未同步、未忽略的文件；pmdata 仍使用 xtools 导出")
                }.buttonStyle(SyncOrbitButton()).disabled(!model.canChangeBatch)
            }.padding(22)
            // Row focus is independent of eligibility for batch operations.
            Table(displayed, selection: $highlightedPaths) {
                TableColumn("选择") { file in
                    Toggle("选择 \(file.name)", isOn: Binding(get: { model.selectedPaths.contains(file.path) }, set: { model.toggle(file.path, checked: $0) }))
                        .labelsHidden().toggleStyle(.checkbox).disabled(!model.canChangeBatch || !model.canSelect(file.path))
                }.width(38)
                TableColumn("名称") { file in
                    Label(file.name, systemImage: file.mergeType.symbol).lineLimit(1)
                        .modifier(SyncTableForeground(normal: SyncOrbit.text))
                        .help("双击查看处理详情：" + file.path)
                }.width(min: 180, ideal: 240)
                TableColumn("确认状态") { file in
                    Text(model.displayStage(file.path))
                        .modifier(SyncTableForeground(normal: model.confirmationCategory(file.path) == "已忽略" ? SyncOrbit.muted : ["低风险", "已完成"].contains(model.confirmationCategory(file.path)) ? SyncOrbit.green : accent))
                }.width(76)
                TableColumn("相对目录") { file in
                    Text(file.directory.isEmpty ? "根目录" : file.directory).modifier(SyncTableForeground(normal: SyncOrbit.muted))
                        .lineLimit(1).truncationMode(.head).help(file.path)
                }.width(min: 100, ideal: 160)
                TableColumn("最新版本") { file in Text("r\(file.latestRevision)").monospacedDigit().modifier(SyncTableForeground(normal: SyncOrbit.text)) }.width(80)
            }
            .onChange(of: highlightedPaths) { old, new in
                if let path = new.subtracting(old).sorted().first ?? new.sorted().first {
                    model.selection = path
                }
            }
            .onChange(of: displayed.map(\.path)) { _, paths in
                highlightedPaths.formIntersection(Set(paths))
            }
            .contextMenu(forSelectionType: String.self) { paths in
                if let path = paths.sorted().first {
                    Button("查看处理详情") { model.selection = path; activeSheet = .detail("处理进度") }
                }
            } primaryAction: { paths in
                if let path = paths.sorted().first { model.selection = path; activeSheet = .detail("处理进度") }
            }
            .overlay {
                if displayed.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "tray").font(.title2)
                        Text(model.files.isEmpty ? "点击“新建轮次”选择作者和时间范围" : model.listedFiles.isEmpty ? model.verificationSummary : "“\(statusFilter)”中暂无匹配文件")
                        if !model.uncheckedPaths.isEmpty && !model.busy {
                            Button("继续核验") { Task { await model.refresh() } }.disabled(!model.canRefresh)
                        }
                        if statusFilter != "全部" { Button("返回全部分类") { statusFilter = "全部" } }
                        if !model.files.isEmpty {
                            Button("清除筛选") { model.filter = ""; model.typeFilter = ""; statusFilter = "全部"; model.directory = ""; showSelectedOnly = false }
                        }
                    }.foregroundStyle(SyncOrbit.muted)
                }
            }
            HStack {
                Text("已选 \(model.selectedPaths.count) 个 · 其中当前列表 \(displayed.filter { model.selectedPaths.contains($0.path) }.count) 个")
                Spacer()
                Text("已忽略 \(model.listedFiles.filter { model.skipped.contains($0.path) }.count) 个 · 共 \(model.listedFiles.count) 个 · 已隐藏无差异 \(model.hiddenNoDiffCount) 个")
            }.font(.caption).foregroundStyle(SyncOrbit.muted).padding(16)
        }.background(SyncOrbit.background)
    }
    private func statusButton(_ name: String, count: Int) -> some View {
        Button { statusFilter = name } label: {
            Text("\(name) \(count)").font(.system(size: 11, weight: .medium))
                .foregroundStyle(statusFilter == name ? accent : SyncOrbit.muted)
                .padding(.horizontal, 9).padding(.vertical, 7)
                .fixedSize()
                .background(statusFilter == name ? WorkbenchTheme.selection : .clear, in: RoundedRectangle(cornerRadius: 5))
                .overlay { RoundedRectangle(cornerRadius: 5).strokeBorder(statusFilter == name ? accent : .clear) }
        }.buttonStyle(.plain).accessibilityAddTraits(statusFilter == name ? .isSelected : [])
    }
    private var batchReviewPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                WorkbenchHeading(eyebrow: "", title: "确认批量写入", subtitle: "确认范围 → 连续写入 → 查看结果", symbol: "checkmark.shield")
                Spacer()
                WorkbenchCloseButton(hint: "返回文件列表，保留核对选择") { activeSheet = nil }
            }.padding(24)
            Divider()
            ScrollView { readyNotice.padding(24) }
            Divider()
            HStack {
                Text(model.busy ? model.activity : "确认仅写入本地，不会提交 SVN").foregroundStyle(SyncOrbit.muted)
                Spacer()
                Button("确认并写入所选 \(model.selectedLowRiskPaths.count) 个文件") { Task { await model.confirmLowRisk() } }
                    .buttonStyle(SyncOrbitButton(prominent: true))
                    .disabled(!model.canChangeBatch || model.selectedLowRiskPaths.isEmpty)
            }.font(.system(size: 12)).padding(18)
        }.frame(width: 840, height: 640).workbenchStyle().workbenchSecondarySurface()
    }
    private func prepareWorkflowDraft() {
        guard !workflowDraftLoaded else { return }
        workflowDraftLoaded = true
    }
    private var readyNotice: some View {
        let high = model.visibleFiles.map(\.path).filter { model.isReady($0) && model.entries[$0]?.lowRisk != true }
        return VStack(alignment: .leading, spacing: 12) {
            Text("目标：\(model.report?.config.target ?? (model.targetName + " 本地工作副本"))")
                .font(.caption).foregroundStyle(SyncOrbit.muted).textSelection(.enabled)
            if !high.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Label("高风险 \(high.count) 个文件 · 必须打开对比确认", systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(WorkbenchTheme.danger)
                    Text("可能存在覆盖冲突、结构变化或尚未完成核验，不能批量确认。")
                        .font(.caption)
                    Button("打开高风险文件逐个确认 ↗") { model.openReview(high) }
                        .buttonStyle(SyncOrbitButton())
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                    .background(WorkbenchTheme.danger.opacity(0.14), in: RoundedRectangle(cornerRadius: 7))
                    .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(WorkbenchTheme.danger) }
            }
            Text("当前筛选低风险 \(model.lowRiskPaths.count) 个 · 已选 \(model.selectedLowRiskPaths.count) 个")
                .foregroundStyle(SyncOrbit.green)
            HStack {
                Button("全选当前低风险") { model.reviewSelectedPaths = Set(model.lowRiskPaths) }
                Button("清空确认选择") { model.reviewSelectedPaths.removeAll() }
            }.buttonStyle(SyncOrbitButton())
            if let path = model.selection, let entry = model.entries[path], model.isReady(path) {
                Text((entry.risk?.reasons ?? ["尚未完成风险评估，需打开对比核对"]).joined(separator: "；"))
                    .font(.caption).foregroundStyle(entry.lowRisk ? SyncOrbit.green : WorkbenchTheme.danger)
                Button("打开当前文件对比确认 ↗") { model.openReview([path]) }.buttonStyle(SyncOrbitButton())
            }
            Text("一次确认后按列表顺序写入本地 \(model.targetName)；每个文件重新校验，异常时停止后续写入。尚不提交 SVN。")
                .font(.caption).foregroundStyle(SyncOrbit.muted)
            if model.lowRiskPaths.isEmpty {
                Text("当前没有可批量确认的低风险文件，请返回列表生成副本或处理需核对的文件。")
                    .font(.caption).foregroundStyle(SyncOrbit.muted)
            }
            LazyVStack(alignment: .leading, spacing: 10) {
            ForEach(model.lowRiskPaths, id: \.self) { path in
                Toggle(path, isOn: Binding(get: { model.reviewSelectedPaths.contains(path) }, set: {
                    if $0 { model.reviewSelectedPaths.insert(path) } else { model.reviewSelectedPaths.remove(path) }
                })).toggleStyle(.checkbox).font(.caption)
            }
            }
        }.disabled(!model.canChangeBatch)
    }
    private func openPendingDetails() {
        model.directory = ""; model.filter = ""; model.typeFilter = ""; model.pendingOnly = false
        directorySearch = ""
        statusFilter = "全部"
        model.selection = model.readyPaths.first
        activeSheet = .detail("同步确认")
    }
    private func performNextStep(_ path: String) {
        model.selection = path
        if model.skipped.contains(path) || model.isProcessingFile(path) { activeSheet = .detail("处理进度"); return }
        switch model.workflowStatus(path) {
        case "待核验": Task { await model.verifyRemaining(path) }; activeSheet = .detail("处理进度")
        case "暂时受阻": Task { await model.retry(path) }
        case "可确认", "待核对": model.openReview([path])
        case "待合入": model.selectedPaths = [path]; Task { await model.merge() }
        case "待导出": prepareWorkflowDraft(); activeSheet = .workflow
        default: activeSheet = .detail("处理进度")
        }
    }
    private var footer: some View {
        HStack(spacing: 13) {
            if model.busy { ProgressView().controlSize(.small).tint(accent) }
            else { Image(systemName: model.reviewing ? "circle.dotted" : "checkmark.shield").foregroundStyle(accent) }
            if model.busy, model.action == "remaining-diff", let total = progress.activity?.filesTotal {
                Text("已核验 \(progress.activity?.filesCompleted ?? 0)/\(total) 个文件").monospacedDigit()
            }
            Text(model.batchAccepting ? (model.writeBatch?.summary ?? model.activity) : model.busy ? progress.phase + (model.action == "remaining-diff" ? " · 保留上次结果，逐文件复核" : "") : model.reviewing ? "等待你在对比窗口确认" : model.activity)
                .font(.system(size: 12)).lineLimit(1)
            if let start = progress.started {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    let seconds = max(0, Int((progress.ended ?? context.date).timeIntervalSince(start)))
                    Text(String(format: "已用时 %d:%02d", seconds / 60, seconds % 60)).monospacedDigit().foregroundStyle(SyncOrbit.muted)
                }.font(.system(size: 11))
            }
            Spacer()
            if model.writeBatch != nil {
                Button(model.batchAccepting ? "查看批量写入进度" : "查看本批写入结果") { activeSheet = .detail("同步确认") }
                    .buttonStyle(SyncOrbitButton())
            }
            if model.busy {
                if ["stage", "catalog", "remaining-diff"].contains(model.action) {
                    Button(progress.cancelling ? "正在取消…" : ["catalog", "remaining-diff"].contains(model.action) ? "取消读取" : "取消生成") { model.cancelGeneration() }
                        .buttonStyle(SyncOrbitButton()).disabled(progress.cancelling)
                }
            } else if model.reviewing {
                Button("返回对比 ↗") { model.showNext() }.buttonStyle(SyncOrbitButton(prominent: true))
            } else {
                if !model.readyPaths.isEmpty {
                    Button("待确认（\(model.readyPaths.count)）") { openPendingDetails() }.buttonStyle(SyncOrbitButton())
                }
                if !selectedProblemPaths.isEmpty {
                    Button("查看处理原因（\(selectedProblemPaths.count)）") {
                        model.selection = selectedProblemPaths.first; activeSheet = .detail("处理进度")
                    }.buttonStyle(SyncOrbitButton()).disabled(!model.canChangeBatch)
                }
                if !selectedReviewPaths.isEmpty {
                    Button("核对所选（\(selectedReviewPaths.count)）") { model.openReview(selectedReviewPaths) }
                        .buttonStyle(SyncOrbitButton()).disabled(!model.canChangeBatch)
                }
                if !selectedRetryPaths.isEmpty {
                    Button("重试所选（\(selectedRetryPaths.count)）") {
                        let paths = selectedRetryPaths
                        Task { await model.retryTemporarilyBlocked(paths) }
                    }.buttonStyle(SyncOrbitButton(prominent: true)).disabled(!model.canChangeBatch || !model.matchesScope)
                }
                if !model.migrationPaths.isEmpty || selectedVisible.isEmpty {
                    Button("生成副本（\(model.migrationPaths.count)）") { Task { await model.merge() } }
                        .buttonStyle(SyncOrbitButton(prominent: true)).disabled(!model.canMerge)
                }
            }
        }.padding(.horizontal, 26).padding(.vertical, 13).background(SyncOrbit.panel)
    }
}
