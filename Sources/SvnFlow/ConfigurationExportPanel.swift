import AppKit
import SwiftUI

/// Shared by the merge workflow and the directory workspace.
struct ConfigurationExportPanel: View {
    @ObservedObject var model: BranchSyncModel
    var workspaceCount: Int? = nil
    let close: () -> Void

    private var completedExportCount: Int? {
        guard !model.busy, let result = model.exportCandidate,
              result.status == "published", let workbooks = result.publishedWorkbooks,
              !workbooks.isEmpty, Set(workbooks.keys) == model.selectedExports else { return nil }
        return workbooks.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("配置导出").font(.system(size: 20, weight: .semibold))
                Spacer()
                WorkbenchCloseButton(hint: "关闭面板，保留候选与任务") { close() }
            }
            if let count = workspaceCount {
                Text("从目录选入 \(count) 个 Excel · " + model.workspaceExportLabel).font(.caption).foregroundStyle(SyncOrbit.muted)
                Text("目标：" + model.workspaceExportTarget).font(.caption).foregroundStyle(SyncOrbit.muted)
                    .textSelection(.enabled).lineLimit(2).help(model.workspaceExportTarget)
            }
            Divider()
            if let count = completedExportCount {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 24)).foregroundStyle(SyncOrbit.green)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("导出成功").font(.headline)
                        Text("所选 \(count) 个 Excel 已全部导出，Lua、pmdata 已写入并核验。尚未提交 SVN。")
                            .font(.caption).foregroundStyle(SyncOrbit.muted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(WorkbenchTheme.successSurface, in: RoundedRectangle(cornerRadius: 8))
                .accessibilityElement(children: .combine)
            }
            ScrollView {
            VStack(alignment: .leading, spacing: 16) {
            Text(model.workspaceExport ? "按当前本地 Excel 导出，无需确认合入记录；生成时重新核验。" : "按已确认合入的 Excel 生成候选并核验。").foregroundStyle(SyncOrbit.muted)
            Text("按现有转表规则自动生成 Lua、pmdata 到对应目录，无需再次确认。")
                .font(.caption).foregroundStyle(SyncOrbit.muted)
            Divider()
            HStack {
                Text("导出配置 \(model.pendingExports.count) 项").font(.headline)
                Spacer()
                Button("复制 xtools 导出清单") {
                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(model.exportChecklist, forType: .string)
                }.disabled(model.pendingExports.isEmpty)
            }
            HStack {
                Button("导出所选 \(model.selectedExports.count) 项") { Task { await model.exportXTools() } }
                    .disabled(!model.canChangeBatch || model.selectedExports.isEmpty || !model.selectedExports.isSubset(of: model.exportablePaths))
                if let receipt = model.exportCandidateReceipt {
                    Button("查看核验记录") { NSWorkspace.shared.open(URL(fileURLWithPath: receipt)) }
                }
            }.buttonStyle(SyncOrbitButton())
            Text("生成并核验后自动写入对应目录；核验失败会停止并说明原因。不会提交 SVN。")
                .font(.caption).foregroundStyle(SyncOrbit.muted)
            if let candidate = model.exportCandidate {
                HStack {
                    Text((candidate.status == "published" ? "导出完成 · " : "") + "已核验 \(candidate.fields) 个字段")
                    if candidate.status != "published" {
                        Button("继续导出") { Task { await model.publishXTools(resume: true) } }
                    }
                }.disabled(!model.canChangeBatch || candidate.status == "published")
                ScrollView {
                    VStack(alignment: .leading) {
                        ForEach(candidate.outputs, id: \.target) { item in
                            if candidate.status == "published" {
                                Text((item.before == item.after ? "无变化 · " : "已生成 · ") + (item.target as NSString).lastPathComponent)
                            } else {
                            Button((item.before == item.after ? "无变化 · " : "查看差异 · ") + (item.target as NSString).lastPathComponent) { model.compareExport(item) }
                                .disabled(!model.canChangeBatch)
                            }
                        }
                    }
                }.frame(maxHeight: 90)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(model.displayedExportPaths, id: \.self) { path in
                        Toggle(path + (model.workspaceExport ? "（当前本地文件）" : model.exportRecords[path]?.publicationHash != nil ? "（上次发布已核验）" : "（待正式发布）"), isOn: Binding(get: { model.selectedExports.contains(path) }, set: { if $0 { model.selectedExports.insert(path) } else { model.selectedExports.remove(path) } }))
                            .toggleStyle(.checkbox).disabled(!model.canChangeBatch || !model.exportablePaths.contains(path))
                    }
                    if model.displayedExportPaths.isEmpty { Text(model.workspaceExport ? "请返回目录选择 Excel。" : "Excel 确认写入后会自动加入这里。").foregroundStyle(SyncOrbit.muted) }
                }
            }.frame(minHeight: 160)
            }
            }
            Divider()
            if model.busy { ProgressView().progressViewStyle(.linear) }
            Text(model.activity).font(.caption).foregroundStyle(SyncOrbit.muted)
        }.padding(24).frame(width: 780, height: 650).workbenchStyle().workbenchSecondarySurface()
    }
}

struct WorkspaceConfigurationExport: View {
    @ObservedObject var model: BranchSyncModel
    let close: () -> Void

    init(model: BranchSyncModel, close: @escaping () -> Void) {
        self.model = model
        self.close = close
    }

    var body: some View {
        ConfigurationExportPanel(model: model,
                                 workspaceCount: model.selectedExports.count, close: close)
    }
}
