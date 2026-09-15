import AppKit
import Combine
import SwiftUI
import SVNCore

private struct CommitComparisonTarget: Identifiable {
    let path: String
    let isDirectory: Bool
    var id: String { path }
}

struct ContentView: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @StateObject var m = Model()
    @State private var listingCache = FileListingCache()
    @State private var directorySearch = ""
    @State private var showDirectories = true
    @State private var commitDirectory = ""
    @State private var commitFilter = ""
    @State private var commitFocus: String?
    @State private var commitDiffTarget: CommitComparisonTarget?
    @State private var commitDirectoryDiff = ""
    @State private var showCommitHistory = false
    @State private var commitHistory: [LogItem] = []
    @State private var commitHistoryError: String?
    @State private var loadingCommitHistory = false
    @State private var commitStateFilter = "all"
    @State private var showCommit = false
    @State private var showIgnored = false
    @State private var selectedFileIDs = Set<String>()
    @State private var recursive = true
    @State private var showUnversioned = true
    @AppStorage("SvnFlow.showUnchangedFiles") private var showUnchanged = false
    private let chrome = WorkbenchTheme.panel
    private let border = WorkbenchTheme.border

    private var commands: Publishers.MergeMany<NotificationCenter.Publisher> {
        Publishers.MergeMany([.openWorkingCopy, .checkoutWorkingCopy, .closeWorkingCopy, .refreshWorkingCopy,
            .updateWorkingCopy, .commitChanges, .addSelected, .removeSelected, .moveSelected, .revertSelected,
            .deleteSelected, .switchWorkingCopy, .createBranch, .mergeChanges, .showLog, .showProperties,
            .showAnnotate, .lockSelected, .unlockSelected, .showRepository, .cleanupWorkingCopy,
            .mainPerspective, .reviewPerspective, .compareFile].map { NotificationCenter.default.publisher(for: $0) })
    }
    var body: some View {
        let _ = interfaceLanguage;
        VStack(spacing: 0) {
            toolbar
            Divider()
            operationToolbar
            Divider()
            GeometryReader { geometry in fileWorkspace(width: geometry.size.width) }
            if m.busy || m.restoringCache || m.backgroundValidation { statusBar }
        }
        .font(.system(size: 12)).workbenchStyle()

        .frame(minWidth: 1040, minHeight: 660)
        .background(WorkspaceWindowStyle(title: (m.isUIPreview ? "Client" : (m.selected?.name ?? AppIdentity.name)) + " — " + AppIdentity.title + (m.isUIPreview ? " · UI Preview" : ""), preventsClose: m.reverting))
        .alert(L("Operation Failed"), isPresented: Binding(get: { m.error != nil && !showCommit }, set: { if !$0 { m.error = nil } })) {
            Button(L("OK")) { m.error = nil }
        } message: { Text(m.error ?? "") }
        .sheet(isPresented: $showCommit) { commitSheet }
        .sheet(isPresented: $showIgnored) { LocalIgnoreSheet(model: m) }
        .onReceive(commands, perform: handleCommand)
        .onChange(of: m.selectedID) { _, _ in selectedFileIDs = []; m.selectedEntryID = nil; m.revertSummary = nil; Task { await m.activateCopy() } }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in m.checkExternalChanges() }
        .onReceive(Timer.publish(every: 30, on: .main, in: .common).autoconnect()) { _ in if NSApp.isActive { m.checkExternalChanges() } }
        .onChange(of: m.busy) { _, busy in if !busy { clearHiddenSelection() } }
        .onChange(of: m.selectedDirectory) { _, _ in clearHiddenSelection() }
        .onChange(of: showUnchanged) { _, _ in clearHiddenSelection() }
        .onChange(of: m.filter) { _, _ in clearHiddenSelection() }
        .onChange(of: recursive) { _, _ in clearHiddenSelection() }
        .onChange(of: showUnversioned) { _, _ in clearHiddenSelection() }
        .onChange(of: interfaceLanguage) { _, _ in localizeSystemMenus() }
        .task {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { localizeSystemMenus() }
            if m.selected != nil {
                await m.activateCopy()
                if m.isUIPreview {
                    m.selectedEntryID = m.statuses.first(where: { $0.state == .modified && $0.path.hasSuffix(".cs") })?.path
                    await m.loadLogs()
                }
            }
        }
    }

    var toolbar: some View {
        HStack(spacing: 22) {
            WorkbenchHeading(eyebrow: "WORKSPACE / 01", title: T("Directory & Diff", "目录与差异"), subtitle: "", symbol: "folder.badge.gearshape")
            Rectangle().fill(border).frame(width: 1, height: 36)
            Menu {
                ForEach(m.treeCopies) { copy in
                    Button(copy.name) {
                        if copy.path.isEmpty { m.configureSlot(copy.id) }
                        else { m.selectedID = copy.id; m.selectedDirectory = ""; directorySearch = "" }
                    }
                }
                Divider()
                Button(T("Change source folder…", "修改源目录…") + "（\(m.mergeEndpoints.sourceName)）") { m.configureSlot(Model.devID) }
                Button(T("Change target folder…", "修改目标目录…") + "（\(m.mergeEndpoints.targetName)）") { m.configureSlot(Model.releaseID) }
            } label: { Label(m.selectedDisplayName, systemImage: "externaldrive") }
            .menuStyle(.borderlessButton).fixedSize().disabled(m.busy || m.restoringCache)
            Text(m.selected?.path ?? T("Select a working copy to begin", "选择工作副本开始浏览"))
                .font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted).lineLimit(1).truncationMode(.middle).help(m.selected?.path ?? "")
            Spacer(minLength: 0)
            Button { Task { await m.refresh() } } label: { Label(L("Refresh"), systemImage: "arrow.clockwise") }.disabled(!hasProject)
            LanguageMenu().labelStyle(.iconOnly).frame(width: 26)
        }.padding(.horizontal, 24).padding(.vertical, 18).background(WorkbenchTheme.canvas)
    }
    var operationToolbar: some View {
        HStack(spacing: 10) {
            Button { openCommit() } label: { Label(T("Commit…", "提交…"), systemImage: "checkmark.circle") }
                .buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(!hasProject)
                .help("先选择文件并填写说明，再确认提交到 SVN")
            Button { Task { await m.update() } } label: { Label(L("Update"), systemImage: "arrow.down.circle") }.disabled(!hasProject)
                .help(L("更新范围：") + (m.selectedDirectory.isEmpty ? (m.selected?.path ?? "") : m.selectedDirectory))
            Button { QueryWindows.shared.openBranchSync() } label: { Label("分支合入…", systemImage: "arrow.triangle.branch") }.disabled(!hasProject)
                .help("打开 \(m.mergeEndpoints.direction) 文件合入工具")
            Divider().frame(height: 22)
            Button { if let path = m.selectedEntryID { openComparison(path) } } label: { Label("查看差异", systemImage: "doc.text.magnifyingglass") }.disabled(!hasSelection)
            Button { openHistory() } label: { Label("提交记录", systemImage: "clock.arrow.circlepath") }.disabled(!hasProject)
            Spacer(minLength: 8)
            Menu("更多操作") {
                Button("添加到版本管理") { chooseFile(); Task { await m.addFiles() } }.disabled(!hasSelection)
                Button("移动所选文件…") { Task { await m.moveSelected() } }.disabled(!hasSelection)
                Button("移出版本管理（保留本地）…") { chooseFile(); Task { await m.deleteSelected(keepLocal: true) } }.disabled(!hasSelection)
                Divider()
                Button("回退所选本地修改…", role: .destructive, action: revertFiles).disabled(!hasProject || revertCount == 0)
                Button("标记为删除…", role: .destructive) { chooseFile(); Task { await m.deleteSelected() } }.disabled(!hasSelection)
                Divider()
                Button("逐行追溯") { Task { await m.annotate(); QueryWindows.shared.preview(L("Annotate"), text: m.output) } }.disabled(!hasSelection)
                Button("按 SVN URL 合并…") { merge() }.disabled(!hasProject)
                Button("清理工作副本") { Task { await m.cleanup() } }.disabled(!hasProject)
            }.fixedSize()
        }.padding(.horizontal, 24).padding(.vertical, 12).background(chrome)
    }
    private var operationSeparator: some View {
        Rectangle().fill(border).frame(width: 1, height: 30).padding(.horizontal, 6)
    }
    var hasProject: Bool { m.selected != nil && !m.busy && !m.restoringCache && !m.reverting }
    var hasSelection: Bool { hasProject && m.selectedEntryID != nil }
    private var selectedExportFiles: Set<String> {
        let selected = selectedFileIDs.isEmpty ? Set([m.selectedEntryID].compactMap { $0 }) : selectedFileIDs
        return Set(displayedFiles.filter { selected.contains($0.path) && !$0.isDirectory && WorkbookExportScope.supports($0.path) }.map(\.path))
    }
    private func openConfigurationExport() {
        guard hasProject, let copy = m.selected else { return }
        do { try QueryWindows.shared.openConfigurationExport(workingCopy: copy.path, selection: selectedExportFiles, label: copy.pathDisplayName) }
        catch { m.error = error.localizedDescription }
    }
    private var visibleSelection: Set<String> {
        let selected = selectedFileIDs.isEmpty ? Set([m.selectedEntryID].compactMap { $0 }) : selectedFileIDs
        return selected.intersection(Set(displayedFiles.map(\.path)))
    }
    private var revertCount: Int {
        let selected = visibleSelection
        return displayedFiles.filter { selected.contains($0.path) && RevertScope.supports($0.state) }.count
    }
    private func selectAllFiles() {
        guard hasProject else { return }
        selectedFileIDs = Set(displayedFiles.map(\.path))
        m.selectedEntryID = displayedFiles.first?.path
    }
    private func deselectFiles() {
        guard hasProject else { return }
        selectedFileIDs = []; m.selectedEntryID = nil
    }
    private func revertFiles() {
        guard hasProject, revertCount > 0 else { return }
        let paths = visibleSelection
        Task {
            let reverted = await m.revert(paths: paths)
            selectedFileIDs.subtract(reverted)
            if let focus = m.selectedEntryID, reverted.contains(focus) { m.selectedEntryID = selectedFileIDs.sorted().first }
            clearHiddenSelection()
        }
    }
    private var selectionToolbar: some View {
        HStack(spacing: 12) {
            Button(T("Select all", "全选"), action: selectAllFiles)
                .disabled(!hasProject || displayedFiles.isEmpty)
                .help(T("Select all files in the current directory and search results (⌘A in the list)", "全选当前目录与筛选结果中的文件（列表内可按 ⌘A）"))
            Button(T("Deselect all", "取消全选"), action: deselectFiles)
                .disabled(!hasProject || visibleSelection.isEmpty)
            Button(action: revertFiles) {
                Label(revertCount == 0 ? T("Revert selected…", "回退所选…") : T("Revert selected ({0})…", "回退所选（{0}）…", revertCount), systemImage: "arrow.uturn.backward")
                    .foregroundStyle(hasProject && revertCount > 0 ? WorkbenchTheme.danger : WorkbenchTheme.muted)
            }.disabled(!hasProject || revertCount == 0)
                .help(T("Confirm before discarding versioned local changes; unversioned files are skipped", "确认后丢弃所选版本化本地改动；跳过未纳入版本的文件"))
            Text(T("Selected {0} / {1} · {2} revertible", "已选 {0} / {1} 项 · 可回退 {2} 项", visibleSelection.count, displayedFiles.count, revertCount))
                .font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted)
            Spacer(minLength: 0)
        }
    }
    func chooseFile() { m.selectedPaths = selectedFileIDs.isEmpty ? Set([m.selectedEntryID].compactMap { $0 }) : selectedFileIDs }
    func merge() { if let url = m.ask(L("Merge"), L("Repository source URL"), placeholder: "SVN URL") { m.mergeSource = url; Task { await m.merge(false) } } }

    func fileWorkspace(width: CGFloat) -> some View {
        WorkbenchFileSplit(showsLeft: showDirectories) {
                VStack(spacing: 0) {
                    HStack { Text(T("Directories", "目录")).font(.system(size: 14, weight: .semibold)); Spacer(); Image(systemName: "sidebar.left").foregroundStyle(WorkbenchTheme.muted) }.padding(18)
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(WorkbenchTheme.muted)
                        TextField(T("Find directory or path", "搜索目录或路径"), text: $directorySearch).textFieldStyle(.plain)
                        if !directorySearch.isEmpty { Button { directorySearch = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain) }
                    }.padding(10).background(WorkbenchTheme.raised, in: RoundedRectangle(cornerRadius: 6)).padding(.horizontal, 16).padding(.bottom, 12)
                    if !directorySearch.isEmpty {
                        let matches = m.directories.filter { $0.relative.localizedStandardContains(directorySearch) }
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 4) {
                                ForEach(Array(matches.prefix(100))) { directory in
                                    Button { m.selectedDirectory = directory.relative } label: {
                                        VStack(alignment: .leading, spacing: 5) {
                                            Label(directory.name, systemImage: "folder")
                                            Text(directory.relative).font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted).lineLimit(2)
                                        }.frame(maxWidth: .infinity, alignment: .leading).padding(10)
                                            .background(m.selectedDirectory == directory.relative ? WorkbenchTheme.raised : .clear, in: RoundedRectangle(cornerRadius: 6))
                                    }.buttonStyle(.plain)
                                }
                                if matches.isEmpty { Text(T("No matching directories", "没有匹配的目录")).foregroundStyle(WorkbenchTheme.muted).padding(12) }
                                if matches.count > 100 { Text(T("First 100 results; refine your search", "显示前 100 项，请缩小搜索范围")).foregroundStyle(WorkbenchTheme.muted).padding(12) }
                            }.padding(.horizontal, 12)
                        }
                    } else {
                    WorkspaceTree(projectTitle: m.isUIPreview ? "Client" : L("Working Copies"), copies: m.treeCopies, directories: m.treeDirectories, changes: m.treeChanges, contentVersion: m.indexVersion, selectedCopy: m.selectedID, selectedDirectory: m.selectedDirectory) { copy, directory in
                        if m.copies.contains(where: { $0.id == copy }) { m.selectedID = copy; m.selectedDirectory = directory }
                        else { m.configureSlot(copy) }
                    }.background(WorkbenchTheme.canvas)
                    }
                }.background(WorkbenchTheme.canvas)
        } right: {
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(m.selectedDirectory.isEmpty ? (m.selected?.name ?? T("Changed files", "改动文件")) : (m.selectedDirectory as NSString).lastPathComponent)
                                .font(.system(size: 22, weight: .semibold)).lineLimit(1)
                            Text(m.selectedDirectory.isEmpty ? T("Select a directory · Double-click a file to compare", "选择左侧目录 · 双击文件查看差异") : m.selectedDirectory)
                                .font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted).lineLimit(1).truncationMode(.middle).help(m.selectedDirectory)
                        }
                        Spacer()
                        if !selectedExportFiles.isEmpty {
                            Button { openConfigurationExport() } label: { Label("配置导出", systemImage: "tablecells.badge.ellipsis") }
                                .disabled(!hasProject)
                                .help("导出所选本地 Excel 配置（.xlsx），核验后自动生成 Lua、pmdata 到对应目录")
                        }
                        Button { if let path = m.selectedEntryID { openComparison(path) } } label: { Label(T("Open Diff", "查看差异"), systemImage: "arrow.up.right") }
                            .buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(!hasSelection)
                    }
                    HStack(spacing: 14) {
                        HStack {
                            Image(systemName: "magnifyingglass").foregroundStyle(WorkbenchTheme.muted)
                            TextField(T("Find file or path", "搜索文件或路径"), text: $m.filter).textFieldStyle(.plain)
                            if !m.filter.isEmpty { Button { m.filter = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain) }
                        }.padding(9).frame(maxWidth: 320).background(WorkbenchTheme.raised, in: RoundedRectangle(cornerRadius: 6))
                        Toggle(T("All files", "显示全部文件"), isOn: $showUnchanged).toggleStyle(.checkbox)
                        Menu {
                            Toggle(L("Show Unversioned Files"), isOn: $showUnversioned)
                            Toggle(T("Include unchanged files in subdirectories", "包含子目录中的未修改文件"), isOn: $recursive)
                            Divider()
                            Button(L("管理忽略项…")) { showIgnored = true }
                        } label: { Image(systemName: "line.3.horizontal.decrease.circle") }.menuStyle(.borderlessButton).frame(width: 26).help(T("Display options", "显示选项"))
                        Spacer(minLength: 0)
                        Text(T("{0} files", "{0} 个文件", displayedFiles.count)).font(.system(size: 11, design: .monospaced)).foregroundStyle(WorkbenchTheme.muted)
                    }
                    selectionToolbar
                    if let summary = m.revertSummary {
                        HStack {
                            Text(summary).font(.system(size: 12)).foregroundStyle(WorkbenchTheme.success)
                            Spacer()
                            Button { m.revertSummary = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain).help(T("Dismiss", "关闭提示"))
                        }
                    }
                }.padding(24).background(WorkbenchTheme.canvas)
                Divider()
                ZStack {
                    WorkspaceTable(columns: fileColumns, rows: fileRows, selection: $m.selectedEntryID, multipleSelection: $selectedFileIDs, onDoubleClick: { if let path = m.selectedEntryID { openComparison(path) } }, contextActions: { path in [
                        .init(title: T("Select all", "全选"), perform: selectAllFiles, enabled: hasProject && !displayedFiles.isEmpty),
                        .init(title: T("Deselect all", "取消全选"), perform: deselectFiles, enabled: hasProject && !visibleSelection.isEmpty),
                        .init(title: T("Revert selected ({0})…", "回退所选（{0}）…", revertCount), perform: revertFiles, enabled: hasProject && revertCount > 0),
                        .init(title: L("忽略此项（本地显示）"), perform: { for target in selectedFileIDs { m.hideLocally(target) } }),
                        .init(title: L("Show Changes"), perform: { m.selectedEntryID = path; openComparison(path) }),
                        .init(title: L("Log…"), perform: { QueryWindows.shared.log(path) }),
                        .init(title: L("Open in Repository Browser"), perform: { Task { do { let url = try await RepositoryQuery().info(path, item: "url"); QueryWindows.shared.repository(URL(string: url)?.deletingLastPathComponent().absoluteString ?? url) } catch { m.error = error.localizedDescription } } }),
                        .init(title: L("Reveal in Finder"), perform: { NSWorkspace.shared.activateFileViewerSelecting(selectedFileIDs.sorted().map { URL(fileURLWithPath: $0) }) }),
                        .init(title: L("Copy Path"), perform: { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(selectedFileIDs.sorted().joined(separator: "\n"), forType: .string) })
                    ] })
                    if m.busy {
                        VStack(spacing: 12) {
                            if m.updateStage > 0 {
                                Text(L(m.activity)).font(.system(size: 13, weight: .medium))
                                ProgressView().progressViewStyle(.linear).frame(width: 380)
                                HStack {
                                    Text(T("Stage {0}/3 · {1}", "阶段 {0}/3 · {1}", m.updateStage, [L("Update"), L("Local State"), L("Refresh")][m.updateStage - 1]))
                                    Spacer()
                                    Text(T("{0} files processed", "已处理 {0} 个文件", m.updateCount))
                                }.font(.system(size: 12))
                                Text(m.updateDetail).font(.system(size: 11)).lineLimit(2).truncationMode(.middle).frame(maxWidth: .infinity, alignment: .leading)
                                HStack {
                                    Text(T("SVN does not report a total; the bar indicates ongoing activity", "SVN 未提供总量，进度条表示任务仍在进行"))
                                    Spacer()
                                    Text(m.updateStarted, style: .relative)
                                }.font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted)
                            } else {
                                ProgressView().controlSize(.large)
                                Text(L(m.activity)).font(.system(size: 13, weight: .medium))
                                Text(L("大型工作副本加载需要一些时间，请稍候。")).font(.system(size: 12)).foregroundStyle(WorkbenchTheme.muted)
                            }
                        }.frame(width: m.updateStage > 0 ? 440 : 310).padding(24).workbenchSecondarySurface().allowsHitTesting(false)
                    }
                    if m.selected != nil && displayedFiles.isEmpty && !m.busy && !m.restoringCache {
                        VStack(spacing: 8) {
                            Image(systemName: m.filter.isEmpty ? "checkmark.circle" : "magnifyingglass").font(.system(size: 28, weight: .light)).foregroundStyle(WorkbenchTheme.muted)
                            Text(m.filter.isEmpty ? T("No visible changes", "当前范围没有可显示的改动") : L("No matching files")).font(.system(size: 13, weight: .medium))
                            if !m.filter.isEmpty {
                                Button(T("Clear filter", "清除筛选")) { m.filter = "" }
                            } else {
                                Text(showUnchanged ? T("This folder has no visible files", "此目录没有可显示的文件") : T("Enable Show Unchanged to browse all files", "开启“显示全部文件”可浏览文件")).foregroundStyle(WorkbenchTheme.muted)
                            }
                        }.font(.system(size: 12))
                    }
                    if m.selected == nil {
                        VStack(spacing: 12) {
                            Text(L("Open a working copy to get started.")).foregroundStyle(WorkbenchTheme.muted)
                            HStack { Button(L("Open Working Copy…"), action: m.add); Button(L("Check Out…"), action: m.checkout) }
                        }
                    }
                }.background(WorkbenchTheme.canvas).overlay(Rectangle().stroke(border, lineWidth: 0.5))
            }
        }
    }
    func openComparison(_ path: String) {
        guard !m.isHidden(path) else { return }
        if m.localEntries.first(where: { $0.path == path })?.isDirectory == true {
            Task {
                do { let diff = try await m.svn.run(["diff", "--depth", "empty", "--", path]); QueryWindows.shared.preview(T("Directory Changes — {0}", "目录差异 — {0}", URL(fileURLWithPath: path).lastPathComponent), text: diff.isEmpty ? L("该目录没有可显示的文本或属性差异。子项变化请在文件列表中选择。") : diff) }
                catch { m.error = error.localizedDescription }
            }
        } else { QueryWindows.shared.compare(path) }
    }
    func clearHiddenSelection() {
        selectedFileIDs.formIntersection(Set(displayedFiles.map(\.path)))
        if let selected = m.selectedEntryID, !displayedFiles.contains(where: { $0.path == selected }) { m.selectedEntryID = nil }
    }
    var listing: FileListingCache.Result {
        listingCache.resolve(version: m.indexVersion, directory: m.selectedDirectory, recursive: recursive,
                             unchanged: showUnchanged, unversioned: showUnversioned, filter: m.filter, ignored: m.ignoredPaths, index: m.listingIndex)
    }

    var displayedFiles: [LocalEntry] { listing.shown }
    var fileColumns: [WorkspaceColumn] { [
        .init(title: L("Name"), width: 270), .init(title: L("Local State"), width: 100),
        .init(title: L("Relative Directory"), width: 380)
    ] }
    var fileRows: [WorkspaceTableRow] {
        let files = displayedFiles
        return listingCache.rows(branch: m.selected?.branch ?? "") { files.map { item in
        WorkspaceTableRow(id: item.path, values: [item.name, (item.state == .modified && item.propertyState == "modified" ? L("Properties Modified") : stateTitle(item.state)), (item.relative as NSString).deletingLastPathComponent], symbol: item.isDirectory ? "folder.badge.gearshape" : item.state == .normal ? "doc" : item.state == .modified ? "doc.badge.ellipsis" : item.state.icon, tint: stateTint(item.state))
    } } }
    func stateTitle(_ state: ItemState) -> String {
        switch state { case .normal: ""; case .modified: L("Modified"); case .added: L("Added"); case .deleted: L("Removed"); case .missing: L("Missing"); case .unversioned: L("Unversioned"); case .conflicted: L("Conflicted"); default: state.rawValue.capitalized }
    }
    func stateTint(_ state: ItemState) -> NSColor {
        switch state { case .modified: WorkbenchTheme.accentNS; case .added, .unversioned: WorkbenchTheme.successNS; case .deleted, .missing, .conflicted: WorkbenchTheme.dangerNS; default: WorkbenchTheme.mutedNS }
    }
    var statusBar: some View {
        HStack(spacing: 10) {
            if !showDirectories { Button(L("Directories")) { showDirectories = true }.buttonStyle(.plain) }
            Text(m.busy ? L(m.activity) : (m.selectedEntryID ?? m.selected?.name ?? T("No working copy", "未选择工作副本"))).lineLimit(1).truncationMode(.middle).help(m.selectedEntryID ?? m.selected?.url ?? "")
            Spacer()
            if m.restoringCache {
                ProgressView().controlSize(.mini)
                Text(T("Restoring cached list…", "正在恢复缓存列表…")).foregroundStyle(WorkbenchTheme.muted)
            }
            if m.backgroundValidation {
                ProgressView().controlSize(.mini)
                Text(m.refreshLabel).foregroundStyle(WorkbenchTheme.muted)
            }
            if !m.updateTiming.isEmpty { Text(m.updateTiming).lineLimit(1).help(m.updateTiming).foregroundStyle(WorkbenchTheme.muted) }
            Text(m.selectedEntryID == nil ? T("{0} files", "{0} 个文件", displayedFiles.count) : T("{0} files selected", "已选择 {0} 个文件", selectedFileIDs.count))
            if m.isUIPreview { Text(L("Local preview")).foregroundStyle(WorkbenchTheme.muted) }
        }.font(.system(size: 10)).padding(.horizontal, 5).frame(height: 21).background(chrome)
    }
    func openCommit() {
        guard !m.busy, !m.restoringCache, !m.committing, m.selected != nil else { return }
        m.error = nil
        commitDirectory = m.selectedDirectory
        m.selectedPaths = CommitScope.selection(in: commitScopeFiles, selected: selectedFileIDs)
        commitFocus = nil
        commitFilter = ""
        commitStateFilter = "all"
        showCommit = true
    }
    private var commitScopeFiles: [StatusItem] {
        CommitScope.files(m.statuses, directory: commitDirectory)
    }
    private var visibleCommitFiles: [StatusItem] {
        let query = commitFilter.trimmingCharacters(in: .whitespacesAndNewlines)
        return commitScopeFiles.filter { item in
            (query.isEmpty || item.relative.localizedStandardContains(query)) &&
            (commitStateFilter == "all" || item.state.rawValue == commitStateFilter)
        }.sorted { $0.relative.localizedStandardCompare($1.relative) == .orderedAscending }
    }
    var commitSheet: some View {
        let files = visibleCommitFiles
        let visibleEligible = CommitScope.selection(in: files, selected: [])
        let hiddenSelectedCount = m.selectedPaths.subtracting(Set(files.map(\.path))).count
        return VStack(alignment: .leading, spacing: 0) {
            HStack {
                WorkbenchHeading(eyebrow: "COMMIT / 03", title: T("Review & Commit", "检查并提交"), subtitle: commitDirectory.isEmpty ? (m.selected?.name ?? "") : commitDirectory, symbol: "checkmark.seal")
                Spacer()
                Text(T("{0} selected", "已选 {0} 项", m.selectedPaths.count)).foregroundStyle(WorkbenchTheme.accent).monospacedDigit()
                WorkbenchCloseButton(disabled: m.committing, hint: "返回列表，保留提交说明") { showCommit = false }
            }.padding(24)
            Divider()
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    Text(T("Select files", "选择文件")).font(.system(size: 11, weight: .medium)).foregroundStyle(WorkbenchTheme.accent)
                    HStack {
                        TextField(T("Filter filename or path", "筛选文件名或路径"), text: $commitFilter).textFieldStyle(.roundedBorder)
                        Picker(T("State", "状态"), selection: $commitStateFilter) {
                            Text(T("All states", "全部状态")).tag("all")
                            ForEach(Array(Set(commitScopeFiles.map { $0.state.rawValue })).sorted(), id: \.self) { value in
                                Text(stateTitle(ItemState(rawValue: value) ?? .unknown)).tag(value)
                            }
                        }.labelsHidden().frame(width: 120)
                    }.disabled(m.committing)
                    HStack {
                        Text(T("{0} of {1} files", "显示 {0} / {1} 个文件", files.count, commitScopeFiles.count)).foregroundStyle(WorkbenchTheme.muted)
                        Spacer()
                        Button(T("Select results", "全选结果")) { m.selectedPaths.formUnion(visibleEligible) }
                        Button(T("Deselect results", "取消选择")) { m.selectedPaths.subtract(Set(files.map(\.path))) }
                    }.disabled(m.committing)
                    WorkspaceTable(columns: [
                        .init(title: T("State", "状态"), width: 95), .init(title: T("Path", "文件路径"), width: 440)
                    ], rows: files.map { item in
                        WorkspaceTableRow(id: item.path, values: [stateTitle(item.state), item.relative], symbol: "circle.fill", tint: stateTint(item.state))
                    }, selection: $commitFocus, checkedPaths: $m.selectedPaths,
                        canCheck: { visibleEligible.contains($0) }, checkingEnabled: !m.committing,
                        onDoubleClick: { previewCommitDiff() })
                    .overlay { if files.isEmpty { Text(T("No files to commit in this scope", "当前范围没有可提交文件")).foregroundStyle(WorkbenchTheme.muted) } }
                    .overlay(Rectangle().stroke(border, lineWidth: 1))
                    HStack {
                        Text(T("Double-click to compare", "双击文件查看差异")).foregroundStyle(WorkbenchTheme.muted)
                        Spacer()
                        Button(T("Open Diff", "查看差异")) { previewCommitDiff() }.disabled(m.committing || !files.contains { $0.path == commitFocus })
                    }
                    Text(T("Unversioned, conflicted or missing files must be handled first.", "未纳入版本、冲突或缺失文件需先处理。")).font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted)
                }.padding(24).frame(maxWidth: .infinity)
                Divider()
                VStack(alignment: .leading, spacing: 16) {
                    Text(T("Commit message", "提交说明")).font(.system(size: 11, weight: .medium)).foregroundStyle(WorkbenchTheme.accent)
                    HStack {
                        Text(T("Describe this change", "说明本次修改")).font(.system(size: 17, weight: .semibold))
                        Spacer()
                        Button(T("History", "历史说明")) { showCommitHistory = true }.disabled(m.committing)
                    }
                    TextEditor(text: $m.message).font(.system(size: 13)).scrollContentBackground(.hidden)
                        .padding(12).frame(minHeight: 180, maxHeight: .infinity).background(WorkbenchTheme.raised, in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(WorkbenchTheme.controlBorder, lineWidth: 1)).disabled(m.committing)
                    Text(T("Scope includes subdirectories. Review selected files before committing.", "范围包含子目录。提交前请确认左侧勾选文件及差异。")).font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted)
                    if hiddenSelectedCount > 0 { Text(T("{0} selected files hidden by filters", "有 {0} 个已选文件被筛选隐藏", hiddenSelectedCount)).foregroundStyle(WorkbenchTheme.warning) }
                    if let error = m.error { ScrollView { Text(error).foregroundStyle(WorkbenchTheme.danger).textSelection(.enabled) }.frame(maxHeight: 100) }
                    if m.committing { HStack { ProgressView().controlSize(.small); Text(m.busy ? m.activity : T("Waiting for confirmation…", "等待确认提交…")) } }
                }.padding(24).frame(width: 370).background(WorkbenchTheme.panel)
            }.frame(height: 480)
            Divider()
            HStack {
                Label(T("Review files → Write message → Commit", "检查文件 → 填写说明 → 提交"), systemImage: "checklist").foregroundStyle(WorkbenchTheme.muted)
                Spacer()
                Button(T("Back to files", "返回列表")) { showCommit = false }.keyboardShortcut(.cancelAction).disabled(m.committing)
                Button(T("Commit to SVN", "提交到 SVN")) { Task { if await m.commit() { showCommit = false } } }
                    .buttonStyle(WorkbenchButtonStyle(prominent: true)).keyboardShortcut(.defaultAction)
                    .disabled(m.selectedPaths.isEmpty || m.message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || m.busy || m.committing)
            }.padding(20)
        }.frame(width: 1060).workbenchStyle().workbenchSecondarySurface().interactiveDismissDisabled(m.committing)
            .sheet(item: $commitDiffTarget) { target in
                let path = target.path
                    VStack(spacing: 0) {
                        HStack {
                            Text("提交前查看差异").font(.headline)
                            Spacer()
                            WorkbenchCloseButton(title: "返回提交", hint: "保留提交说明和勾选文件") { commitDiffTarget = nil }
                        }.padding(16)
                        Divider()
                        if target.isDirectory {
                            WorkbenchOutputText(text: commitDirectoryDiff).task(id: path) {
                                do {
                                    let result = try await m.svn.run(["diff", "--", path + "@"])
                                    commitDirectoryDiff = result.isEmpty ? T("No text differences to display.", "没有可显示的文本差异。") : result
                                } catch { commitDirectoryDiff = error.localizedDescription }
                            }
                        } else if ["xlsx", "xlsm"].contains(URL(fileURLWithPath: path).pathExtension.lowercased()) {
                            WorkbookCompareWindow(model: WorkbookModel(path: path, revision: nil), showsPin: false)
                        } else {
                            CompareWindow(model: CompareModel(path: path), showsPin: false)
                        }
                        Divider()
                        HStack {
                            Text(T("Close to return to your commit; message and checked files are preserved.", "关闭后返回提交，提交说明和勾选文件保持不变。")).foregroundStyle(WorkbenchTheme.muted)
                            Spacer()
                            Button(T("Back to Commit", "返回提交")) { commitDiffTarget = nil }.keyboardShortcut(.cancelAction)
                        }.font(.system(size: 12)).padding(10)
                    }.id(path).frame(width: 1160, height: 700).workbenchSecondarySurface()
            }
            .sheet(isPresented: $showCommitHistory) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text(T("Choose a previous commit message", "选择历史提交说明")).font(.headline)
                        Spacer()
                        WorkbenchCloseButton { showCommitHistory = false }
                    }
                    if loadingCommitHistory { ProgressView() }
                    if let error = commitHistoryError { Text(error).foregroundStyle(WorkbenchTheme.danger) }
                    List(commitHistory) { item in
                        Button {
                            m.message = item.message
                            showCommitHistory = false
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("r\(item.revision) · \(item.author)").foregroundStyle(WorkbenchTheme.muted)
                                Text(item.message).lineLimit(4).frame(maxWidth: .infinity, alignment: .leading)
                            }.padding(.vertical, 4)
                        }.buttonStyle(.plain)
                    }
                    HStack { Text(T("Selecting an entry replaces the current message.", "选择一条记录将替换当前提交说明。")).foregroundStyle(WorkbenchTheme.muted); Spacer(); Button(L("Cancel")) { showCommitHistory = false }.keyboardShortcut(.cancelAction) }
                }.padding(16).frame(width: 760, height: 480).workbenchSecondarySurface()
                    .task {
                        guard let path = m.selected?.path else { return }
                        loadingCommitHistory = true; commitHistoryError = nil; commitHistory = []
                        defer { loadingCommitHistory = false }
                        do { commitHistory = try await m.svn.logs(path) }
                        catch { commitHistoryError = error.localizedDescription }
                    }
            }
            .interactiveDismissDisabled(m.committing)
            .onAppear { QueryWindows.shared.suspendComparisons() }
            .onDisappear { QueryWindows.shared.resumeComparisons() }
    }

    func previewCommitDiff() {
        guard !m.committing, let path = commitFocus, visibleCommitFiles.contains(where: { $0.path == path }) else { return }
        var isDirectory: ObjCBool = false
        FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory)
        let directory = isDirectory.boolValue || m.localEntries.contains { $0.path == path && $0.isDirectory }
        _commitDirectoryDiff.wrappedValue = T("Loading differences…", "正在加载差异…")
        _commitDiffTarget.wrappedValue = CommitComparisonTarget(path: path, isDirectory: directory)
    }
    func openHistory() {
        if let path = m.selectedEntryID ?? m.selected?.path { QueryWindows.shared.log(path) }
    }

    func handleCommand(_ notification: Notification) {
        switch notification.name {
        case .mainPerspective: break
        case .reviewPerspective: if let path = m.selectedEntryID { openComparison(path) }
        case .openWorkingCopy: m.add()
        case .checkoutWorkingCopy: m.checkout()
        case .closeWorkingCopy: m.remove()
        case .refreshWorkingCopy: Task { await m.refresh() }
        case .updateWorkingCopy: Task { await m.update() }
        case .commitChanges: openCommit()
        case .addSelected: chooseFile(); Task { await m.addFiles() }
        case .removeSelected: chooseFile(); Task { await m.deleteSelected(keepLocal: true) }
        case .moveSelected: Task { await m.moveSelected() }
        case .revertSelected: revertFiles()
        case .deleteSelected: chooseFile(); Task { await m.deleteSelected() }
        case .switchWorkingCopy: Task { await m.switchBranch() }
        case .createBranch: Task { await m.createBranchOrTag() }
        case .mergeChanges: merge()
        case .compareFile: if let path = m.selectedEntryID { openComparison(path) }
        case .showLog: openHistory()
        case .showProperties: Task { await m.showProperties(); QueryWindows.shared.preview(L("Properties"), text: m.output) }
        case .showAnnotate: Task { await m.annotate(); QueryWindows.shared.preview(L("Annotate"), text: m.output) }
        case .lockSelected: chooseFile(); Task { await m.lock(false) }
        case .unlockSelected: chooseFile(); Task { await m.lock(true) }
        case .showRepository: QueryWindows.shared.repository(m.selected?.url ?? "")
        case .cleanupWorkingCopy: Task { await m.cleanup() }
        default: break
        }
    }
}
