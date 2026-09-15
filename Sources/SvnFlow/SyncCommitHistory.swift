import AppKit
import SwiftUI
import SVNCore

/// Browses the author-filtered snapshot already used by the merge pipeline.
struct SyncCommitHistory: View {
    let file: SyncReport.FileItem
    let report: SyncReport
    @State private var selection: String?
    @State private var pathSelection: String?
    @State private var filter = ""
    @State private var comparing = false
    @State private var error = ""

    private var commits: [SyncReport.Commit] {
        let revisions = Set(file.revisions)
        return (report.dev ?? []).filter { revisions.contains($0.revision) }.sorted { $0.revision > $1.revision }
    }
    private var visible: [SyncReport.Commit] {
        commits.filter { item in
            filter.isEmpty || "r\(item.revision) \(report.config.author) \(item.date) \(item.message) \(item.paths.map(\.path).joined(separator: " "))".localizedCaseInsensitiveContains(filter)
        }
    }
    private var current: SyncReport.Commit? { visible.first { $0.id == selection } }
    private var selectedPath: SyncReport.Commit.Path? { current?.paths.first { $0.path == pathSelection } }
    private var rows: [WorkspaceTableRow] {
        visible.map { item in
            .init(id: item.id, values: ["r\(item.revision)", report.config.author, dateLabel(item.date), item.message.components(separatedBy: .newlines).joined(separator: " ")], symbol: "clock.arrow.circlepath")
        }
    }
    private var pathRows: [WorkspaceTableRow] {
        (current?.paths ?? []).map { path in
            .init(id: path.path, values: [path.path, path.actionLabel, path.copyFrom ?? ""], symbol: path.kind == "dir" ? "folder" : SyncMergeType.classify(path.path).symbol, tint: path.action == "D" ? WorkbenchTheme.dangerNS : path.action == "A" ? WorkbenchTheme.successNS : WorkbenchTheme.mutedNS)
        }
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(WorkbenchTheme.muted)
                TextField("搜索版本、作者、说明或路径", text: $filter).textFieldStyle(.plain)
                if !filter.isEmpty { Button { filter = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).help("清除搜索") }
                Text("\(visible.count) / \(commits.count) 次提交").foregroundStyle(WorkbenchTheme.muted)
            }.padding(9).background(WorkbenchTheme.raised)
            Divider()
            if commits.isEmpty {
                ContentUnavailableView("暂无逐条提交记录", systemImage: "clock", description: Text("此报告未保存详细日志，请通过“修改范围”重新加载。"))
            } else {
                VSplitView {
                    WorkspaceTable(columns: [.init(title: "版本", width: 90), .init(title: "作者", width: 100), .init(title: "日期", width: 155), .init(title: "提交说明", width: 420)], rows: rows, selection: $selection)
                        .overlay { if visible.isEmpty { Text("没有匹配的提交记录").foregroundStyle(WorkbenchTheme.muted).allowsHitTesting(false) } }
                        .frame(minHeight: 100, idealHeight: 220)
                    VStack(alignment: .leading, spacing: 0) {
                        sectionHeader(current.map { "r\($0.revision) · \(report.config.author) · \(dateLabel($0.date))" } ?? "完整提交说明")
                        ScrollView {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(current.map { $0.message.isEmpty ? "（无提交说明）" : $0.message } ?? "选择上方记录，查看完整提交说明")
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                if let outside = current?.outsideScope, !outside.isEmpty {
                                    Text("另有 \(outside.count) 个 报告范围外路径：\n" + outside.joined(separator: "\n")).foregroundStyle(WorkbenchTheme.muted)
                                }
                            }.textSelection(.enabled).padding(10)
                        }
                    }.frame(minHeight: 80, idealHeight: 130)
                    VStack(spacing: 0) {
                        HStack {
                            Text("本次提交的变更路径 · 报告范围（\(current?.paths.count ?? 0)）").fontWeight(.medium)
                            Spacer()
                            Button("对比所选文件") { Task { await compare() } }.disabled(comparing || selectedPath == nil || selectedPath?.kind == "dir")
                        }.padding(8).background(WorkbenchTheme.raised)
                        WorkspaceTable(columns: [.init(title: "路径", width: 450), .init(title: "操作", width: 75), .init(title: "复制来源", width: 240)], rows: pathRows, selection: $pathSelection, scrollToSelection: true, onDoubleClick: { Task { await compare() } })
                            .help("双击文件，使用现有对比窗口查看该次提交的修改")
                    }.frame(minHeight: 110, idealHeight: 180)
                }
            }
            Divider()
            HStack {
                if comparing { ProgressView().controlSize(.small) }
                Text(error.isEmpty ? "按版本从新到旧 · 选中记录查看说明，双击路径对比" : error)
                    .foregroundStyle(error.isEmpty ? WorkbenchTheme.muted : WorkbenchTheme.danger)
                Spacer()
                Button("复制说明") {
                    guard let message = current?.message else { return }
                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(message, forType: .string)
                }.disabled(current == nil)
            }.font(.caption).padding(.vertical, 8)
        }
        .onAppear { reconcileSelection() }
        .onChange(of: visible.map(\.id)) { _, _ in reconcileSelection() }
        .onChange(of: selection) { _, _ in selectCurrentPath(); error = "" }
    }
    private func sectionHeader(_ title: String) -> some View {
        Text(title).font(.system(size: 12, weight: .medium)).frame(maxWidth: .infinity, alignment: .leading)
            .padding(8).background(WorkbenchTheme.raised)
    }
    private func reconcileSelection() {
        if !visible.contains(where: { $0.id == selection }) { selection = visible.first?.id }
        selectCurrentPath()
    }
    private func selectCurrentPath() {
        pathSelection = current?.paths.first(where: { $0.path == file.path })?.path ?? current?.paths.first?.path
    }
    private func dateLabel(_ value: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = parser.date(from: value) ?? ISO8601DateFormatter().date(from: value) else { return value }
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd HH:mm"
        return formatter.string(from: date)
    }
    @MainActor private func compare() async {
        guard !comparing, let commit = current, let path = selectedPath, path.kind != "dir" else { return }
        comparing = true; error = ""; defer { comparing = false }
        do {
            let query = RepositoryQuery()
            let revision = String(commit.revision)
            // Fetch exact SVN metadata so deletion and copy history retain the existing comparison semantics.
            let records = try await query.revisionDetails(report.config.dev, revision: revision)
            let root = try await query.info(report.config.dev, item: "repos-root-url", revision: revision)
            guard let base = URL(string: report.config.dev), let rootURL = URL(string: root) else { throw URLError(.badURL) }
            let url = base.appendingPathComponent(path.path)
            guard let change = records.first(where: { $0.revision == revision })?.paths.first(where: {
                rootURL.appendingPathComponent(String($0.path.dropFirst())).absoluteString == url.absoluteString
            }) else { throw NSError(domain: "SyncHistory", code: 1, userInfo: [NSLocalizedDescriptionKey: "未找到此文件的修订信息，请重新加载报告后重试。"]) }
            QueryWindows.shared.compare(url.absoluteString, revision: revision, change: change)
        } catch { self.error = error.localizedDescription }
    }
}
