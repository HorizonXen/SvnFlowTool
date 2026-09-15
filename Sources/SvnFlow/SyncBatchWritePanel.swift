import SwiftUI

/// One confirmed batch stays visible even when file-system notifications invalidate
/// the working-copy list. The model owns execution; dismissing this sheet cannot cancel it.
struct SyncBatchWritePanel: View {
    @ObservedObject var model: BranchSyncModel
    @ObservedObject var progress: SyncProgressModel
    let close: () -> Void
    let inspectFailure: () -> Void

    var body: some View {
        if let batch = model.writeBatch {
            VStack(spacing: 0) {
                HStack {
                    WorkbenchHeading(eyebrow: "", title: batch.title,
                                     subtitle: "确认范围 → 连续写入 → 查看结果", symbol: batch.active ? "arrow.triangle.2.circlepath" : "checklist")
                    Spacer()
                    WorkbenchCloseButton(hint: batch.active ? "关闭面板后继续写入，可从主窗口查看进度" : "关闭面板，保留本批结果", action: close)
                }.padding(24)
                Divider()
                VStack(alignment: .leading, spacing: 16) {
                    Text("目标：\(batch.target)").font(.caption).foregroundStyle(WorkbenchTheme.muted)
                        .lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                    HStack(alignment: .firstTextBaseline) {
                        Text("已完成 \(batch.completed) / \(batch.paths.count)")
                            .font(.system(size: 20, weight: .semibold)).monospacedDigit()
                        Spacer()
                        if let path = batch.currentPath, let index = batch.paths.firstIndex(of: path) {
                            Text("当前第 \(index + 1) 个文件").foregroundStyle(WorkbenchTheme.muted)
                        }
                    }
                    if batch.active {
                        ProgressView(value: Double(batch.completed), total: Double(max(1, batch.paths.count)))
                            .accessibilityLabel("批量文件完成进度")
                            .accessibilityValue("\(batch.completed) / \(batch.paths.count) 个文件")
                    }
                    HStack {
                        Text("失败 \(batch.failures) · 未开始 \(batch.unstarted)")
                        Spacer()
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            let seconds = max(0, Int((batch.ended ?? context.date).timeIntervalSince(batch.started)))
                            Text(String(format: "耗时 %d:%02d", seconds / 60, seconds % 60)).monospacedDigit()
                        }
                    }.font(.caption).foregroundStyle(WorkbenchTheme.muted)
                    if batch.active {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(batch.state == .stopping ? "停止请求已收到；完成当前文件后不再启动下一项。" : (progress.activity?.phase ?? progress.phase))
                                .font(.system(size: 13, weight: .medium))
                            if let path = batch.currentPath {
                                Text(path).font(.caption).textSelection(.enabled)
                                    .foregroundStyle(WorkbenchTheme.muted).fixedSize(horizontal: false, vertical: true)
                            }
                            Text("按文件数计数，不代表时间比例。每个文件都需完成写入前核验。")
                                .font(.caption).foregroundStyle(WorkbenchTheme.muted)
                        }
                    } else if let failure = batch.failure {
                        VStack(alignment: .leading, spacing: 8) {
                            Label(batch.state == .interrupted ? "当前文件可能部分写入，请检查现场及备份。" : "已停止后续写入，请先处理失败原因。", systemImage: "exclamationmark.triangle")
                                .foregroundStyle(WorkbenchTheme.danger)
                            Text(failure.split(separator: "\n").last.map(String.init) ?? failure)
                                .font(.caption).lineLimit(3).textSelection(.enabled)
                            HStack {
                                Button("查看失败文件") { inspectFailure() }
                                if let log = progress.logURL {
                                    Button("查看日志") { NSWorkspace.shared.open(log) }
                                }
                            }.buttonStyle(SyncOrbitButton())
                        }
                    } else {
                        Text(batch.state == .completed ? "全部所选文件已确认到本地 Release，尚未提交 SVN。" : "已安全停止，已完成的结果保留；未开始文件需重新确认。")
                            .font(.system(size: 13)).foregroundStyle(WorkbenchTheme.muted)
                    }
                    Divider()
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 0) {
                            ForEach(batch.paths, id: \.self) { path in
                                batchRow(path, batch: batch)
                            }
                        }
                    }
                }.padding(24).frame(maxHeight: .infinity)
                Divider()
                HStack {
                    Text(batch.active ? "关闭面板后继续写入，可从主窗口查看进度。" : "仅写入本地 Release，不会自动提交 SVN。")
                        .font(.caption).foregroundStyle(WorkbenchTheme.muted)
                    Spacer()
                    if batch.active {
                        Button(batch.state == .stopping ? "正在等待当前文件完成" : "完成当前文件后停止") {
                            model.requestStopWriting()
                        }.buttonStyle(SyncOrbitButton()).disabled(batch.state == .stopping)
                    } else {
                        Button("返回选择文件") { model.returnToWriteSelection() }
                            .buttonStyle(SyncOrbitButton(prominent: true)).disabled(!model.canChangeBatch)
                    }
                }.padding(18)
            }.frame(width: 840, height: 640).workbenchStyle().workbenchSecondarySurface()
        }
    }

    private func batchRow(_ path: String, batch: SyncWriteBatch) -> some View {
        let outcome = batch.outcomes[path]
        let active = batch.currentPath == path && batch.active
        let failed = outcome == .failed
        let label = active ? "处理中" : (outcome?.rawValue ?? "未开始")
        let symbol = active ? "clock" : failed ? "exclamationmark.triangle" : outcome == nil ? "minus" : "checkmark.circle"
        return HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).frame(width: 16)
                .foregroundStyle(failed ? WorkbenchTheme.danger : outcome == nil ? WorkbenchTheme.muted : WorkbenchTheme.accent)
            Text(path).font(.caption).textSelection(.enabled).lineLimit(2).truncationMode(.middle)
            Spacer(minLength: 8)
            Text(label).font(.caption).foregroundStyle(failed ? WorkbenchTheme.danger : WorkbenchTheme.muted)
        }.padding(.vertical, 8).accessibilityElement(children: .combine)
    }
}
