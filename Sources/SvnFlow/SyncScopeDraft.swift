import Foundation
import SwiftUI
import CryptoKit
import SVNCore

/// A draft survives dismissing the scope sheet and never changes the active round.
@MainActor final class SyncScopeDraft: ObservableObject {
    static let excel = "Client/CommonRes/Table/Design"
    static let lua = "Client/Assets/Script/Lua"
    @Published var author = ""
    @Published var dayOption = 30
    @Published var customDays = "30"
    @Published var authorSearch = ""
    @Published var authors: [String] = []
    @Published var loadingAuthors = false
    @Published var authorFailure: String?
    @Published var loadedDays: Int?
    @Published var allDirectories = true { didSet { if oldValue != allDirectories { invalidateCheck() } } }
    @Published var directories: Set<String> = [] { didSet { if oldValue != directories { invalidateCheck() } } }
    @Published var commitSearch = "" { didSet { if oldValue != commitSearch { selectedRevisions = [] } } }
    @Published var selectedRevisions: Set<Int> = [] { didSet { if oldValue != selectedRevisions { invalidateCheck() } } }
    @Published var preview: SyncReport?
    @Published var reading = false
    @Published var failure: String?
    @Published var checking = false
    @Published var checkResult: RemainingDiffResult?
    @Published var checkFailure: String?
    @Published var inherited = false
    @Published var directorySearch = ""
    private(set) var previewFolder: URL?
    private var request: Task<Void, Never>?
    private var generation = UUID()
    private var workspaceKey = ""
    private var initialized = false
    static let presets = [1, 3, 7, 14, 30, 60, 90, 180, 365]
    var days: Int? { (dayOption == 0 ? Int(customDays) : dayOption).flatMap { (1...365).contains($0) ? $0 : nil } }
    private var currentWorkspaceKey: String {
        let data = Data((UserDefaults.standard.string(forKey: "SvnFlow.fixedCopies.v1") ?? "").utf8)
        return "SvnFlow.scopeDirectories.v1." + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    func setup(author: String, days: Int) {
        guard !initialized || workspaceKey != currentWorkspaceKey else { return }
        cancelRead(); discardPreview()
        initialized = true; workspaceKey = currentWorkspaceKey
        self.author = author; dayOption = Self.presets.contains(days) ? days : 0; customDays = String(days)
        authors = []; loadedDays = nil
        if let saved = UserDefaults.standard.stringArray(forKey: workspaceKey) {
            allDirectories = saved.isEmpty; directories = Set(saved); inherited = true
        } else { allDirectories = true; directories = []; inherited = false }
    }
    var canRead: Bool { days != nil && loadedDays == days && authors.contains(author) && !loadingAuthors && authorFailure == nil && !reading && !checking }
    var previewMatches: Bool {
        preview != nil && preview?.config.author == author && preview?.config.days == days && workspaceKey == currentWorkspaceKey
    }
    var normalizedDirectories: [String] {
        directories.sorted().reduce(into: []) { result, path in
            if !result.contains(where: { path == $0 || path.hasPrefix($0 + "/") }) { result.append(path) }
        }
    }
    func contains(_ path: String) -> Bool { allDirectories || normalizedDirectories.contains { path == $0 || path.hasPrefix($0 + "/") } }
    var commits: [SyncReport.Commit] { previewMatches ? (preview?.dev ?? []).sorted { $0.revision > $1.revision } : [] }
    var visibleCommits: [SyncReport.Commit] {
        let query = commitSearch.trimmingCharacters(in: .whitespacesAndNewlines)
        return commits.filter { query.isEmpty || $0.message.localizedCaseInsensitiveContains(query) || "r\($0.revision)".localizedCaseInsensitiveContains(query) }
    }
    var effectiveRevisions: [Int] { commits.filter { selectedRevisions.contains($0.revision) }.map(\.revision).sorted() }
    func selectSearchResults() { selectedRevisions = Set(visibleCommits.map(\.revision)) }
    private func includesRevision(_ file: SyncReport.FileItem) -> Bool { !selectedRevisions.isDisjoint(with: file.revisions) }
    var total: Int { preview?.fileItems?.filter { $0.mergeType != .pmdata }.count ?? 0 }
    var selectedCount: Int { previewMatches ? (preview?.fileItems ?? []).filter { $0.mergeType != .pmdata && contains($0.path) && includesRevision($0) }.count : 0 }
    var selectedFiles: [SyncReport.FileItem] {
        previewMatches ? (preview?.fileItems ?? []).filter { $0.mergeType != .pmdata && contains($0.path) && includesRevision($0) } : []
    }
    var mergedPaths: Set<String> {
        guard let result = checkResult, result.complete == true else { return [] }
        return Set(result.noDiffPaths.filter { result.localIssues?[$0] == nil && result.localStates?[$0] == "same" })
    }
    var remainingCount: Int { selectedFiles.filter { !mergedPaths.contains($0.path) }.count }
    var selectedPMData: Int { previewMatches ? (preview?.fileItems ?? []).filter { $0.mergeType == .pmdata && contains($0.path) && includesRevision($0) }.count : 0 }
    var availableDirectories: [String] {
        var paths = Set([Self.excel, Self.lua]).union(directories)
        for item in preview?.fileItems ?? [] {
            var parts = item.path.split(separator: "/").map(String.init)
            if !parts.isEmpty { parts.removeLast() }
            while !parts.isEmpty { paths.insert(parts.joined(separator: "/")); parts.removeLast() }
        }
        return paths.sorted().filter { directorySearch.isEmpty || $0.localizedCaseInsensitiveContains(directorySearch) }
    }
    func choose(_ directory: String?) { allDirectories = directory == nil; directories = directory.map { [$0] } ?? [] }
    func remember() { UserDefaults.standard.set(allDirectories ? [] : normalizedDirectories, forKey: workspaceKey) }
    func invalidateCheck() {
        checkResult = nil; checkFailure = nil
        if checking { generation = UUID(); request?.cancel(); request = nil; checking = false }
    }
    func cancelRead() { generation = UUID(); request?.cancel(); request = nil; reading = false; checking = false; checkResult = nil; checkFailure = nil }
    func checkSelection() {
        guard canRead, previewMatches, !checking, selectedCount > 0, let days, let previewFolder else { return }
        cancelRead(); checking = true
        let id = UUID(), selectedAuthor = author, workspace = currentWorkspaceKey
        generation = id
        let folder = previewFolder.appendingPathComponent("check-" + id.uuidString)
        let revisions = effectiveRevisions, scope = allDirectories ? nil : normalizedDirectories
        request = Task {
            defer { try? FileManager.default.removeItem(at: folder) }
            do {
                let text = try await SyncScopeReader.run(action: "scope-check", days: days, author: selectedAuthor, folder: folder,
                    preview: previewFolder.appendingPathComponent("scope-preview.json"), directories: scope, revisions: revisions)
                try Task.checkCancellation()
                guard generation == id, author == selectedAuthor, self.days == days, currentWorkspaceKey == workspace else { return }
                let result = try JSONDecoder().decode(RemainingDiffResult.self, from: Data(text.utf8))
                guard result.complete == true else { throw NSError(domain: "Sync", code: 1, userInfo: [NSLocalizedDescriptionKey: "核验未完成，请重试"] ) }
                checkResult = result; checking = false; request = nil
            } catch {
                if generation == id { checking = false; request = nil; if !Task.isCancelled { checkFailure = error.localizedDescription } }
            }
        }
    }
    private func discardPreview() {
        if let previewFolder { try? FileManager.default.removeItem(at: previewFolder) }
        previewFolder = nil; preview = nil; selectedRevisions = []
    }
    func readPreview() {
        guard canRead, let days else { return }
        cancelRead(); discardPreview(); failure = nil; reading = true
        let selectedAuthor = author, id = UUID(), selectedWorkspace = currentWorkspaceKey
        generation = id
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("SvnFlow-scope-" + id.uuidString)
        request = Task {
            do {
                let text = try await SyncScopeReader.run(action: "scope-preview", days: days, author: selectedAuthor, folder: folder)
                try Task.checkCancellation()
                guard generation == id, self.days == days, author == selectedAuthor, currentWorkspaceKey == selectedWorkspace else {
                    try? FileManager.default.removeItem(at: folder); if generation == id { reading = false }; return
                }
                preview = try JSONDecoder().decode(SyncReport.self, from: Data(text.utf8))
                previewFolder = folder; reading = false; request = nil
            } catch {
                try? FileManager.default.removeItem(at: folder)
                if generation == id { reading = false; request = nil; if !Task.isCancelled { failure = error.localizedDescription } }
            }
        }
    }
    func readAuthors() async {
        guard let days else { loadingAuthors = false; return }
        if loadedDays == days && authorFailure == nil { return }
        loadingAuthors = true; authorFailure = nil
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("SvnFlow-authors-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        do {
            let text = try await SyncScopeReader.run(action: "authors", days: days, folder: folder)
            try Task.checkCancellation()
            guard self.days == days else { return }
            authors = try JSONDecoder().decode([String].self, from: Data(text.utf8)); loadedDays = days
            if !authors.contains(author) { author = "" }
            loadingAuthors = false
        } catch {
            if !Task.isCancelled && self.days == days { authorFailure = error.localizedDescription; loadingAuthors = false }
        }
    }
}

private enum SyncScopeReader {
    static func run(action: String, days: Int, author: String = "", folder: URL, preview: URL? = nil, directories: [String]? = nil, revisions: [Int] = []) async throws -> String {
        guard let resources = Bundle.main.resourceURL else {
            throw NSError(domain: "Sync", code: 1, userInfo: [NSLocalizedDescriptionKey: "缺少合入运行环境"])
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let token = UUID().uuidString
        let marker = folder.appendingPathComponent("cancel-" + token)
        var environment = ProcessInfo.processInfo.environment; environment["SVNFLOW_PROGRESS_TOKEN"] = token
        let childEnvironment = environment
        var args = [resources.appendingPathComponent("sync_progress.py").path, resources.appendingPathComponent("branch_sync.py").path,
                    action, "--folder", folder.path, "--days", String(days), "--author", author]
        if let preview { args += ["--scope-preview", preview.path] }
        if let directories { for path in directories { args += ["--scope-directory", path] } }
        for revision in revisions { args += ["--scope-revision", String(revision)] }
        let arguments = args
        let invocation = try PythonRuntime.invocation(resources: resources, arguments: arguments)
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            let result = try await Task.detached {
                try CommandRunner().run(executable: invocation.executable, arguments: invocation.arguments, environment: childEnvironment).checked().outputText
            }.value
            try Task.checkCancellation()
            return result
        } onCancel: { try? Data().write(to: marker, options: .atomic) }
    }
}
