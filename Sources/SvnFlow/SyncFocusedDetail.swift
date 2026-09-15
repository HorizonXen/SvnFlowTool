import SwiftUI

/// File-level presentation only. Generation, review and writes stay in BranchSyncModel.
struct SyncFocusedDetail: View {
    @ObservedObject var model: BranchSyncModel
    @ObservedObject var progress: SyncProgressModel
    let close: () -> Void
    let export: () -> Void
    @State private var history = false
    @State private var fileInfo = false
    @State private var expandedLog = false
    private let blue = WorkbenchTheme.accent
    private let ink = WorkbenchTheme.text
    private let muted = WorkbenchTheme.muted
    private var path: String? { model.selection }
    private var ownsProgress: Bool { path != nil && model.outputPath == path }
    private var busy: Bool { model.busy && (ownsProgress || model.outputPath == nil) }
    private var writing: Bool { busy && ["accept", "accept-low"].contains(model.action) }
    private var blocked: Bool { !busy && !localSame && !verifiedSame && path.map { model.blocked.contains($0) && !model.done.contains($0) && !model.skipped.contains($0) } == true }
    private var done: Bool { path.map { model.done.contains($0) } == true }
    private var skipped: Bool { path.map { model.skipped.contains($0) } == true }
    private var ready: Bool { path.map(model.isReady) == true }
    private var needsExport: Bool { path.map { model.workflowStatus($0) == "待导出" } == true }
    private var needsVerification: Bool {
        guard let path, !skipped, !needsExport, model.current?.mergeType != .pmdata else { return false }
        return model.repositoryStates[path] == nil || model.repositoryStates[path] == "error"
    }
    private var verificationFailed: Bool { path.map(model.remainingFailed) == true }
    private var localIssue: String? { path.flatMap { model.localRemainingIssues[$0] } }
    private var localSame: Bool { path.map(model.localContainsChanges) == true && !needsExport }
    private var verifiedSame: Bool { path.map { model.repositoryStates[$0] == "same" } == true && localIssue == nil && !needsExport }
    private var step: Int {
        if writing || (!busy && (done || skipped || localSame || verifiedSame)) { return 2 }
        if busy { return 0 }
        return ready ? 1 : 0
    }
    private var status: String {
        if busy { return progress.cancelling ? "正在停止" : writing ? "正在写入" : ["catalog", "authors", "remaining-diff"].contains(model.action) ? "正在检索" : "正在生成" }
        if model.current == nil { return "尚未选择" }
        if localSame && !verifiedSame { return "本地一致 · 已登记" }
        if needsVerification { return verificationFailed ? "无法确认" : "待核验" }
        if verifiedSame { return "仓库一致 · 已登记" }
        if localIssue != nil && !needsExport { return "需要处理" }
        if blocked { return "需要处理" }
        if needsExport { return "等待导出" }
        if done { return "处理完成" }
        if skipped { return "已暂不合入" }
        return ready ? "等待你确认" : "等待开始"
    }
    private var title: String {
        if busy, !progress.cancelling, model.action == "remaining-diff", let scope = progress.verificationScope {
            return scope == "当前文件核验" ? "正在核验当前文件" : "正在核验所选文件"
        }
        if busy { return progress.cancelling ? "正在安全停止，保留已生成副本" : writing ? "正在写入 \(model.targetName) 本地文件" : ["catalog", "authors", "remaining-diff"].contains(model.action) ? "正在检索并核对合入范围" : "正在生成待合入副本" }
        if model.current == nil { return "请选择需要合入的文件" }
        if localSame && !verifiedSame { return "\(model.targetName) 本地已包含所需改动" }
        if needsVerification { return verificationFailed ? "当前 \(model.targetName) 核验未完成" : "先核验当前 \(model.targetName)，再生成副本" }
        if verifiedSame { return "当前 \(model.targetName) 已包含所需改动" }
        if localIssue != nil && !needsExport { return "请先核对 \(model.targetName) 本地状态" }
        if blocked {
            if let path, model.isTemporarilyBlocked(path) { return "其他合入任务正在运行" }
            if let path, model.failureReason(path).contains("缺少配置 ID") { return "无法生成副本：缺少配置 ID" }
            return "合入未完成，请查看原因"
        }
        if needsExport { return "需要通过 xtools 导出" }
        if done { return "已合入 \(model.targetName) 本地文件" }
        if skipped { return "本次暂不合入，副本已保留" }
        return ready ? "副本已准备好，查看差异后继续" : "准备生成待合入副本"
    }
    private var description: String {
        if busy { return progress.activity?.phase ?? progress.phase }
        if model.current == nil { return "返回列表选择文件后再继续。" }
        if localSame && !verifiedSame { return "本次提交范围已登记并从列表移除，无需重复对比；尚未提交 SVN。" }
        if needsVerification {
            let reason = verificationFailed ? (path.map(model.shortReason) ?? "核验未完成，请重试。") : "上次核验尚未覆盖当前文件。"
            return reason + " 只核验上方路径对应的文件，其他文件的已有结果与副本保留。"
        }
        if verifiedSame { return "本次提交范围已登记并从列表移除，无需重复对比。" }
        if let localIssue, !needsExport { return localIssue }
        if blocked, let path {
            let reason = model.shortReason(path)
            return reason.count > 230 ? String(reason.prefix(230)) + "…（完整原因见下方日志）" : reason
        }
        if needsExport { return "查看原有导出清单，按文件类型继续处理。" }
        if done { return "文件处理已完成，原文件备份已保留。仅写入本地，尚未提交 SVN。" }
        if skipped { return "当前文件不写入 \(model.targetName)，可在完整报告中查看处理记录。" }
        if ready, let path {
            return model.entries[path]?.lowRisk == true ? "请核对待合入内容；确认操作仍在现有对比窗口中完成。" : (model.entries[path]?.risk?.reasons.joined(separator: "；") ?? "需要逐项核对差异，确认后才会写入本地。")
        }
        return "提取所选作者的修改并生成副本，确认前不会写入 \(model.targetName)。"
    }
    private var result: String {
        if let path, let value = model.fileOutputs[path] { return String(value.prefix(24000)) }
        if ownsProgress || model.outputPath == nil { return String(model.output.prefix(24000)) }
        return description
    }
    private var panelColor: Color { blocked ? WorkbenchTheme.warningSurface : (done || localSame || verifiedSame) ? WorkbenchTheme.successSurface : WorkbenchTheme.infoSurface }
    private var stateColor: Color { blocked ? WorkbenchTheme.danger : (done || localSame || verifiedSame) ? WorkbenchTheme.success : blue }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("文件合入").font(.system(size: 12, weight: .medium)).foregroundStyle(muted)
                Spacer()
                WorkbenchCloseButton(title: "返回文件列表", hint: "关闭详情，任务继续运行", action: close)
            }.padding(.horizontal, 24).padding(.vertical, 13).background(WorkbenchTheme.panel)
            Divider()
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 14) {
                    Image(systemName: model.current?.mergeType.symbol ?? "doc")
                        .font(.system(size: 22)).foregroundStyle(blue).frame(width: 44, height: 48)
                        .background(blue.opacity(0.07), in: RoundedRectangle(cornerRadius: 9))
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.current?.name ?? "尚未选择文件").font(.system(size: 23, weight: .semibold)).lineLimit(2).textSelection(.enabled)
                        Text(model.current?.path ?? "请选择需要合入的文件").font(.system(size: 11)).foregroundStyle(muted).lineLimit(1).truncationMode(.middle).textSelection(.enabled)
                    }
                    Spacer(minLength: 0)
                    Button { fileInfo.toggle() } label: { Image(systemName: "info.circle") }.buttonStyle(.plain).help("文件信息")
                        .popover(isPresented: $fileInfo) {
                            VStack(alignment: .leading, spacing: 12) {
                                HStack { Text("文件信息").font(.headline); Spacer(); WorkbenchCloseButton { fileInfo = false } }
                                Text(model.current?.path ?? "未选择文件").textSelection(.enabled)
                                Text("\(model.targetName)：\(model.report?.config.target ?? "未加载")").textSelection(.enabled)
                                Text("生成方式：\(model.current?.mergeType.function ?? "按文件类型处理")")
                            }.font(.system(size: 12)).padding(22).frame(width: 450).foregroundStyle(ink).background(WorkbenchTheme.canvas)
                        }
                }
                HStack(spacing: 10) {
                    Text(model.directionTitle).foregroundStyle(blue)
                    Text("·  \(model.author)  ·  最近 \(model.days) 天  ·  \(model.current?.revisions.count ?? 0) 次提交")
                    Spacer()
                    Button(history ? "返回处理" : "提交记录") { history.toggle() }.buttonStyle(.plain).foregroundStyle(blue)
                }.font(.system(size: 11)).foregroundStyle(muted)
            }.padding(.horizontal, 32).padding(.top, 22).padding(.bottom, 16)
            if history, let file = model.current, let report = model.report {
                SyncCommitHistory(file: file, report: report).id(file.path)
                    .padding(18).background(SyncOrbit.background).environment(\.colorScheme, .light)
            } else {
                ScrollView {
                    VStack(spacing: 20) {
                        steps
                        panel
                    }.padding(.horizontal, 32).padding(.top, 8).padding(.bottom, 12)
                }
                actions.padding(.horizontal, 32).padding(.vertical, 14)
            }
            Divider()
            HStack {
                Button("完整报告 ↗") { NSWorkspace.shared.open(model.folder.appendingPathComponent("差异报告.md")) }.disabled(model.report == nil)
                Spacer()
                Text("目标 \(model.targetName) r\(model.report?.config.snapshot ?? 0)")
                Spacer()
                Menu("更多") {
                    Button("查看日志文件") { NSWorkspace.shared.open(progress.logURL.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil } ?? model.folder) }
                    Button("打开备份") { NSWorkspace.shared.open(model.backupRoot) }
                }.menuStyle(.borderlessButton).fixedSize()
            }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(muted).padding(.horizontal, 24).padding(.vertical, 14)
        }.frame(width: 880, height: 710).foregroundStyle(ink).background(WorkbenchTheme.canvas).tint(blue).environment(\.colorScheme, .light)
            .onChange(of: path) { _, _ in expandedLog = false; history = false }
    }
    private var steps: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(0..<3, id: \.self) { index in
                if index > 0 { Rectangle().fill(WorkbenchTheme.border).frame(height: 1).padding(.top, 22) }
                VStack(spacing: 9) {
                    ZStack {
                        Circle().fill(index == step ? stateColor.opacity(0.09) : Color.white)
                        Circle().strokeBorder(index == step ? stateColor.opacity(0.25) : Color.gray.opacity(0.2))
                        if index < step || (!busy && (done || localSame || verifiedSame) && index == 2) { Image(systemName: "checkmark").foregroundStyle(WorkbenchTheme.success) }
                        else { Text(index == step && blocked ? "!" : "\(index + 1)").foregroundStyle(index == step ? stateColor : muted) }
                    }.frame(width: 44, height: 44)
                    Text(["检索 SVN", "等待确认", "最终结果"][index]).font(.system(size: 12, weight: .medium)).foregroundStyle(index == step ? stateColor : muted)
                }.frame(width: 115)
            }
        }.padding(.horizontal, 15)
    }
    private var panel: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                Label(status, systemImage: "circle.fill").font(.system(size: 10, weight: .medium)).foregroundStyle(stateColor)
                Spacer()
                if (busy || ownsProgress), let start = progress.started {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let seconds = max(0, Int((progress.ended ?? context.date).timeIntervalSince(start)))
                        Text(String(format: "本批用时 %d:%02d", seconds / 60, seconds % 60)).monospacedDigit()
                    }.font(.system(size: 11)).foregroundStyle(muted)
                }
            }
            Text(title).font(.system(size: 20, weight: .semibold))
            Text(description).font(.system(size: 12)).foregroundStyle(muted).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            if busy {
                SyncFileProgressView(progress: progress, action: model.action)
                if let activity = progress.activity, activity.revisionIndex > 0, activity.revisionTotal > 0 {
                    Text("正在处理第 \(activity.revisionIndex) / \(activity.revisionTotal) 次提交 · r\(activity.revision)")
                        .font(.system(size: 11)).foregroundStyle(muted)
                }
            }
            Divider().overlay(blue.opacity(0.06))
            if (ownsProgress || busy), let events = progress.activity?.events, !events.isEmpty {
                ForEach(Array((expandedLog ? events : Array(events.suffix(2))).enumerated()), id: \.offset) { _, event in
                    HStack(alignment: .top, spacing: 12) {
                        Text(event.timeLabel).monospacedDigit().foregroundStyle(muted)
                        Text(event.message).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                    }.font(.system(size: 11))
                }
            }
            DisclosureGroup(isExpanded: $expandedLog) {
                Text(result).font(.system(size: 11)).foregroundStyle(muted).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).padding(.top, 8)
            } label: { Text(blocked ? "技术详情与完整日志" : "展开处理记录").font(.system(size: 11)).foregroundStyle(muted) }
        }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            .background(panelColor, in: RoundedRectangle(cornerRadius: 12))
            .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(stateColor.opacity(0.15)) }
            .overlay(alignment: .top) {
                GeometryReader { proxy in
                    let centers = [72.5, proxy.size.width / 2, proxy.size.width - 72.5]
                    FocusedPointer().fill(panelColor).frame(width: 18, height: 9).position(x: centers[step], y: -4)
                }.allowsHitTesting(false)
            }
    }
    private var actions: some View {
        VStack(spacing: 9) {
            HStack(spacing: 10) {
                if busy {
                    Button(status + "…") {}.buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(true)
                    if ["stage", "assess", "catalog", "remaining-diff"].contains(model.action) {
                        Button(progress.cancelling ? "正在停止…" : "安全停止") { model.cancelGeneration() }.disabled(progress.cancelling)
                    }
                } else if model.current == nil {
                    Button("返回文件列表", action: close).buttonStyle(WorkbenchButtonStyle(prominent: true))
                } else if (localSame || verifiedSame), let path {
                    Button("返回文件列表", action: close).buttonStyle(WorkbenchButtonStyle(prominent: true))
                    Button("查看本地差异") { model.compareLocal(path) }.disabled(!model.canChangeBatch)
                    Button("重新核验此文件") { Task { await model.verifyRemaining(path) } }.disabled(!model.canChangeBatch || !model.matchesScope)
                    if localSame && !verifiedSame && model.current?.mergeType == .excel {
                        Button("导出本地配置") {
                            guard let target = model.report?.config.target else { return }
                            do { try QueryWindows.shared.openConfigurationExport(workingCopy: target, selection: [URL(fileURLWithPath: target).appendingPathComponent(path).path]) }
                            catch { model.activity = error.localizedDescription; model.output = error.localizedDescription }
                        }.disabled(!model.canChangeBatch)
                    }
                } else if needsVerification, let path {
                    Button(verificationFailed ? "重新核验此文件" : "核验此文件") { Task { await model.verifyRemaining(path) } }
                        .buttonStyle(WorkbenchButtonStyle(prominent: true))
                        .disabled(!model.canChangeBatch || !model.matchesScope)
                } else if verifiedSame {
                    Button("返回文件列表", action: close).buttonStyle(WorkbenchButtonStyle(prominent: true))
                } else if let path, localIssue != nil && !needsExport {
                    Button("查看本地差异") { model.compareLocal(path) }.buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(!model.canChangeBatch)
                    Button("重新核验此文件") { Task { await model.verifyRemaining(path) } }.disabled(!model.canChangeBatch || !model.matchesScope)
                } else if needsExport {
                    Button("查看导出清单", action: export).buttonStyle(WorkbenchButtonStyle(prominent: true))
                } else if done || skipped {
                    Button("返回文件列表", action: close).buttonStyle(WorkbenchButtonStyle(prominent: true))
                } else if let path {
                    if ready {
                        Button(model.reviewing ? "请在对比窗口确认" : "查看差异并确认") { model.openReview([path]) }
                            .buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(!model.canChangeBatch)
                    } else if blocked {
                        Button("查看本地差异") { model.compareLocal(path) }.buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(!model.canChangeBatch)
                        Button("重新生成") { Task { await model.retry(path) } }.disabled(!model.canChangeBatch || !model.matchesScope)
                        if model.entries[path]?.status == "ready" {
                            Button("暂不合入") { Task { await model.skipBlocked(path) } }.disabled(!model.canChangeBatch)
                        }
                    } else {
                        Button("生成副本") { model.selectedPaths = [path]; Task { await model.merge() } }
                            .buttonStyle(WorkbenchButtonStyle(prominent: true))
                            .disabled(!model.canChangeBatch || !model.matchesScope || !model.canGenerate(path) || !model.visibleFiles.contains { $0.path == path })
                    }
                }
            }.buttonStyle(WorkbenchButtonStyle()).controlSize(.large)
            Text(busy ? "任务继续执行，可返回文件列表查看其他文件" : model.reviewing ? "核对与写入由现有对比窗口完成" : (done || (localSame && !verifiedSame)) ? "本地已包含；尚未提交 SVN" : blocked ? "处理问题后重新生成，原副本与记录仍保留" : "确认前不会写入 \(model.targetName) 本地文件")
                .font(.system(size: 11)).foregroundStyle(muted)
        }
    }
}

private struct FocusedPointer: Shape {
    func path(in rect: CGRect) -> Path {
        Path { path in
            path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
            path.addLine(to: CGPoint(x: rect.midX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
            path.closeSubpath()
        }
    }
}
