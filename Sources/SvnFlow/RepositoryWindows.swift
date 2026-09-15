import AppKit
import SwiftUI
import SVNCore

@MainActor final class QueryWindows: NSObject, NSWindowDelegate {
    static let shared = QueryWindows()
    private var windows: [NSWindow] = []
    var openWindows: [NSWindow] { windows }
    private var reviews: [ObjectIdentifier: ComparisonReviewActions] = [:]
    private var comparisonPaths: [ObjectIdentifier: String] = [:]
    private struct ComparisonKey: Equatable { let path: String; let revision: String?; let change: ChangedPath? }
    private var comparisonKeys: [ObjectIdentifier: ComparisonKey] = [:]
    private weak var branchSyncWindow: NSWindow?
    private var branchSyncModel: BranchSyncModel?
    private var configurationExportWindows: [String: NSWindow] = [:]
    private var workspaceExportModels: [String: BranchSyncModel] = [:]
    var branchSyncBusy: Bool { workspaceExportModels.values.contains { $0.busy } || branchSyncModel?.busy == true || branchSyncModel?.reviewing == true || branchSyncModel?.batchAccepting == true }
    func openBranchSync() {
        if let window = branchSyncWindow {
            branchSyncModel?.refreshEndpointDisplay()
            window.title = "分支合入 · " + (branchSyncModel?.directionTitle ?? MergeEndpointDisplay.current().direction)
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
            return
        }
        let model = branchSyncModel ?? BranchSyncModel()
        model.refreshEndpointDisplay()
        branchSyncModel = model
        branchSyncWindow = present("分支合入 · " + model.directionTitle, SyncRoundEntry(model: model), size: .init(width: 1360, height: 830), assistant: true)
        branchSyncWindow?.minSize = .init(width: 1160, height: 690)
        branchSyncWindow?.appearance = NSAppearance(named: .aqua)
        branchSyncWindow?.backgroundColor = NSColor(SyncOrbit.background)
        NSApp.activate(ignoringOtherApps: true)
    }
    func openConfigurationExport(workingCopy: String, selection: Set<String>, label: String = "Release") throws {
        let root = URL(fileURLWithPath: workingCopy).standardizedFileURL.resolvingSymlinksInPath().path
        let paths = try WorkbookExportScope.paths(selection: selection, workingCopy: root, target: root)
        let model = workspaceExportModels[root] ?? BranchSyncModel(workspaceExport: true)
        if model.busy, let window = configurationExportWindows[root] {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        guard model.canChangeBatch, !branchSyncBusy else {
            throw NSError(domain: "ConfigurationExport", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "当前合入或导出任务尚未结束，请等待完成后再选择导出文件。"])
        }
        model.workspaceExportTarget = root
        model.workspaceExportLabel = label
        model.workspaceExportPaths = paths
        model.selectedExports = paths
        if model.exportCandidate == nil {
            model.activity = "已从目录选择 \(paths.count) 个本地 Excel，生成前请保存文件。"
        }
        workspaceExportModels[root] = model
        if let window = configurationExportWindows[root] {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        } else {
            configurationExportWindows[root] = present("配置导出 · " + label, WorkspaceConfigurationExport(model: model) { [weak self] in
                self?.configurationExportWindows[root]?.orderOut(nil)
            }, size: .init(width: 820, height: 710))
        }
        NSApp.activate(ignoringOtherApps: true)
    }
    private var comparisonSuspensions = 0
    func suspendComparisons() {
        comparisonSuspensions += 1
        for case let panel as WorkflowPanel in windows { panel.suspended = true }
    }
    func resumeComparisons() {
        comparisonSuspensions = max(0, comparisonSuspensions - 1)
        for case let panel as WorkflowPanel in windows { panel.suspended = comparisonSuspensions > 0 }
    }
    // Floating panels are omitted from the system Dock window list. Supply
    // live entries separately, including panels hidden on app deactivation.
    func comparisonDockMenu() -> NSMenu? {
        let comparisons = windows.filter { comparisonKeys[ObjectIdentifier($0)] != nil }
        guard !comparisons.isEmpty else { return nil }
        let menu = NSMenu()
        for window in comparisons {
            let item = NSMenuItem(title: window.title, action: #selector(activateComparison(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = window
            item.state = window.isKeyWindow ? .on : .off
            menu.addItem(item)
        }
        return menu
    }
    @objc private func activateComparison(_ sender: NSMenuItem) {
        guard comparisonSuspensions == 0, NSApp.modalWindow == nil else { return }
        guard let window = sender.representedObject as? NSWindow,
              windows.contains(where: { $0 === window }) else { return }
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
    }
    @discardableResult func present<V: View>(_ title: String, _ view: V, size: NSSize = .init(width: 1120, height: 760), comparison: Bool = false, assistant: Bool = false) -> NSWindow {
        let presentingScreen = NSApp.keyWindow?.screen ?? NSApp.mainWindow?.screen ?? NSScreen.main
        let type: NSWindow.Type = comparison ? ComparisonPanel.self : assistant ? WorkflowPanel.self : NSWindow.self
        let window = type.init(contentRect: .init(origin: .zero, size: size), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        (window as? WorkflowPanel)?.configureLayer()
        (window as? WorkflowPanel)?.suspended = comparisonSuspensions > 0
        window.appearance = NSAppearance(named: .aqua)
        window.backgroundColor = WorkbenchTheme.canvasNS
        window.titlebarAppearsTransparent = false
        // The existing content header owns the visible title; keep traffic lights clear.
        window.titleVisibility = .hidden
        window.titlebarSeparatorStyle = .line
        window.title = title; window.isReleasedWhenClosed = false; window.delegate = self
        let host = NSHostingController(rootView: WorkbenchWindowChrome(title: title) { view }.frame(minWidth: 800, maxWidth: .infinity, minHeight: 520, maxHeight: .infinity).workbenchStyle())
        host.sizingOptions = []
        window.contentViewController = host
        window.setContentSize(size)
        window.minSize = .init(width: 800, height: 520)
        if comparison || assistant, let screen = presentingScreen {
            // Fill the available desktop on the invoking window's screen.
            window.setFrame(screen.visibleFrame, display: false)
        } else {
            window.center()
        }
        windows.append(window)
        window.makeKeyAndOrderFront(nil)
        WorkbenchWindowOutline.install(on: window)
        return window
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if configurationExportWindows.values.contains(where: { $0 === sender }) { sender.orderOut(nil); return false }
        if sender === branchSyncWindow, let model = branchSyncModel, model.busy || model.batchAccepting {
            guard sender.attachedSheet == nil else { NSSound.beep(); return false }
            let writing = model.batchAccepting || ["accept", "accept-low", "xtools-export", "xtools-local-export"].contains(model.action)
            let alert = NSAlert()
            alert.messageText = writing ? "在安全收尾后关闭？" : "停止核验或生成并关闭？"
            alert.informativeText = writing ? "等待当前文件写入并保存记录，再停止后续文件。不会强制终止 SVN 写入。" : "已完成结果与副本保留，下次可继续处理未完成的文件。"
            alert.addButton(withTitle: "取消")
            alert.addButton(withTitle: writing ? "安全收尾后关闭" : "停止并关闭")
            alert.beginSheetModal(for: sender) { response in
                guard response == .alertSecondButtonReturn else { return }
                if writing { model.requestStopWriting() } else { model.cancelGeneration() }
                Task { @MainActor in
                    while model.busy || model.batchAccepting { try? await Task.sleep(for: .milliseconds(200)) }
                    model.saveSelection()
                    if !model.interrupted && !model.reviewing { sender.performClose(nil) }
                }
            }
            return false
        }
        if reviews[ObjectIdentifier(sender)]?.busy == true || (sender === branchSyncWindow && branchSyncBusy) {
            let alert = NSAlert()
            alert.messageText = "当前任务尚未结束"
            alert.informativeText = "请等待写入完成，或先在任务界面安全停止生成；正在核对时可先关闭对比窗口。现场与副本会保留。"
            alert.addButton(withTitle: "返回任务")
            if sender.attachedSheet == nil { alert.beginSheetModal(for: sender) }
            else { NSSound.beep() }
            return false
        }
        return true
    }
    func windowWillClose(_ notification: Notification) { if let window = notification.object as? NSWindow {
        reviews.removeValue(forKey: ObjectIdentifier(window))?.didClose()
        if window === branchSyncWindow { branchSyncWindow = nil }
        comparisonPaths.removeValue(forKey: ObjectIdentifier(window)); comparisonKeys.removeValue(forKey: ObjectIdentifier(window)); windows.removeAll { $0 === window } } }
    func log(_ target: String, revision: String? = nil) { present(T("Log — {0}", "日志 — {0}", (target as NSString).lastPathComponent), HistoryWindow(model: HistoryModel(target: target, revision: revision))) }
    func repository(_ url: String) { present(L("Repository Browser"), RepositoryWindow(model: BrowserModel(url: url))) }
    func closeHiddenComparisons(_ rules: Set<String>) {
        let hidden = windows.filter { comparisonPaths[ObjectIdentifier($0)].map { LocalIgnore.contains($0, rules: rules) } == true }
        for window in hidden { comparisonPaths.removeValue(forKey: ObjectIdentifier(window)); window.close() }
    }
    func compare(_ path: String, revision: String? = nil, change: ChangedPath? = nil) {
        if LocalIgnore.contains(path, rules: Set(UserDefaults.standard.stringArray(forKey: LocalIgnore.storageKey) ?? [])) { return }
        let key = ComparisonKey(path: path.hasPrefix("/") ? (path as NSString).standardizingPath : path, revision: revision, change: change)
        if let existing = windows.first(where: { comparisonKeys[ObjectIdentifier($0)] == key }) {
            if existing.isMiniaturized { existing.deminiaturize(nil) }
            NSApp.activate(ignoringOtherApps: true)
            existing.makeKeyAndOrderFront(nil)
            return
        }
        let window: NSWindow
        let name = (path as NSString).lastPathComponent
        if ["xlsx", "xlsm"].contains((name as NSString).pathExtension.lowercased()) {
            window = present(name + " ↔ " + name + T(" — Table Compare", " — 表格比较"), WorkbookCompareWindow(model: WorkbookModel(path: path, revision: revision, change: change)), size: .init(width: 1280, height: 800), comparison: true)
        } else {
            window = present(L("Compare — ") + name, CompareWindow(model: CompareModel(path: path, revision: revision, change: change)), size: .init(width: 1280, height: 800), comparison: true)
        }
        comparisonPaths[ObjectIdentifier(window)] = path
        comparisonKeys[ObjectIdentifier(window)] = key
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func compare(_ path: String, files: ComparisonFiles, review: ComparisonReviewActions? = nil) {
        let title = (path as NSString).lastPathComponent + (review == nil ? " — 差异核对" : " — 合入确认")
        let window: NSWindow
        if ["xlsx", "xlsm"].contains((path as NSString).pathExtension.lowercased()) {
            window = present(title, WorkbookCompareWindow(model: WorkbookModel(path: path, revision: nil, files: files), review: review), size: .init(width: 1280, height: 860), comparison: true)
        } else {
            window = present(title, CompareWindow(model: CompareModel(path: path, files: files), review: review), size: .init(width: 1280, height: 860), comparison: true)
        }
        if let review {
            review.window = window
            reviews[ObjectIdentifier(window)] = review
        }
        comparisonKeys[ObjectIdentifier(window)] = ComparisonKey(path: path, revision: nil, change: nil)
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func preview(_ title: String, text: String) { present(title, WorkbenchOutputText(text: text), size: .init(width: 900, height: 680)) }
}

@MainActor final class HistoryModel: ObservableObject {
    let target: String
    let fixedRevision: String?
    let query = RepositoryQuery()
    @Published var records: [RevisionRecord] = []
    @Published var selection: String?
    @Published var filter = ""
    @Published var directory = "/"
    @Published var pathSelection: String?
    @Published var busy = false
    @Published var error = ""
    @Published var more = true
    private var peg = "HEAD"
    init(target: String, revision: String? = nil) { self.target = target; self.fixedRevision = revision }
    var current: RevisionRecord? { records.first { $0.revision == selection } }
    var visible: [RevisionRecord] { filter.isEmpty ? records : records.filter { "\($0.revision) \($0.author) \($0.message)".localizedCaseInsensitiveContains(filter) } }
    var directories: [String] { ["/"] + Array(Set((current?.paths ?? []).map { ($0.path as NSString).deletingLastPathComponent })).filter { $0 != "/" }.sorted() }
    var paths: [ChangedPath] { (current?.paths ?? []).filter { directory == "/" || ($0.path as NSString).deletingLastPathComponent == directory } }
    func compareSelection() async {
        guard !busy, let record = current, let entry = paths.first(where: { $0.path == pathSelection }) else { return }
        guard entry.kind != "dir" else { error = T("Select a file to compare revisions.", "请选择文件查看版本差异。"); return }
        busy = true; error = ""; defer { busy = false }
        do {
            let root = try await query.info(target, item: "repos-root-url", revision: peg)
            guard let rootURL = URL(string: root) else { return }
            let url = rootURL.appendingPathComponent(String(entry.path.dropFirst())).absoluteString
            QueryWindows.shared.compare(url, revision: record.revision, change: entry)
        } catch { self.error = error.localizedDescription }
    }
    func load(older: Bool = false) async {
        guard !busy else { return }; busy = true; error = ""; defer { busy = false }
        do {
            if !older { peg = try await query.info(target, item: "revision", revision: fixedRevision) }
            let start = older ? String(max(0, (Int(records.last?.revision ?? "0") ?? 0) - 1)) : peg
            let result = try await query.history(target, peg: peg, start: start)
            if older { records += result } else { records = result; selection = result.first?.revision }
            more = result.count == 100 && (Int(result.last?.revision ?? "0") ?? 0) > 0
        } catch { self.error = error.localizedDescription }
    }
}

private func dateLabel(_ value: String) -> String {
    let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return (formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value))?.formatted(date: .abbreviated, time: .shortened) ?? value
}
private struct QueryHeader: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    let title: String
    var body: some View {
        let _ = interfaceLanguage; Text(title).font(.system(size: 12, weight: .semibold)).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 8).padding(.vertical, 5).background(WorkbenchTheme.panel) }
}
struct HistoryWindow: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @StateObject var model: HistoryModel
    var body: some View {
        let _ = interfaceLanguage;
        VStack(spacing: 0) {
            HStack {
                Button { Task { await model.load() } } label: { Label(L("Refresh"), systemImage: "arrow.clockwise") }.disabled(model.busy)
                Button(L("Load Older")) { Task { await model.load(older: true) } }.disabled(model.busy || !model.more)
                Spacer()
                TextField(L("Filter revisions, authors and messages"), text: $model.filter).textFieldStyle(.roundedBorder).frame(width: 300)
            }.padding(8).background(WorkbenchTheme.panel)
            Text(model.target).font(.system(size: 11)).lineLimit(1).truncationMode(.middle).frame(maxWidth: .infinity, alignment: .leading).padding(8)
            Divider()
            VSplitView {
                HSplitView {
                    VStack(spacing: 0) {
                        QueryHeader(title: L("Revisions"))
                        WorkspaceTable(columns: [.init(title: L("Revision"), width: 75), .init(title: L("Message"), width: 310), .init(title: L("Author"), width: 100), .init(title: L("Date"), width: 155)], rows: model.visible.map { .init(id: $0.revision, values: [$0.revision, $0.message.replacingOccurrences(of: "\n", with: " "), $0.author, dateLabel($0.date)], symbol: "square.stack.3d.up") }, selection: $model.selection)
                    }.frame(minWidth: 480)
                    VStack(spacing: 0) {
                        QueryHeader(title: L("Revision Info"))
                        ScrollView {
                            if let item = model.current {
                                VStack(alignment: .leading, spacing: 12) {
                                    Text(T("Revision {0}", "修订号 {0}", item.revision)).font(.system(size: 18, weight: .semibold))
                                    Label(item.author.isEmpty ? L("Unknown author") : item.author, systemImage: "person")
                                    Label(dateLabel(item.date), systemImage: "clock")
                                    Divider(); Text(item.message).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                                }.padding(14)
                            } else { Text(L("Select a revision")).foregroundStyle(WorkbenchTheme.muted).padding(20) }
                        }
                    }.frame(minWidth: 240, idealWidth: 290, maxWidth: 340)
                }.frame(minHeight: 230)
                HSplitView {
                    VStack(spacing: 0) {
                        QueryHeader(title: L("Directories"))
                        List(model.directories, id: \.self, selection: $model.directory) { path in Label(path == "/" ? L("All Changed Paths") : path, systemImage: "folder").font(.system(size: 12)).tag(path) }.listStyle(.sidebar)
                    }.frame(minWidth: 220, idealWidth: 270, maxWidth: 310)
                    VStack(spacing: 0) {
                        QueryHeader(title: L("Changed Paths — entire commit"))
                        WorkspaceTable(columns: [.init(title: L("Path"), width: 390), .init(title: L("Action"), width: 65), .init(title: L("Copy From"), width: 220), .init(title: L("Revision"), width: 70)], rows: model.paths.map { .init(id: $0.path, values: [$0.path, $0.action, $0.copyFrom, $0.copyRevision], symbol: "doc", tint: $0.action == "D" ? WorkbenchTheme.dangerNS : $0.action == "A" ? WorkbenchTheme.successNS : .systemOrange) }, selection: $model.pathSelection, onDoubleClick: { Task { await model.compareSelection() } })
                            .help(T("Double-click a file to compare with its previous revision", "双击文件，查看该次修改与前一版本的差异"))
                    }.frame(minWidth: 440)
                }.frame(minHeight: 180)
            }
            QueryStatus(busy: model.busy, error: model.error, text: T("{0} revisions · {1} changed paths", "{0} 条修订 · {1} 个变更路径", model.visible.count, model.current?.paths.count ?? 0))
        }.font(.system(size: 12)).background(WorkbenchTheme.canvas).task { await model.load() }
        .onChange(of: model.selection) { _, _ in model.directory = "/"; model.pathSelection = nil }
    }
}

@MainActor final class BrowserModel: ObservableObject {
    let query = RepositoryQuery()
    @Published var address: String
    @Published var revision = "HEAD"
    @Published var location = ""
    @Published var resolvedRevision = ""
    @Published var rootURL = ""
    @Published var entries: [RepositoryEntry] = []
    @Published var selection: String?
    @Published var busy = false
    @Published var error = ""
    @Published var visited: [String] = []
    private var request = 0
    init(url: String) { address = url }
    var current: RepositoryEntry? { entries.first { $0.name == selection } }
    func childURL(_ name: String) -> String { URL(string: location)?.appendingPathComponent(name).absoluteString ?? location }
    func navigate(_ url: String? = nil) async {
        let destination = (url ?? address).trimmingCharacters(in: .whitespacesAndNewlines)
        let requestedRevision = revision.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parsed = URL(string: destination), ["file", "http", "https", "svn", "svn+ssh"].contains(parsed.scheme ?? ""), requestedRevision == "HEAD" || UInt(requestedRevision) != nil else { error = L("请输入有效仓库 URL 和 HEAD 或非负修订号。"); return }
        request += 1; let token = request; busy = true; error = ""
        do {
            let fixed = try await query.info(destination, item: "revision", revision: requestedRevision)
            let root = try await query.info(destination, item: "repos-root-url", revision: fixed)
            let result = try await query.list(destination, revision: fixed)
            guard token == request else { return }
            location = destination; address = destination; resolvedRevision = fixed; rootURL = root
            entries = result.sorted { $0.kind == $1.kind ? $0.name.localizedStandardCompare($1.name) == .orderedAscending : $0.kind == "dir" }
            selection = nil
            if !visited.contains(destination) { visited.append(destination) }
        } catch { if token == request { self.error = error.localizedDescription } }
        if token == request { busy = false }
    }
    func openSelection() async {
        guard let item = current, !busy else { return }
        let url = childURL(item.name), fixed = resolvedRevision
        if item.kind == "dir" { revision = fixed; await navigate(url); return }
        guard item.size <= 1_048_576 else { error = L("文件超过 1 MB，暂不提供文本预览。"); return }
        busy = true; error = ""
        do { let text = try await query.content(url, revision: fixed); QueryWindows.shared.preview("\(item.name) — r\(fixed)", text: text) }
        catch { self.error = error.localizedDescription }
        busy = false
    }
}
struct RepositoryWindow: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @StateObject var model: BrowserModel
    var body: some View {
        let _ = interfaceLanguage;
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button { if let url = URL(string: model.location) { Task { model.revision = model.resolvedRevision; await model.navigate(url.deletingLastPathComponent().absoluteString) } } } label: { Label(L("Up"), systemImage: "arrow.up") }.disabled(model.location.isEmpty || model.location.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == model.rootURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) || model.busy)
                Button { Task { await model.navigate(model.location) } } label: { Label(L("Refresh"), systemImage: "arrow.clockwise") }.disabled(model.location.isEmpty || model.busy)
                Divider().frame(height: 20)
                Button { Task { await model.openSelection() } } label: { Label(L("Open"), systemImage: "doc.text.magnifyingglass") }.disabled(model.current == nil || model.busy)
                Button { QueryWindows.shared.log(model.current.map { model.childURL($0.name) } ?? model.location, revision: model.resolvedRevision) } label: { Label(L("Log"), systemImage: "clock.arrow.circlepath") }.disabled(model.location.isEmpty)
                Spacer(); Text(L("Revision")); TextField("HEAD", text: $model.revision).frame(width: 75).onSubmit { Task { await model.navigate() } }
            }.padding(10).background(WorkbenchTheme.panel)
            HStack {
                Text("URL:"); TextField(L("Repository URL"), text: $model.address).textFieldStyle(.roundedBorder).onSubmit { Task { await model.navigate() } }
                Button(L("Go")) { Task { await model.navigate() } }.disabled(model.busy)
            }.padding(8)
            Divider()
            HSplitView {
                VStack(spacing: 0) {
                    QueryHeader(title: L("Directories"))
                    ScrollView {
                        if !model.rootURL.isEmpty {
                            BrowserTreeBranch(url: model.rootURL, revision: model.resolvedRevision, selected: model.location, navigate: { url in Task { model.revision = model.resolvedRevision; await model.navigate(url) } })
                                .id(model.rootURL + "@" + model.resolvedRevision).padding(6).frame(maxWidth: .infinity, alignment: .topLeading)
                        }
                    }
                }.frame(minWidth: 180, idealWidth: 220, maxWidth: 260)
                VStack(spacing: 0) {
                    QueryHeader(title: model.location.isEmpty ? L("Repository") : "\(model.location)  @ \(model.resolvedRevision)")
                    WorkspaceTable(columns: [.init(title: L("Name"), width: 260), .init(title: L("Revision"), width: 80), .init(title: L("Author"), width: 120), .init(title: L("Size"), width: 90), .init(title: L("Date"), width: 170)], rows: model.entries.map { .init(id: $0.name, values: [$0.name, $0.revision, $0.author, $0.kind == "dir" ? "" : ByteCountFormatter.string(fromByteCount: $0.size, countStyle: .file), dateLabel($0.date)], symbol: $0.kind == "dir" ? "folder.fill" : "doc", tint: $0.kind == "dir" ? WorkbenchTheme.warningNS : WorkbenchTheme.mutedNS) }, selection: $model.selection, onDoubleClick: { if let item = model.current, item.kind != "dir" { QueryWindows.shared.compare(model.childURL(item.name), revision: model.resolvedRevision) } else { Task { await model.openSelection() } } })
                        .overlay { if model.entries.isEmpty && !model.busy && model.error.isEmpty { Text(model.location.isEmpty ? L("Enter a repository URL to browse") : L("This directory is empty")).foregroundStyle(WorkbenchTheme.muted) } }
                }.frame(minWidth: 570)
            }
            QueryStatus(busy: model.busy, error: model.error, text: T("{0} items · Revision {1} · Read only", "{0} 项 · 修订号 {1} · 只读", model.entries.count, model.resolvedRevision))
        }.font(.system(size: 12)).background(WorkbenchTheme.canvas).task { if !model.address.isEmpty { await model.navigate() } }
    }
}
private struct QueryStatus: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    let busy: Bool
    let error: String
    let text: String
    var body: some View {
        let _ = interfaceLanguage;
        VStack(spacing: 0) {
            Divider()
            if !error.isEmpty { ScrollView { Text(L(error)).foregroundStyle(WorkbenchTheme.danger).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(8) }.frame(maxHeight: 85) }
            HStack { if busy { ProgressView().controlSize(.small); Text(L("Loading…")) } else { Text(text) }; Spacer() }.font(.system(size: 11)).padding(7).background(WorkbenchTheme.panel)
        }
    }
}

private struct BrowserTreeBranch: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    let url: String
    let revision: String
    let selected: String
    let navigate: (String) -> Void
    @State private var expanded = false
    @State private var children: [RepositoryEntry] = []
    @State private var loaded = false
    @State private var failure = ""
    var body: some View {
        let _ = interfaceLanguage;
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Button { expanded.toggle() } label: { Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.system(size: 9)).frame(width: 12, height: 20) }.buttonStyle(.plain)
                Button { navigate(url) } label: {
                    HStack(spacing: 5) {
                        Image(systemName: "folder.fill").foregroundStyle(WorkbenchTheme.warning)
                        Text(URL(string: url)?.lastPathComponent ?? url).lineLimit(1)
                    }.padding(.trailing, 8).frame(height: 20)
                }.buttonStyle(.plain).help(url)
            }.background(selected.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == url.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ? Color.accentColor.opacity(0.14) : .clear)
            if expanded {
                if !loaded && failure.isEmpty { Text(L("Loading…")).foregroundStyle(WorkbenchTheme.muted).padding(.leading, 20) }
                if !failure.isEmpty { Button(L("Retry loading")) { loaded = false; expanded = false; failure = "" }.help(failure).padding(.leading, 20) }
                ForEach(children, id: \.name) { entry in
                    BrowserTreeBranch(url: URL(string: url)!.appendingPathComponent(entry.name).absoluteString, revision: revision, selected: selected, navigate: navigate).padding(.leading, 16)
                }
            }
        }.font(.system(size: 12)).onAppear { if selected.hasPrefix(url.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/") { expanded = true } }.task(id: expanded) {
            if expanded && !loaded {
                do { let result = try await RepositoryQuery().list(url, revision: revision); children = result.filter { $0.kind == "dir" }; loaded = true }
                catch { failure = error.localizedDescription }
            }
        }
    }
}
