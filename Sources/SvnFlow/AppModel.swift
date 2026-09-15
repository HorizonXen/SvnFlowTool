import AppKit
import CoreServices
import Combine
import Foundation
import SwiftUI
import SVNCore

extension Notification.Name {
    static let mainPerspective = Notification.Name("SvnFlow.mainPerspective")
    static let reviewPerspective = Notification.Name("SvnFlow.reviewPerspective")
    static let openWorkingCopy = Notification.Name("SvnFlow.openWorkingCopy")
    static let checkoutWorkingCopy = Notification.Name("SvnFlow.checkoutWorkingCopy")
    static let closeWorkingCopy = Notification.Name("SvnFlow.closeWorkingCopy")
    static let refreshWorkingCopy = Notification.Name("SvnFlow.refreshWorkingCopy")
    static let updateWorkingCopy = Notification.Name("SvnFlow.updateWorkingCopy")
    static let commitChanges = Notification.Name("SvnFlow.commitChanges")
    static let addSelected = Notification.Name("SvnFlow.addSelected")
    static let removeSelected = Notification.Name("SvnFlow.removeSelected")
    static let moveSelected = Notification.Name("SvnFlow.moveSelected")
    static let revertSelected = Notification.Name("SvnFlow.revertSelected")
    static let deleteSelected = Notification.Name("SvnFlow.deleteSelected")
    static let switchWorkingCopy = Notification.Name("SvnFlow.switchWorkingCopy")
    static let createBranch = Notification.Name("SvnFlow.createBranch")
    static let mergeChanges = Notification.Name("SvnFlow.mergeChanges")
    static let compareFile = Notification.Name("SvnFlow.compareFile")
    static let showLog = Notification.Name("SvnFlow.showLog")
    static let showProperties = Notification.Name("SvnFlow.showProperties")
    static let showAnnotate = Notification.Name("SvnFlow.showAnnotate")
    static let lockSelected = Notification.Name("SvnFlow.lockSelected")
    static let unlockSelected = Notification.Name("SvnFlow.unlockSelected")
    static let showRepository = Notification.Name("SvnFlow.showRepository")
    static let cleanupWorkingCopy = Notification.Name("SvnFlow.cleanupWorkingCopy")
}

struct WorkingCopy: Identifiable, Codable, Hashable, Sendable {
    var id = UUID()
    var name: String
    var path: String
    var url: String
    var branch: String
    var revision: String
}

extension ItemState {
    var title: String {
        switch self {
        case .modified: L("已修改")
        case .added: L("待新增")
        case .deleted: L("待删除")
        case .replaced: L("已替换")
        case .conflicted: L("有冲突")
        case .missing: L("本地缺失")
        case .unversioned: L("未纳入版本")
        case .ignored: L("已忽略")
        case .normal: L("正常")
        case .external: L("外部引用")
        case .incomplete: L("不完整")
        case .obstructed: L("被阻挡")
        case .unknown: L("未知")
        }
    }
    var icon: String {
        switch self {
        case .conflicted, .obstructed: "exclamationmark.triangle.fill"
        case .modified, .replaced: "pencil.circle.fill"
        case .added, .unversioned: "plus.circle.fill"
        case .deleted, .missing: "minus.circle.fill"
        default: "questionmark.circle"
        }
    }
}

struct LogItem: Identifiable, Hashable {
    var id: String { revision }
    let revision: String
    let author: String
    let date: Date?
    let message: String
}

typealias LocalEntry = WorkspaceEntry

enum ToolError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { value } else { L("未知错误") } }
}

actor SVN {
    private func executable() throws -> URL {
        let environmentPaths = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map { String($0) + "/svn" }
        let candidates = [
            "/opt/homebrew/bin/svn",
            "/usr/local/bin/svn",
            "/usr/bin/svn",
            "/Applications/Xcode.app/Contents/Developer/usr/bin/svn"
        ] + environmentPaths
        if let path = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) { return URL(fileURLWithPath: path) }
        throw ToolError.message(T("SVN was not found. Install Subversion (for example: brew install svn).", "未找到 SVN 命令。请先安装 Subversion（例如：brew install svn）。"))
    }
    private func execute(_ args: [String], cwd: String? = nil) throws -> CommandResult {
        try CommandRunner().run(
            executable: executable(), arguments: ["--non-interactive"] + args,
            directory: cwd.map { URL(fileURLWithPath: $0, isDirectory: true) }
        ).checked()
    }
    func run(_ args: [String], cwd: String? = nil) throws -> String {
        try execute(args, cwd: cwd).displayText
    }

    func duplicateCommitTargets(_ paths: [String], cwd: String) throws -> [[String]] {
        var targets: [CommitTarget] = []
        for start in stride(from: 0, to: paths.count, by: 100) {
            let batch = Array(paths[start..<min(start + 100, paths.count)])
            let result = try execute(["info", "--xml", "--depth", "infinity", "--"] + batch.map { $0 + "@" }, cwd: cwd)
            targets += try CommitTargets.parse(result.standardOutput, root: cwd)
        }
        return CommitTargets.duplicates(targets)
    }

    nonisolated func updateOutput(_ path: String) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    try await self.streamUpdate(path) { continuation.yield($0) }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
        }
    }
    private func streamUpdate(_ path: String, onOutput: @escaping @Sendable (Data) -> Void) throws {
        _ = try CommandRunner().run(executable: executable(), arguments: ["--non-interactive", "update", "--accept", "postpone", "--", path + "@"], onOutput: onOutput).checked()
    }
    func info(_ path: String) throws -> WorkingCopy {
        let xml = try execute(["info", "--xml", path]).outputText
        let parser = InfoParser(Data(xml.utf8))
        guard parser.parse(), !parser.url.isEmpty else { throw ToolError.message(T("Not a valid SVN working copy: {0}", "不是有效的 SVN 工作副本：{0}", path)) }
        let parts = parser.url.split(separator: "/").map(String.init)
        let branch: String
        if let i = parts.lastIndex(where: { ["branches", "tags"].contains($0.lowercased()) }), i + 1 < parts.count { branch = parts[i + 1] }
        else if let i = parts.lastIndex(where: { $0.lowercased() == "branch" }), i + 1 < parts.count {
            let next = i + 1
            branch = ["dev", "release", "hotfix"].contains(parts[next].lowercased()) && next + 1 < parts.count ? parts[next + 1] : parts[next]
        } else if parts.contains("trunk") { branch = "trunk" }
        else { branch = "" }
        return WorkingCopy(name: URL(fileURLWithPath: path).lastPathComponent, path: path, url: parser.url, branch: branch, revision: parser.revision)
    }

    func status(_ path: String, root: String? = nil) throws -> [StatusItem] {
        let result = try execute(["status", "--xml", "--verbose", "--no-ignore", "--", path.contains("@") ? path + "@" : path])
        return try WorkingCopyStatus.parse(result.standardOutput, root: root ?? path)
    }

    func exactStatus(_ paths: [String], root: String) throws -> [StatusItem] {
        var items: [StatusItem] = []
        for offset in stride(from: 0, to: paths.count, by: 100) {
            let targets = paths[offset..<min(offset + 100, paths.count)].map { $0 + "@" }
            let result = try execute(["status", "--xml", "--verbose", "--no-ignore", "--ignore-externals", "--depth", "empty", "--"] + targets)
            items += try WorkingCopyStatus.parse(result.standardOutput, root: root)
        }
        return items
    }

    func logs(_ path: String) throws -> [LogItem] {
        let xml = try execute(["log", "--xml", "--limit", "100", "--", path + "@"]).standardOutput
        return try RepositoryXML.history(xml).map { item in
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return LogItem(revision: item.revision, author: item.author, date: formatter.date(from: item.date) ?? ISO8601DateFormatter().date(from: item.date), message: item.message)
        }
    }
}

final class InfoParser: NSObject, XMLParserDelegate {
    private let parser: XMLParser
    private var current = ""
    var url = "", revision = ""
    init(_ data: Data) { parser = XMLParser(data: data); super.init(); parser.delegate = self }
    func parse() -> Bool { parser.parse() }
    func parser(_ p: XMLParser, didStartElement e: String, namespaceURI: String?, qualifiedName: String?, attributes a: [String:String] = [:]) { current = e; if e == "entry" { revision = a["revision"] ?? "" } }
    func parser(_ p: XMLParser, foundCharacters s: String) { if current == "url" { url += s } }
    func parser(_ p: XMLParser, didEndElement e: String, namespaceURI: String?, qualifiedName: String?) { current = "" }
}

final class LogParser: NSObject, XMLParserDelegate {
    private let parser: XMLParser
    private var current = "", revision = "", author = "", date = "", message = ""
    var items: [LogItem] = []
    init(_ data: Data) { parser = XMLParser(data: data); super.init(); parser.delegate = self }
    func parse() -> Bool { parser.parse() }
    func parser(_ p: XMLParser, didStartElement e: String, namespaceURI: String?, qualifiedName: String?, attributes a: [String:String] = [:]) {
        current = e
        if e == "logentry" { revision = a["revision"] ?? ""; author = ""; date = ""; message = "" }
    }
    func parser(_ p: XMLParser, foundCharacters s: String) {
        switch current { case "author": author += s; case "date": date += s; case "msg": message += s; default: break }
    }
    func parser(_ p: XMLParser, didEndElement e: String, namespaceURI: String?, qualifiedName: String?) {
        if e == "logentry" { items.append(LogItem(revision: revision, author: author, date: ISO8601DateFormatter().date(from: date), message: message)) }
        current = ""
    }
}

@MainActor final class Model: ObservableObject {
    @Published var copies: [WorkingCopy] = []
    @Published var selectedID: UUID? { didSet { if !isUIPreview { UserDefaults.standard.set(selectedID?.uuidString, forKey: "SvnFlow.fixedSelection.v1") } } }
    @Published var statusEntries: [StatusItem] = [] { didSet { refreshVisibleStatuses() } }
    @Published private(set) var statuses: [StatusItem] = []
    @Published var ignoredPaths = Set(UserDefaults.standard.stringArray(forKey: LocalIgnore.storageKey) ?? [])
    func isHidden(_ path: String) -> Bool { LocalIgnore.contains(path, rules: ignoredPaths) }
    private func refreshVisibleStatuses() { statuses = statusEntries.filter { $0.hasLocalChange && !isHidden($0.path) } }
    func hideLocally(_ path: String) {
        guard let copy = selected, UpdateRefresh.contains(path, in: copy.path), path != copy.path else { return }
        ignoredPaths.insert(path)
        QueryWindows.shared.closeHiddenComparisons(ignoredPaths)
        applyIgnoreRules()
    }
    func restoreLocally(_ paths: [String]) { ignoredPaths.subtract(paths); applyIgnoreRules() }
    private func applyIgnoreRules() {
        UserDefaults.standard.set(ignoredPaths.sorted(), forKey: LocalIgnore.storageKey)
        refreshVisibleStatuses(); indexVersion += 1
        selectedPaths = selectedPaths.filter { !isHidden($0) }
        if let path = selectedEntryID, isHidden(path) { selectedEntryID = nil; diff = L("选择文件查看差异") }
    }
    @Published var selectedPaths = Set<String>()
    @Published var diff = L("选择文件查看差异")
    @Published var logs: [LogItem] = []
    @Published var output = L("就绪")
    @Published var message = ""
    @Published var mergeSource = ""
    @Published var repoEntries: [String] = []
    @Published var restoringCache = false
    @Published var busy = false
    @Published var backgroundValidation = false
    @Published var refreshLabel = T("Refreshing in background", "后台刷新中")
    @Published var updateTiming = ""
    private var validationToken = UUID()
    @Published var updateStage = 0
    @Published var updateCount = 0
    @Published var updateDetail = ""
    @Published var updateStarted = Date()
    @Published var activity = L("正在加载 SVN…")
    @Published var error: String?
    @Published var localEntries: [LocalEntry] = []
    @Published private(set) var directories: [LocalEntry] = []
    @Published private(set) var indexVersion = 0
    private(set) var listingIndex = WorkspaceListingIndex([])
    private struct Snapshot {
        let statuses: [StatusItem]
        let entries: [LocalEntry]
        let directories: [LocalEntry]
        let index: WorkspaceListingIndex
    }
    private var snapshots: [UUID: Snapshot] = [:]
    private var loadedCopy: UUID?
    // Keep every loaded working copy in the sidebar when selection changes.
    var treeDirectories: [UUID: [LocalEntry]] {
        var result = snapshots.mapValues(\.directories)
        if let loadedCopy { result[loadedCopy] = directories }
        return result
    }
    var treeChanges: [UUID: [StatusItem]] {
        var result = snapshots.mapValues { snapshot in
            snapshot.statuses.filter { $0.hasLocalChange && !isHidden($0.path) }
        }
        if let loadedCopy { result[loadedCopy] = statuses }
        return result
    }
    private var refreshRequest = UUID()
    private var scanningCopy: UUID?
    private var monitor: WorkspaceMonitor?
    private var monitorCopy: UUID?
    private var checkpoints: [UUID: UInt64] = [:]
    private var adminStamps: [UUID: String] = [:]
    private var pendingEvents: [String: UInt32] = [:]
    private var eventTask: Task<Void, Never>?
    private var activationRequest = UUID()
    private var cacheTasks: [UUID: Task<Void, Never>] = [:]

    func activateCopy() async {
        guard let c = selected else { monitor?.stop(); monitor = nil; return }
        if loadedCopy == c.id && monitorCopy == c.id { return }
        let token = UUID(); activationRequest = token
        restoringCache = true
        defer { if activationRequest == token { restoringCache = false } }
        refreshRequest = UUID(); scanningCopy = nil
        monitor?.stop(); monitor = nil; monitorCopy = nil
        eventTask?.cancel(); pendingEvents = [:]
        invalidateValidation()
        if snapshots[c.id] == nil, let disk = await WorkspaceSnapshotStore.shared.read(c.id, root: c.path) {
            let index = await Task.detached { WorkspaceListingIndex(disk.entries) }.value
            guard activationRequest == token, selectedID == c.id else { return }
            snapshots[c.id] = Snapshot(statuses: disk.statuses, entries: disk.entries, directories: disk.entries.filter { $0.isDirectory && !$0.relative.isEmpty }, index: index)
            checkpoints[c.id] = disk.eventID; adminStamps[c.id] = disk.adminStamp
        }
        guard activationRequest == token, selectedID == c.id else { return }
        if let cached = snapshots[c.id] {
            statusEntries = cached.statuses; localEntries = cached.entries; directories = cached.directories; listingIndex = cached.index
            loadedCopy = c.id; selectedEntryID = nil; selectedPaths = []; indexVersion += 1
            busy = false
            output = T("Cached state restored; monitoring file changes", "已恢复缓存，正在监听文件变化")
            startMonitor(c)
            if monitor?.active != true || (checkpoints[c.id] ?? 0) > FSEventsGetCurrentEventId() || adminStamps[c.id] != WorkspaceMonitor.adminStamp(c.path) { validateInBackground(c) }
        } else {
            checkpoints[c.id] = FSEventsGetCurrentEventId()
            startMonitor(c)
            restoringCache = false
            await refresh()
        }
    }
    private func startMonitor(_ c: WorkingCopy) {
        monitorCopy = c.id
        monitor = WorkspaceMonitor(root: c.path, since: checkpoints[c.id] ?? FSEventsGetCurrentEventId()) { [weak self] events in
            guard let self, self.selectedID == c.id else { return }
            for (path, flags) in events { self.pendingEvents[path, default: 0] |= flags }
            self.scheduleEvents(c)
        }
    }
    private func scheduleEvents(_ c: WorkingCopy) {
        eventTask?.cancel()
        eventTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
            guard !Task.isCancelled, let self, selectedID == c.id else { return }
            if busy || backgroundValidation || scanningCopy != nil { scheduleEvents(c); return }
            await flushEvents(c)
        }
    }
    private func persistSnapshot(_ c: WorkingCopy) {
        adminStamps[c.id] = WorkspaceMonitor.adminStamp(c.path)
        let value = WorkspaceDiskSnapshot(root: c.path, statuses: statusEntries, entries: localEntries, eventID: checkpoints[c.id] ?? FSEventsGetCurrentEventId(), adminStamp: adminStamps[c.id] ?? "")
        // Serial store writes preserve order; encoding and disk I/O stay off the UI actor.
        cacheTasks[c.id]?.cancel()
        cacheTasks[c.id] = Task {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            await WorkspaceSnapshotStore.shared.write(value, id: c.id)
        }
    }
    private func refreshAffected(_ c: WorkingCopy, paths: [String]) async {
        for path in paths {
            var isDirectory: ObjCBool = false
            let exists = FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory)
            let directory = exists ? isDirectory.boolValue : localEntries.contains { $0.path == path && $0.isDirectory }
            pendingEvents[path, default: 0] |= UInt32(directory ? kFSEventStreamEventFlagItemIsDir : kFSEventStreamEventFlagItemIsFile)
        }
        await flushEvents(c, allowBusy: true)
        if selectedID == c.id, let i = copies.firstIndex(where: { $0.id == c.id }), var latest = try? await svn.info(c.path) {
            latest.id = c.id; copies[i] = latest; save()
        }
    }
    func checkExternalChanges() {
        guard !busy, !backgroundValidation, let c = selected, loadedCopy == c.id else { return }
        if adminStamps[c.id] != WorkspaceMonitor.adminStamp(c.path) { validateInBackground(c) }
    }
    private func flushEvents(_ c: WorkingCopy, allowBusy: Bool = false) async {
        let events = pendingEvents; pendingEvents = [:]
        let dropped = UInt32(kFSEventStreamEventFlagUserDropped | kFSEventStreamEventFlagKernelDropped | kFSEventStreamEventFlagEventIdsWrapped | kFSEventStreamEventFlagRootChanged | kFSEventStreamEventFlagMustScanSubDirs)
        if events.contains(where: { $0.value & dropped != 0 }) || (!allowBusy && adminStamps[c.id] != WorkspaceMonitor.adminStamp(c.path)) {
            validateInBackground(c); return
        }
        let ignored = statusEntries.filter { $0.textState == .ignored }.map(\.path)
        let paths = events.keys.filter { path in UpdateRefresh.contains(path, in: c.path) && !path.split(separator: "/").contains(".svn") && !ignored.contains(where: { UpdateRefresh.contains(path, in: $0) }) }
        guard !paths.isEmpty else { return }
        if paths.count > 512 { validateInBackground(c); return }
        let token = UUID(); validationToken = token; backgroundValidation = true
        refreshLabel = T("Refreshing changed paths", "正在后台刷新变化路径")
        defer { if validationToken == token { backgroundValidation = false } }
        let old = statusEntries, catalog = localEntries
        let initialStamp = WorkspaceMonitor.adminStamp(c.path)
        let directories = paths.filter { events[$0, default: 0] & UInt32(kFSEventStreamEventFlagItemIsDir) != 0 }
        let scopes = directories.filter { p in !directories.contains { $0 != p && UpdateRefresh.contains(p, in: $0) } }
        let exact = paths.filter { p in !scopes.contains { UpdateRefresh.contains(p, in: $0) } }
        do {
            let reader = SVN()
            var fresh = exact.isEmpty ? [] : try await reader.exactStatus(exact, root: c.path)
            var queried = Set(exact)
            for scope in scopes {
                fresh += try await reader.status(scope, root: c.path)
                queried.formUnion(old.filter { UpdateRefresh.contains($0.path, in: scope) }.map(\.path))
                queried.formUnion(catalog.filter { UpdateRefresh.contains($0.path, in: scope) }.map(\.path))
                queried.insert(scope)
            }
            queried.formUnion(fresh.map(\.path))
            let refreshed = fresh, targets = queried
            let patch = await Task.detached(priority: .utility) {
                let value = UpdateRefresh.merge(root: c.path, previous: old, entries: catalog, refreshed: refreshed, queried: targets, deleted: [])
                return (value.0, value.1, WorkspaceListingIndex(value.1))
            }.value
            guard validationToken == token, selectedID == c.id, (!busy || allowBusy) else {
                for (path, flags) in events { pendingEvents[path, default: 0] |= flags }; scheduleEvents(c); return
            }
            if WorkspaceMonitor.adminStamp(c.path) != initialStamp { validateInBackground(c); return }
            publishUpdate(c, statuses: patch.0, entries: patch.1, index: patch.2)
            output = T("Refreshed {0} changed paths", "已局部刷新 {0} 个变化路径", paths.count)
        } catch {
            guard selectedID == c.id, validationToken == token else { return }
            backgroundValidation = false
            validateInBackground(c)
        }
    }


    @Published var selectedEntryID: String?
    @Published var filter = ""
    @Published var showOnlyChanges = false
    @Published var selectedWorkspaceSection = "files"
    @Published var selectedDirectory = ""
    let svn = SVN()
    let key = "SvnFlow.fixedCopies.v1"
    static let devID = MergeEndpointDisplay.sourceID
    static let releaseID = MergeEndpointDisplay.targetID
    static let slots: [(id: UUID, name: String)] = [(devID, "Dev"), (releaseID, "Release")]
    var treeCopies: [WorkingCopy] {
        if isUIPreview { return copies }
        return Self.slots.map { slot in
            var copy = copies.first { $0.id == slot.id } ?? WorkingCopy(id: slot.id, name: slot.name, path: "", url: "", branch: "", revision: "")
            copy.name = (copy.path.isEmpty ? slot.name : copy.pathDisplayName)
                + (copy.path.isEmpty ? T(" — Choose folder…", " — 选择目录…") : "")
            return copy
        }
    }
    var mergeEndpoints: MergeEndpointDisplay {
        MergeEndpointDisplay(
            sourcePath: copies.first(where: { $0.id == Self.devID })?.path ?? "",
            targetPath: copies.first(where: { $0.id == Self.releaseID })?.path ?? ""
        )
    }
    var selectedDisplayName: String {
        guard let selected else { return T("Choose folder", "选择工作副本") }
        return selected.pathDisplayName
    }
    func chooseSlot() -> UUID? {
        let alert = NSAlert()
        alert.messageText = T("Configure SVN folder", "配置 SVN 目录")
        alert.informativeText = T("Choose which fixed entry to configure.", "选择要配置的固定入口。已有路径仅在选择新目录成功后替换。")
        alert.addButton(withTitle: "Dev"); alert.addButton(withTitle: "Release"); alert.addButton(withTitle: L("Cancel"))
        alert.window.level = .modalPanel
        switch alert.runModal() { case .alertFirstButtonReturn: return Self.devID; case .alertSecondButtonReturn: return Self.releaseID; default: return nil }
    }
    func installCopy(_ copy: WorkingCopy, slot: UUID) {
        var value = copy; value.id = slot
        copies.removeAll { $0.id == slot }; copies.append(value)
        copies.sort { $0.id == Self.devID && $1.id != Self.devID }
        snapshots.removeValue(forKey: slot); loadedCopy = nil
        selectedDirectory = ""; selectedEntryID = nil; selectedPaths = []
        selectedID = slot; save()
    }
    func configureSlot(_ slot: UUID) {
        guard !busy, !committing else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.title = T("Choose {0} SVN folder", "选择 {0} SVN 目录", slot == Self.devID ? "Dev" : "Release")
        if let existing = copies.first(where: { $0.id == slot }) { panel.directoryURL = URL(fileURLWithPath: existing.path) }
        panel.level = .modalPanel
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await perform(T("Validating SVN folder…", "正在验证 SVN 目录…")) {
            let copy = try await svn.info(url.path)
            installCopy(copy, slot: slot)
            await refresh()
        } }
    }
    var selected: WorkingCopy? { copies.first { $0.id == selectedID } }
    var conflictCount: Int { statuses.filter { [.conflicted, .obstructed].contains($0.state) }.count }
    var unversionedCount: Int { statuses.filter { $0.state == .unversioned }.count }
    var selectedChangeCount: Int { statuses.filter { selectedPaths.contains($0.path) }.count }

    var isUIPreview: Bool { ProcessInfo.processInfo.arguments.contains("--ui-preview") }
    init() {
        let args = ProcessInfo.processInfo.arguments
        if let index = args.firstIndex(of: "--ui-preview"), args.count > index + 1 {
            let base = args[index + 1]
            copies = ["Dev_Develop", "Release_1.2", "HotFix_1.2.1"].map { name in
                WorkingCopy(name: name, path: URL(fileURLWithPath: base).appendingPathComponent(name).path, url: "", branch: name, revision: "")
            }
            selectedID = copies.first?.id
            return
        }
        let previousSelection = UserDefaults.standard.string(forKey: "SvnFlow.fixedSelection.v1").flatMap(UUID.init(uuidString:))
        if let data = UserDefaults.standard.data(forKey: key), let saved = try? JSONDecoder().decode([WorkingCopy].self, from: data) {
            // Keep configured paths even when a disk or working copy is temporarily unavailable.
            copies = saved.filter { $0.id == Self.devID || $0.id == Self.releaseID }
        } else if let data = UserDefaults.standard.data(forKey: "SvnFlow.copies.v1"), let legacy = try? JSONDecoder().decode([WorkingCopy].self, from: data) {
            for slot in Self.slots {
                if var copy = legacy.first(where: { ($0.path + "/" + $0.url).lowercased().contains("/" + slot.name.lowercased() + "/") }) {
                    copy.id = slot.id; copies.append(copy)
                }
            }
            save()
        }
        selectedID = copies.contains(where: { $0.id == previousSelection }) ? previousSelection : copies.first?.id
    }

    func save() { guard !isUIPreview else { return }; if let data = try? JSONEncoder().encode(copies) { UserDefaults.standard.set(data, forKey: key) } }
    func perform(_ title: String, _ work: @MainActor () async throws -> Void) async { guard !restoringCache else { return }; invalidateValidation(); busy = true; activity = title; output = title; defer { busy = false }; do { try await work() } catch { self.error = error.localizedDescription; output = error.localizedDescription } }
    func add() { guard !busy, let slot = chooseSlot() else { return }; configureSlot(slot) }
    func remove() { selectedID = nil; selectedDirectory = ""; statusEntries = []; localEntries = []; directories = []; listingIndex = WorkspaceListingIndex([]); indexVersion += 1 }
    func refresh() async {
        guard !restoringCache, let c = selected, scanningCopy != c.id else { return }
        invalidateValidation()
        let request = UUID(); refreshRequest = request; scanningCopy = c.id
        checkpoints[c.id] = FSEventsGetCurrentEventId()
        if loadedCopy != c.id {
            let cached = snapshots[c.id]
            statusEntries = cached?.statuses ?? []
            listingIndex = cached?.index ?? WorkspaceListingIndex([])
            localEntries = cached?.entries ?? []
            directories = cached?.directories ?? []
            loadedCopy = c.id; selectedEntryID = nil; selectedPaths = []; indexVersion += 1
        }
        busy = true; activity = L("扫描工作副本…"); output = activity
        defer { if refreshRequest == request { busy = false; scanningCopy = nil } }
        do {
            let scanned = try await svn.status(c.path)
            guard refreshRequest == request, selectedID == c.id else { return }
            statusEntries = scanned
            let validPaths = Set(statuses.map(\.path))
            if localEntries.isEmpty && selectedPaths.isEmpty {
                selectedPaths = Set(statuses.filter { $0.state != .unversioned }.map(\.path))
            } else { selectedPaths.formIntersection(validPaths) }
            activity = L("正在整理目录和文件状态，请稍候…")
            await rebuildLocalEntries(c, request: request)
            guard refreshRequest == request, selectedID == c.id else { return }
            if let i = copies.firstIndex(where: { $0.id == c.id }) {
                var latest = try await svn.info(c.path)
                guard refreshRequest == request, selectedID == c.id else { return }
                latest.id = c.id; copies[i] = latest; save()
            }
            output = statuses.isEmpty ? L("工作副本干净") : T("Found {0} changes", "发现 {0} 项变化", statuses.count)
        } catch {
            if refreshRequest == request { self.error = error.localizedDescription; output = error.localizedDescription }
        }
    }
    func rebuildLocalEntries(_ c: WorkingCopy, request: UUID? = nil) async {
        let entries = statusEntries
        let previous = localEntries
        let snapshot = await Task.detached(priority: .userInitiated) {
            let entries = WorkspaceCatalog.build(root: c.path, status: entries, previous: previous)
            return (entries, WorkspaceListingIndex(entries))
        }.value
        let rebuilt = snapshot.0
        guard selectedID == c.id, request == nil || refreshRequest == request else { return }
        listingIndex = snapshot.1
        localEntries = rebuilt
        directories = rebuilt.filter { $0.isDirectory && !$0.relative.isEmpty }
        indexVersion += 1
        loadedCopy = c.id
        snapshots[c.id] = Snapshot(statuses: entries, entries: rebuilt, directories: directories, index: snapshot.1)
        persistSnapshot(c)
        // Bound retained project data: current copy and at most one recently visited copy.
        while snapshots.count > 2 { if let key = snapshots.keys.first(where: { $0 != c.id }) { snapshots.removeValue(forKey: key) } }
    }

    var visibleEntries: [LocalEntry] { localEntries.filter { entry in
        let parent = (entry.relative as NSString).deletingLastPathComponent
        let inDirectory = !entry.isDirectory && (selectedDirectory.isEmpty || parent == selectedDirectory || parent.hasPrefix(selectedDirectory + "/"))
        return inDirectory && (!showOnlyChanges || entry.state != .normal) && (filter.isEmpty || entry.name.localizedCaseInsensitiveContains(filter))
    } }
    var diffSides: (old: String, new: String) {
        var old: [String] = [], new: [String] = []
        for line in diff.split(separator: "\n", omittingEmptySubsequences: false).map(String.init) {
            if line.hasPrefix("---") || line.hasPrefix("+++") || line.hasPrefix("@@") { old.append(line); new.append(line) }
            else if line.hasPrefix("-") { old.append(line); new.append("") }
            else if line.hasPrefix("+") { old.append(""); new.append(line) }
            else { old.append(line); new.append(line) }
        }
        return (old.joined(separator: "\n"), new.joined(separator: "\n"))
    }
    func runUpdate(_ path: String) async throws -> UpdateTracker {
        var tracker = UpdateTracker()
        var captured = Data()
        var published = Date.distantPast
        for try await chunk in svn.updateOutput(path) {
            captured.append(chunk); tracker.append(chunk)
            if Date().timeIntervalSince(published) > 0.15 {
                updateCount = tracker.count; updateDetail = tracker.detail; published = Date()
            }
        }
        tracker.finish()
        updateCount = tracker.count; updateDetail = tracker.detail
        output = String(decoding: captured, as: UTF8.self)
        return tracker
    }
    private func invalidateValidation() { validationToken = UUID(); backgroundValidation = false }
    private func validateInBackground(_ c: WorkingCopy) {
        let token = UUID(); validationToken = token; backgroundValidation = true
        refreshLabel = T("Checking complete working-copy state", "正在后台校验完整状态")
        let previous = localEntries
        let checkpoint = FSEventsGetCurrentEventId()
        Task {
            defer { if validationToken == token { backgroundValidation = false } }
            let start = Date()
            do {
                // Independent reader: foreground SVN actions do not queue behind this audit.
                let scanned = try await SVN().status(c.path)
                guard validationToken == token, selectedID == c.id, !busy else { return }
                let snapshot = await Task.detached(priority: .utility) {
                    let entries = WorkspaceCatalog.build(root: c.path, status: scanned, previous: previous)
                    return (entries, WorkspaceListingIndex(entries))
                }.value
                guard validationToken == token, selectedID == c.id, !busy else { return }
                checkpoints[c.id] = checkpoint
                publishUpdate(c, statuses: scanned, entries: snapshot.0, index: snapshot.1)
                updateTiming += String(format: T(" · Background verification %.2f s", " · 后台校验 %.2f 秒"), Date().timeIntervalSince(start))
            } catch {
                guard validationToken == token, selectedID == c.id else { return }
                updateTiming += T(" · Background verification failed; please refresh", " · 后台校验失败，请刷新")
                output += T("\nBackground verification failed: ", "\n后台校验失败：") + error.localizedDescription
            }
        }
    }
    private func publishUpdate(_ c: WorkingCopy, statuses: [StatusItem], entries: [LocalEntry], index: WorkspaceListingIndex) {
        statusEntries = statuses; localEntries = entries; listingIndex = index
        directories = entries.filter { $0.isDirectory && !$0.relative.isEmpty }
        loadedCopy = c.id; indexVersion += 1
        selectedPaths.formIntersection(Set(statuses.filter(\.hasLocalChange).map(\.path)))
        snapshots[c.id] = Snapshot(statuses: statuses, entries: entries, directories: directories, index: index)
        persistSnapshot(c)
    }
    func update() async {
        guard let c = selected else { error = L("请先打开工作副本"); return }
        guard !busy, !restoringCache else { return }
        let initialStatuses = statusEntries, initialEntries = localEntries
        let operation = UUID(); refreshRequest = operation
        let target = UpdateRefresh.target(root: c.path, directory: selectedDirectory)
        updateStage = 1; updateCount = 0; updateDetail = L("更新范围：") + target; updateStarted = Date(); updateTiming = ""
        var completed = false
        await perform(L("更新 ") + (target as NSString).lastPathComponent + "…") {
            let started = Date()
            var tracker: UpdateTracker
            do {
                tracker = try await runUpdate(target)
            } catch {
                let detail = error.localizedDescription.lowercased()
                guard detail.contains("e155004") || detail.contains("working copy locked") || detail.contains("工作副本") && detail.contains("锁") else { throw error }
                _ = try await svn.run(["cleanup", c.path])
                tracker = try await runUpdate(target)
            }
            let updated = Date()
            updateStage = 2; activity = L("更新完成，正在刷新受影响文件…")
            var queried = Set(initialStatuses.filter { $0.hasLocalChange && UpdateRefresh.contains($0.path, in: target) }.map(\.path))
            queried.insert(target)
            queried.formUnion(tracker.paths.map { $0.hasPrefix("/") ? $0 : (target as NSString).deletingLastPathComponent + "/" + $0 }.filter { UpdateRefresh.contains($0, in: c.path) })
            let fresh: [StatusItem]
            if queried.count > 1000 {
                activity = L("变化较多，正在扫描更新范围…")
                fresh = try await svn.status(target, root: c.path)
                queried.formUnion(initialStatuses.filter { UpdateRefresh.contains($0.path, in: target) }.map(\.path))
                queried.formUnion(fresh.map(\.path))
            } else { fresh = try await svn.exactStatus(queried.sorted(), root: c.path) }
            let scanned = Date()
            updateStage = 3; activity = L("正在合并变化并刷新界面…")
            let previous = initialStatuses, entries = initialEntries
            let deleted = tracker.deletedPaths.filter { UpdateRefresh.contains($0, in: c.path) }
            let patch = await Task.detached(priority: .userInitiated) {
                let result = UpdateRefresh.merge(root: c.path, previous: previous, entries: entries, refreshed: fresh, queried: queried, deleted: deleted)
                return (result.0, result.1, WorkspaceListingIndex(result.1))
            }.value
            guard selectedID == c.id, refreshRequest == operation else { return }
            publishUpdate(c, statuses: patch.0, entries: patch.1, index: patch.2)
            if let i = copies.firstIndex(where: { $0.id == c.id }) { var latest = try await svn.info(c.path); latest.id = c.id; copies[i] = latest; save() }
            updateTiming = String(format: T("SVN update %.2f s · Local status %.2f s · UI refresh %.2f s", "SVN 更新 %.2f 秒 · 局部状态 %.2f 秒 · 界面整理 %.2f 秒"), updated.timeIntervalSince(started), scanned.timeIntervalSince(updated), Date().timeIntervalSince(scanned))
            output += T("\nUpdate scope: ", "\n更新范围：") + target + "\n" + updateTiming
            completed = true
        }
        updateStage = 0
        // Audit even on partial update failure; SVN may already have changed some files.
        if !completed && selectedID == c.id { validateInBackground(c) }
        if completed { activity = L("更新完成") }
    }
    func loadDiff(_ item: StatusItem) async {
        guard let c = selected, !isHidden(item.path) else { return }
        do {
            let value = item.state == .unversioned ? ((try? String(contentsOfFile: item.path, encoding: .utf8)) ?? L("无法预览")) : try await svn.run(["diff", "--", item.path], cwd: c.path)
            guard selectedID == c.id, selectedEntryID == item.path, !isHidden(item.path) else { return }
            diff = value
        } catch {
            guard selectedID == c.id, selectedEntryID == item.path, !isHidden(item.path) else { return }
            self.error = error.localizedDescription
        }
    }
    func chooseCurrentEntry() -> String? {
        guard selected != nil else { error = L("请先打开或检出一个 SVN 工作副本"); return nil }
        guard let path = selectedEntryID else { error = L("请先在文件列表中选择一个文件"); return nil }
        return path
    }
    func addFiles() async {
        guard let c = selected else { error = L("请先打开工作副本"); return }
        if let path = selectedEntryID { selectedPaths.insert(path) }
        let paths = statuses.filter { selectedPaths.contains($0.path) && $0.state == .unversioned }.map(\.path)
        guard !paths.isEmpty else { error = L("所选内容中没有未纳入版本控制的文件"); return }
        await perform(L("加入版本控制…")) { output = try await svn.run(["add", "--parents"] + paths, cwd: c.path); await refreshAffected(c, paths: paths) }
    }
    @Published var reverting = false
    @Published var revertSummary: String?
    static var activeReverts = 0

    @discardableResult func revert(paths requested: Set<String>) async -> Set<String> {
        guard !busy, !restoringCache, !reverting, !committing, let c = selected else { return [] }
        let paths = RevertScope.paths(in: statuses, selected: requested)
        guard !paths.isEmpty else { return [] }
        reverting = true; Self.activeReverts += 1
        defer { reverting = false; Self.activeReverts -= 1 }
        let skipped = requested.count - paths.count
        let names = paths.prefix(8).map { path in
            let name = path.hasPrefix(c.path + "/") ? String(path.dropFirst(c.path.count + 1)) : path
            return String(name.prefix(100))
        }.joined(separator: "\n")
        let alert = NSAlert()
        alert.messageText = T("Revert {0} selected local changes?", "回退所选的 {0} 项本地改动？", paths.count)
        alert.informativeText = T("Working copy: {0}", "工作副本：{0}", c.name) + "\n\n"
            + T("Restore the selected items to working-copy BASE and discard local changes. This cannot be undone; the server is unchanged.", "将所选项恢复到工作副本的 BASE，丢弃本地修改。此操作无法恢复；不会修改服务器版本。") + "\n\n"
            + T("Selected {0}; reverting {1}; skipping {2}.", "本次选中 {0} 项，可回退 {1} 项，跳过 {2} 项。", requested.count, paths.count, skipped) + "\n"
            + T("Unversioned files are skipped. SVN may remove conflict helper files. Unselected children are not reverted.", "跳过未纳入版本的文件；SVN 可能清理冲突辅助文件。不回退未选中的子项。")
            + "\n\n" + names + (paths.count > 8 ? "\n…" : "")
        alert.alertStyle = .warning
        alert.addButton(withTitle: L("取消"))
        alert.addButton(withTitle: T("Revert {0} items", "回退 {0} 项", paths.count)).keyEquivalent = ""
        alert.window.level = .modalPanel
        guard alert.runModal() == .alertSecondButtonReturn, !busy, !restoringCache, selectedID == c.id else { return [] }
        var reverted = Set<String>()
        revertSummary = nil
        await perform(T("Reverting selected local changes…", "正在回退所选改动…")) {
            do {
                for start in stride(from: 0, to: paths.count, by: 100) {
                    let batch = Array(paths[start..<min(start + 100, paths.count)])
                    output = try await svn.run(RevertScope.arguments(for: batch), cwd: c.path)
                    reverted.formUnion(batch)
                }
                await refreshAffected(c, paths: paths)
                revertSummary = T("Reverted {0} items; skipped {1}.", "已回退 {0} 项，跳过 {1} 项。", reverted.count, skipped)
            } catch {
                // SVN may have changed earlier targets even when a later one failed.
                // Refresh before surfacing the error and retain the selection for review.
                await refreshAffected(c, paths: paths)
                reverted = []
                throw ToolError.message(T("Revert did not finish. Some items may already have been reverted. Check the refreshed list before retrying.", "回退未完成，部分文件可能已回退。请检查刷新后的列表再重试。") + "\n\n" + error.localizedDescription)
            }
        }
        return reverted
    }
    @Published var committing = false
    @discardableResult func commit() async -> Bool {
        guard !busy, !restoringCache, !committing, let c = selected else { return false }
        committing = true
        defer { committing = false }
        let chosen = statuses.filter { selectedPaths.contains($0.path) }
        guard !chosen.isEmpty else { error = T("Select files to commit.", "请选择要提交的文件。"); return false }
        guard !chosen.contains(where: { $0.state == .conflicted }) else { error = L("存在未解决冲突，已阻止提交"); return false }
        guard !chosen.contains(where: { $0.state == .unversioned }) else { error = L("请先将未纳入版本的文件加入版本控制"); return false }
        guard !chosen.contains(where: { $0.state == .missing }) else { error = T("Restore missing files or schedule their removal before committing.", "请先恢复本地缺失文件，或将其标记为删除后再提交。"); return false }
        let commitMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !commitMessage.isEmpty else { error = L("请填写提交说明"); return false }
        busy = true; error = nil
        activity = T("Checking commit targets…", "正在检查提交目标…")
        defer { busy = false }
        do {
            let duplicates = try await svn.duplicateCommitTargets(chosen.map(\.path), cwd: c.path)
            if !duplicates.isEmpty {
                let prefix = c.path.hasSuffix("/") ? c.path : c.path + "/"
                let detail = duplicates.map { paths in
                    paths.map { $0.hasPrefix(prefix) ? String($0.dropFirst(prefix.count)) : $0 }.joined(separator: "\n")
                }.joined(separator: "\n\n")
                error = T("Multiple local paths refer to the same repository file. Keep only one path selected per group; if their changes differ, reconcile them first. No files have been committed.\n\n{0}", "以下本地路径指向同一个仓库文件，每组只能勾选一份；若改动不同，请先核对并合并。本次尚未提交任何文件。\n\n{0}", detail)
                return false
            }
        } catch {
            self.error = T("Commit target check failed: {0}", "提交目标检查失败：{0}", error.localizedDescription)
            return false
        }
        guard confirm(T("Commit to {0}?", "提交到 {0}？", c.branch), T("Target: {0}\nFiles: {1}\n\nPlease verify the destination branch.", "目标：{0}\n文件数：{1}\n\n请确认没有选错分支。", c.url, chosen.count), action: "提交到 SVN") else { return false }
        invalidateValidation()
        busy = true; error = nil
        activity = T("Committing to {0}…", "正在提交到 {0}，请稍候…", c.branch)
        output = activity
        do {
            output = try await svn.run(["commit", "-m", commitMessage, "--"] + chosen.map { $0.path + "@" }, cwd: c.path)
        } catch { self.error = error.localizedDescription; output = error.localizedDescription; return false }
        message = ""; selectedPaths = []
        activity = T("Committed. Refreshing working copy…", "提交成功，正在刷新工作副本…")
        do {
            await refreshAffected(c, paths: chosen.map(\.path))
            logs = try await svn.logs(c.path)
        } catch { self.error = T("Commit succeeded, but refresh failed: {0}", "提交已成功，但刷新失败：{0}", error.localizedDescription) }
        return true
    }

    func resolve(_ item: StatusItem, _ choice: String) async { guard let c = selected else { return }; await perform(L("解决冲突…")) { output = try await svn.run(["resolve", "--accept", choice, item.path], cwd: c.path); await refreshAffected(c, paths: [item.path]) } }
    func cleanup() async { guard let c = selected else { error = L("请先打开工作副本"); return }; await perform(L("清理工作副本…")) { output = try await svn.run(["cleanup", c.path]) } }
    func loadLogs() async { guard let c = selected else { error = L("请先打开工作副本"); return }; await perform(L("读取提交历史…")) { logs = try await svn.logs(c.path); output = T("Loaded {0} records", "已读取 {0} 条记录", logs.count) } }
    func browse() async { guard let c = selected else { error = L("请先打开工作副本"); return }; await perform(L("读取仓库…")) { repoEntries = try await svn.run(["list", c.url]).split(separator: "\n").map(String.init) } }
    func merge(_ dry: Bool) async { guard let c = selected else { error = L("请先打开工作副本"); return }; guard !mergeSource.isEmpty else { error = L("请输入合并来源 URL"); return }; guard dry || confirm(L("执行合并？"), T("Source: {0}\nTarget: {1}\n\nMerging changes local files; review and commit afterwards.", "来源：{0}\n目标：{1}\n\n合并只修改本地，之后仍需检查并提交。", mergeSource, c.path), action: "执行合并") else { return }; await perform(dry ? L("预演合并…") : L("执行合并…")) { var a = ["merge"]; if dry { a.append("--dry-run") }; output = try await svn.run(a + [mergeSource, c.path], cwd: c.path); if !dry { statusEntries = try await svn.status(c.path); await rebuildLocalEntries(c) } } }
    func confirm(_ title: String, _ detail: String, action: String = "确认") -> Bool { let a = NSAlert(); a.messageText = title; a.informativeText = detail; a.addButton(withTitle: L(action)); a.addButton(withTitle: L("取消")); a.alertStyle = .warning; a.window.level = .modalPanel; return a.runModal() == .alertFirstButtonReturn }
    func ask(_ title: String, _ detail: String, placeholder: String, value: String = "") -> String? {
        let a = NSAlert(); a.messageText = title; a.informativeText = detail; a.addButton(withTitle: L("继续")); a.addButton(withTitle: L("取消"))
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 430, height: 24)); field.placeholderString = placeholder; field.stringValue = value; a.accessoryView = field
        return a.runModal() == .alertFirstButtonReturn ? field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) : nil
    }
    func checkout() {
        guard !busy, let slot = chooseSlot() else { return }
        guard let url = ask(L("检出工作副本"), L("输入 SVN 仓库 URL"), placeholder: "https://server/svn/project/trunk"), !url.isEmpty else { return }
        let p = NSOpenPanel(); p.canChooseFiles = false; p.canChooseDirectories = true; p.canCreateDirectories = true; p.prompt = L("选择父目录")
        guard p.runModal() == .OK, let parent = p.url else { return }
        let suggested = URL(string: url)?.lastPathComponent.nonEmpty ?? "working-copy"
        guard let name = ask(L("本地目录名称"), L("将在所选目录内创建工作副本"), placeholder: "working-copy", value: suggested), !name.isEmpty else { return }
        let target = parent.appendingPathComponent(name).path
        Task { await perform(L("正在检出…")) { output = try await svn.run(["checkout", url, target]); let wc = try await svn.info(target); installCopy(wc, slot: slot); await refresh() } }
    }
    func switchBranch() async { guard let c = selected else { error = L("请先打开工作副本"); return }; guard let url = ask(L("切换工作副本"), L("输入目标分支或标签 URL。执行前请先提交或搁置本地改动。"), placeholder: c.url, value: c.url), !url.isEmpty else { return }; await perform(L("切换工作副本…")) { output = try await svn.run(["switch", url, c.path], cwd: c.path); if let i = copies.firstIndex(where: { $0.id == c.id }) { var n = try await svn.info(c.path); n.id = c.id; copies[i] = n; save() }; await refresh() } }
    func createBranchOrTag() async { guard let c = selected else { error = L("请先打开工作副本"); return }; guard let url = ask(L("创建分支或标签"), L("输入目标仓库 URL，将从当前工作副本地址执行服务器端复制。"), placeholder: "…/branches/feature-name"), !url.isEmpty, let msg = ask(L("复制说明"), L("该操作会立即在仓库中创建一次提交。"), placeholder: "Create branch …"), !msg.isEmpty else { return }; await perform(L("创建分支或标签…")) { output = try await svn.run(["copy", c.url, url, "-m", msg]); } }
    func lock(_ unlock: Bool) async { guard let c = selected, !selectedPaths.isEmpty else { error = L("请先勾选文件"); return }; await perform(unlock ? L("解锁文件…") : L("锁定文件…")) { let paths = Array(selectedPaths); output = try await svn.run([unlock ? "unlock" : "lock"] + paths, cwd: c.path); await refreshAffected(c, paths: paths) } }
    func showLogForSelectedEntry() async { guard let path = chooseCurrentEntry() else { return }; await perform(L("读取文件历史…")) { logs = try await svn.logs(path); selectedWorkspaceSection = "log"; output = T("Loaded {0} file history records", "已读取 {0} 条文件历史", logs.count) } }
    func quickCommit() async { guard selected != nil else { error = L("请先打开工作副本"); return }; let path = selectedEntryID.flatMap { selected in statuses.first(where: { $0.path == selected })?.path } ?? statuses.first?.path; guard let path else { error = L("没有可提交的改动"); return }; selectedPaths = [path]; guard let text = ask(L("提交"), L("输入提交说明"), placeholder: L("提交说明")), !text.isEmpty else { return }; message = text; await commit() }
    func deleteSelected(keepLocal: Bool = false) async {
        guard let c = selected, let path = chooseCurrentEntry() else { return }
        let paths = selectedPaths.isEmpty ? [path] : selectedPaths.sorted()
        let detail = keepLocal ? L("文件会保留在磁盘上，但不再受 SVN 管理。") : L("文件将在下次提交时从仓库删除。")
        guard confirm(keepLocal ? L("从版本控制中移除？") : L("标记为删除？"), detail + "\n" + T("{0} selected files", "已选择 {0} 个文件", paths.count), action: keepLocal ? "移除并保留文件" : "标记为删除") else { return }
        await perform(keepLocal ? L("移除版本控制…") : L("标记删除…")) { var args = ["delete"]; if keepLocal { args.append("--keep-local") }; output = try await svn.run(args + ["--"] + paths, cwd: c.path); await refreshAffected(c, paths: paths) }
    }
    func moveSelected() async { guard let c = selected, let path = chooseCurrentEntry(), let relative = ask(L("移动或重命名"), L("输入相对于工作副本的新路径"), placeholder: "Sources/NewName.swift"), !relative.isEmpty else { return }; let target = URL(fileURLWithPath: c.path).appendingPathComponent(relative).path; await perform(L("移动…")) { output = try await svn.run(["move", "--parents", path, target], cwd: c.path); await refreshAffected(c, paths: [path, target]) } }
    func showProperties() async { guard let path = chooseCurrentEntry() else { return }; await perform(L("读取属性…")) { output = try await svn.run(["proplist", "--verbose", path]); selectedWorkspaceSection = "properties" } }
    func annotate() async { guard let path = chooseCurrentEntry() else { return }; await perform(L("逐行追溯…")) { output = try await svn.run(["blame", "--verbose", path]); selectedWorkspaceSection = "annotate" } }
    func revealWorkingCopy() { guard let selected else { return }; NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: selected.path)]) }
}

private extension String { var nonEmpty: String? { isEmpty ? nil : self } }
private extension Array {
    func uniqued<Key: Hashable>(by key: (Element) -> Key) -> [Element] {
        var seen = Set<Key>()
        return filter { seen.insert(key($0)).inserted }
    }
}

@main struct SvnFlowApp: App {
    @NSApplicationDelegateAdaptor(WorkbenchApplicationDelegate.self) private var appDelegate
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    var body: some Scene {
        WindowGroup(AppIdentity.name) { ContentView().environment(\.locale, Locale(identifier: interfaceLanguage)) }
            .defaultSize(width: 1440, height: 900)
            .windowStyle(.titleBar)
            .commands {
                CommandGroup(after: .windowArrangement) {
                    Divider()
                    Button(L("Main Perspective")) { NotificationCenter.default.post(name: .mainPerspective, object: nil) }.keyboardShortcut("1", modifiers: [.option, .shift])
                }
                CommandMenu(L("Project")) {
                    Button(L("Open Working Copy…")) { NotificationCenter.default.post(name: .openWorkingCopy, object: nil) }.keyboardShortcut("o")
                    Button(L("Check Out…")) { NotificationCenter.default.post(name: .checkoutWorkingCopy, object: nil) }
                    Button(L("Refresh")) { NotificationCenter.default.post(name: .refreshWorkingCopy, object: nil) }.keyboardShortcut("r")
                    Button(L("Update")) { NotificationCenter.default.post(name: .updateWorkingCopy, object: nil) }.keyboardShortcut("u")
                    Button(L("Commit…")) { NotificationCenter.default.post(name: .commitChanges, object: nil) }.keyboardShortcut("k")
                    Divider()
                    Button(L("Close Project")) { NotificationCenter.default.post(name: .closeWorkingCopy, object: nil) }
                }
                CommandMenu(L("Modify")) {
                    Button(L("Add")) { NotificationCenter.default.post(name: .addSelected, object: nil) }
                    Button(L("Remove from Version Control")) { NotificationCenter.default.post(name: .removeSelected, object: nil) }
                    Button(L("Move or Rename…")) { NotificationCenter.default.post(name: .moveSelected, object: nil) }
                    Button(L("Revert")) { NotificationCenter.default.post(name: .revertSelected, object: nil) }
                    Button(L("Delete")) { NotificationCenter.default.post(name: .deleteSelected, object: nil) }
                }
                CommandMenu(L("Tag+Branch")) {
                    Button(L("Create Branch or Tag…")) { NotificationCenter.default.post(name: .createBranch, object: nil) }
                    Button(L("Switch…")) { NotificationCenter.default.post(name: .switchWorkingCopy, object: nil) }
                    Button(L("Merge…")) { NotificationCenter.default.post(name: .mergeChanges, object: nil) }
                }
                CommandMenu(L("Query")) {
                    Button(L("Compare with Base")) { NotificationCenter.default.post(name: .compareFile, object: nil) }.keyboardShortcut("d", modifiers: [.command])
                    Button(L("File Log")) { NotificationCenter.default.post(name: .showLog, object: nil) }
                    Button(L("Check for Modifications")) { NotificationCenter.default.post(name: .refreshWorkingCopy, object: nil) }
                    Button(L("Show Properties")) { NotificationCenter.default.post(name: .showProperties, object: nil) }
                    Button(L("Annotate")) { NotificationCenter.default.post(name: .showAnnotate, object: nil) }
                }
                CommandMenu(L("Locks")) {
                    Button(L("Lock")) { NotificationCenter.default.post(name: .lockSelected, object: nil) }
                    Button(L("Unlock")) { NotificationCenter.default.post(name: .unlockSelected, object: nil) }
                }
                CommandMenu(L("Tools")) {
                    Button(T("Branch Sync…", "分支合入助手…")) { QueryWindows.shared.openBranchSync() }
                    LanguageMenu()
                    Divider()
                    Button(L("Clean Up")) { NotificationCenter.default.post(name: .cleanupWorkingCopy, object: nil) }
                    Button(L("Repository Browser")) { NotificationCenter.default.post(name: .showRepository, object: nil) }
                }
            }
        Settings { LanguageSettings() }
    }
}
