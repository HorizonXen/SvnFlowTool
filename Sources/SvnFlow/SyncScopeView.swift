import SwiftUI
import SVNCore

struct SyncScopeView: View {
    @ObservedObject var model: BranchSyncModel
    @ObservedObject private var draft: SyncScopeDraft
    let close: () -> Void
    var applied: (() -> Void)?
    @State private var showDirectories = false
    @State private var retry = 0
    @State private var customSelection: Set<String> = []
    @State private var customPath = ""
    @State private var customError: String?

    init(model: BranchSyncModel, applied: (() -> Void)? = nil, close: @escaping () -> Void) {
        self.model = model; self.applied = applied; self.close = close
        draft = model.scopeDraft
        model.scopeDraft.setup(author: model.author, days: model.days)
    }
    private var canStart: Bool {
        model.canChangeBatch && draft.canRead && draft.previewMatches && !draft.checking && draft.selectedCount > 0
            && (draft.allDirectories || !draft.directories.isEmpty)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("新建合入轮次").font(.headline)
                Spacer()
                WorkbenchCloseButton(action: close)
            }
            Text("\(model.directionTitle) · 先确定范围，再核验文件").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    authorFields
                    directoryFields
                    commitFields
                    previewStatus
                    selectionCheckStatus
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 490)
            if !model.canChangeBatch {
                Text("请先完成当前操作，并确认或跳过待确认副本。").font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Button("取消", action: close).keyboardShortcut(.cancelAction)
                Spacer()
                if draft.checking {
                    Button("取消核验") { draft.invalidateCheck() }
                } else if draft.reading {
                    Button("取消读取") { draft.cancelRead() }
                } else if draft.previewMatches {
                    Button("重新读取") { draft.readPreview() }.disabled(!draft.canRead || !model.canChangeBatch)
                    if draft.checkResult != nil {
                        Button("重新核验") { draft.checkSelection() }.disabled(!canStart)
                        if draft.remainingCount > 0 {
                            Button("继续处理 \(draft.remainingCount) 个文件", action: start)
                                .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(!canStart)
                        }
                    } else {
                        Button("核验所选 \(draft.selectedCount) 个文件") { draft.checkSelection() }
                            .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(!canStart)
                    }
                } else {
                    Button(draft.failure == nil ? "读取提交记录" : "重新读取") { draft.readPreview() }
                        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                        .disabled(!draft.canRead || !model.canChangeBatch || (!draft.allDirectories && draft.directories.isEmpty))
                }
            }
        }.padding(24).frame(width: 760).workbenchSecondarySurface()
            .onExitCommand(perform: close)
            .onDisappear { draft.cancelRead() }
            .task(id: "\(draft.days ?? 0)|\(retry)") { await draft.readAuthors() }
            .onChange(of: draft.author) { draft.cancelRead(); draft.selectedRevisions = [] }
            .onChange(of: draft.days) { draft.cancelRead(); draft.selectedRevisions = [] }
    }
    @ViewBuilder private var selectionCheckStatus: some View {
        if draft.checking {
            HStack { ProgressView().controlSize(.small); Text("正在核验所选改动是否已合入 \(model.targetName)…") }.font(.callout)
        } else if let failure = draft.checkFailure {
            Text("核验失败：" + failure).font(.callout).foregroundStyle(.red).textSelection(.enabled)
        } else if let result = draft.checkResult {
            VStack(alignment: .leading, spacing: 8) {
                Text("已完全合入 \(draft.mergedPaths.count) 个 · 仍需处理 \(draft.remainingCount) 个").font(.callout.weight(.medium))
                Text(draft.remainingCount == 0 ? "所选改动已全部合入，无需进入合并界面。" : "已完全合入的文件不会进入合并确认；继续时会复核当前 \(model.targetName)。")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(draft.selectedFiles) { file in
                    VStack(alignment: .leading, spacing: 3) {
                        Label(draft.mergedPaths.contains(file.path) ? "已完全合入" : result.errors[file.path] != nil ? "无法确认" : "仍需处理",
                              systemImage: draft.mergedPaths.contains(file.path) ? "checkmark.circle" : "exclamationmark.circle")
                        Text(file.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        if let issue = result.errors[file.path] ?? result.localIssues?[file.path] {
                            Text(issue).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }
                Text("核验依据：\(model.targetName) r\(result.snapshot) · 当前勾选提交与目录").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    private var authorFields: some View {
        HStack(alignment: .top, spacing: 24) {
            VStack(alignment: .leading, spacing: 8) {
                Text("时间范围").font(.subheadline)
                Picker("时间范围", selection: $draft.dayOption) {
                    ForEach(SyncScopeDraft.presets, id: \.self) { Text("最近 \($0) 天").tag($0) }
                    Text("自定义天数…").tag(0)
                }.labelsHidden().accessibilityLabel("时间范围")
                if draft.dayOption == 0 {
                    TextField("1—365 天", text: $draft.customDays).textFieldStyle(.roundedBorder)
                    if draft.days == nil { Text("请输入 1—365 之间的整数。").font(.caption).foregroundStyle(.red) }
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("提交作者").font(.subheadline)
                    Spacer()
                    Button("重新读取") { draft.loadedDays = nil; retry += 1 }.disabled(draft.loadingAuthors || draft.days == nil)
                }
                if draft.loadingAuthors {
                    HStack { ProgressView().controlSize(.small); Text("正在读取作者…").font(.caption) }
                } else if let failure = draft.authorFailure {
                    Text("读取作者失败：" + failure).font(.caption).foregroundStyle(.red).textSelection(.enabled)
                } else {
                    TextField("搜索作者（支持部分名称）", text: $draft.authorSearch).textFieldStyle(.roundedBorder)
                    Picker("作者", selection: $draft.author) {
                        Text("请选择作者").tag("")
                        if !draft.author.isEmpty { Text(draft.author).tag(draft.author) }
                        ForEach(AuthorSearch.filter(draft.authors, query: draft.authorSearch).filter { $0 != draft.author }, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden().accessibilityLabel("提交作者")
                    if draft.authors.isEmpty { Text("该时间范围内没有作者，请扩大范围。").font(.caption).foregroundStyle(.secondary) }
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }.disabled(!model.canChangeBatch)
    }
    @ViewBuilder private var commitFields: some View {
        if draft.previewMatches && !draft.reading {
            VStack(alignment: .leading, spacing: 10) {
                Text("SVN 提交记录").font(.subheadline.weight(.semibold))
                HStack {
                    TextField("搜索提交备注或单号，例如：怪物属性修改", text: $draft.commitSearch)
                        .textFieldStyle(.roundedBorder)
                    Button("全选搜索结果") { draft.selectSearchResults() }.disabled(draft.visibleCommits.isEmpty)
                    Button("清空选择") { draft.selectedRevisions = [] }.disabled(draft.selectedRevisions.isEmpty)
                }
                Text("修改搜索条件将清空勾选；全选仅作用于当前搜索结果。")
                    .font(.caption).foregroundStyle(.secondary)
                if draft.visibleCommits.isEmpty {
                    Text(draft.commits.isEmpty ? "该作者在此时间范围内没有提交记录。" : "没有匹配记录，请调整备注或单号。")
                        .foregroundStyle(.secondary).padding(.vertical, 8)
                } else {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(draft.visibleCommits) { commit in
                            VStack(alignment: .leading, spacing: 5) {
                                Toggle(isOn: Binding(get: { draft.selectedRevisions.contains(commit.revision) }, set: { checked in
                                    if checked { draft.selectedRevisions.insert(commit.revision) }
                                    else { draft.selectedRevisions.remove(commit.revision) }
                                })) {
                                    HStack {
                                        Text("r\(commit.revision)").monospacedDigit().fontWeight(.medium)
                                        Text(draft.author).foregroundStyle(.secondary)
                                        Text(commit.date.replacingOccurrences(of: "T", with: " ").replacingOccurrences(of: "Z", with: " UTC"))
                                            .font(.caption).foregroundStyle(.secondary)
                                        Spacer()
                                        Text("\(commit.paths.count) 个路径").font(.caption).foregroundStyle(.secondary)
                                    }
                                }.toggleStyle(.checkbox).accessibilityLabel("选择提交 r\(commit.revision)：\(commit.message)")
                                Text(commit.message.isEmpty ? "（无提交备注）" : commit.message)
                                    .font(.callout).textSelection(.enabled).fixedSize(horizontal: false, vertical: true).padding(.leading, 20)
                                Divider().padding(.top, 5)
                            }.padding(.vertical, 6)
                        }
                    }
                }
                Text("已选 \(draft.effectiveRevisions.count) / \(draft.visibleCommits.count) 条提交 · \(draft.selectedCount) 个文件")
                    .font(.callout.weight(.medium))
                Text("仅重放勾选提交的改动；删除继续核验后续历史。")
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(!model.canChangeBatch)
        }
    }
    private var directoryFields: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("合并目录").font(.subheadline.weight(.semibold))
                Spacer()
                if draft.inherited { Text("沿用上次范围 · 可修改").font(.caption).foregroundStyle(.secondary) }
            }
            HStack {
                directoryButton("Excel 配置目录", path: SyncScopeDraft.excel)
                directoryButton("Lua 脚本目录", path: SyncScopeDraft.lua)
                directoryButton("全部目录", path: nil)
                Button("自定义目录…") { customSelection = draft.allDirectories ? [] : draft.directories; customPath = ""; customError = nil; showDirectories = true }
                    .popover(isPresented: $showDirectories) { customDirectories }
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("已选目录（包含子目录）").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("清空") { draft.allDirectories = false; draft.directories = [] }
                }
                Text(draft.allDirectories ? "全部目录" : draft.directories.isEmpty ? "尚未选择目录" : draft.normalizedDirectories.joined(separator: "\n"))
                    .font(.callout).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                Text("按目录范围合并，包含其中的配套文件。").font(.caption).foregroundStyle(.secondary)
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 6))
        }.disabled(!model.canChangeBatch || draft.reading)
    }
    private func directoryButton(_ title: String, path: String?) -> some View {
        let selected = path.map { !draft.allDirectories && draft.normalizedDirectories == [$0] } ?? draft.allDirectories
        return Button { draft.choose(path) } label: {
            HStack(spacing: 4) { if selected { Image(systemName: "checkmark") }; Text(title) }
        }.tint(selected ? .accentColor : .secondary)
    }
    @ViewBuilder private var previewStatus: some View {
        if draft.reading {
            HStack { ProgressView().controlSize(.small); Text("正在读取提交清单…") }
            Text("文件总数尚未确定；此时不下载或解析 Excel / Lua 内容。").font(.caption).foregroundStyle(.secondary)
        } else if let failure = draft.failure {
            Text("文件清单读取失败").font(.subheadline.weight(.semibold)).foregroundStyle(.red)
            Text(failure).font(.caption).textSelection(.enabled)
            Text("检查 SVN 连接后重试，已选范围会保留。").font(.caption).foregroundStyle(.secondary)
        } else if !draft.allDirectories && draft.directories.isEmpty {
            Text("请选择至少一个目录。").font(.callout)
        } else if draft.previewMatches {
            Text(draft.effectiveRevisions.isEmpty ? "请勾选需要合入的 SVN 提交记录" : draft.selectedCount == 0 ? "所选范围内没有可核验文件" : "清单已就绪 · \(draft.selectedCount) 个文件待核验")
                .font(.subheadline.weight(.semibold))
            Text(draft.selectedCount == 0 ? "可调整目录、作者或时间后重试。" : "\(draft.total - draft.selectedCount) 个文件未纳入本轮，将跳过内容读取与核验。")
                .font(.caption).foregroundStyle(.secondary)
            if draft.selectedPMData > 0 { Text("另含 \(draft.selectedPMData) 个 pmdata 文件，继续使用配置导出流程，不直接合入。").font(.caption).foregroundStyle(.secondary) }
            Text("数量来自提交清单；是否仍有差异，将在核验后确定。").font(.caption).foregroundStyle(.secondary)
            if let config = draft.preview?.config {
                Text("清单时间：\(config.start) → \(config.end)").font(.caption2).foregroundStyle(.secondary)
            }
        } else {
            Text("先读取提交清单，查看本轮需要核验的文件数。").font(.callout)
            Text("只读取提交记录；更改作者或时间后需重新读取。").font(.caption).foregroundStyle(.secondary)
        }
    }
    private var customDirectories: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("选择合并目录").font(.headline); Spacer(); Button("取消") { showDirectories = false }; Button("使用所选目录") { draft.allDirectories = false; draft.directories = customSelection; showDirectories = false }.disabled(customSelection.isEmpty) }
            Text("多选包含子目录；重叠路径只计算一次。列表来自提交清单，也可手动添加相对目录。").font(.caption).foregroundStyle(.secondary)
            TextField("搜索目录…", text: $draft.directorySearch).textFieldStyle(.roundedBorder)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Set(draft.availableDirectories).union(customSelection).sorted(), id: \.self) { path in
                        Toggle(path, isOn: Binding(get: { customSelection.contains(path) }, set: { checked in
                            if checked { customSelection.insert(path) } else { customSelection.remove(path) }
                        })).toggleStyle(.checkbox).font(.callout).textSelection(.enabled)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(height: 240)
            HStack { TextField("添加分支内相对目录…", text: $customPath).textFieldStyle(.roundedBorder); Button("添加") { addCustomDirectory() } }
            if let error = customError { Text(error).font(.caption).foregroundStyle(.red) }
            Text("已勾选 \(customSelection.count) 个目录；父子目录自动去重").font(.caption)
        }.padding(20).frame(width: 590)
    }
    private func addCustomDirectory() {
        let path = customPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty, !path.contains("\\"), !path.split(separator: "/", omittingEmptySubsequences: false).contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else {
            customError = "请输入分支内相对目录，不包含 .. 或空路径段。"; return
        }
        customSelection.insert(path); customPath = ""; customError = nil
    }
    private func start() {
        guard canStart, draft.checkResult != nil, draft.remainingCount > 0, let days = draft.days, let folder = draft.previewFolder else { return }
        let revisions = draft.effectiveRevisions
        guard !revisions.isEmpty else { return }
        let author = draft.author, directories: [String]? = draft.allDirectories ? nil : draft.normalizedDirectories
        draft.remember()
        let preview = folder.appendingPathComponent("scope-preview.json")
        close()
        Task {
            let previous = model.folder
            await model.applyScope(author: author, days: days, directories: directories, preview: preview, revisions: revisions)
            if model.folder != previous { applied?() }
        }
    }
}
