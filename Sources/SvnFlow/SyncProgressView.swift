import SwiftUI
import SVNCore

struct RemainingDiffResult: Decodable, Sendable {
    let snapshot: Int
    let noDiffPaths: [String]
    let differentPaths: [String]
    let errors: [String: String]
    var localStates: [String: String]? = nil
    var localIssues: [String: String]? = nil
    var reportDigest: String? = nil
    var complete: Bool? = nil
}

struct SyncActivity: Decodable, Sendable {
    struct Event: Decodable, Sendable {
        let elapsed: Double
        let message: String
        var timestamp: Double? = nil

        var timeLabel: String {
            guard let timestamp else { return "—" }
            return Date(timeIntervalSince1970: timestamp).formatted(
                .dateTime.hour(.twoDigits(amPM: .omitted)).minute(.twoDigits).second(.twoDigits))
        }
    }
    let token: String
    let phase: String
    let revision: Int
    let revisionIndex: Int
    let revisionTotal: Int
    var updatedAt: Double? = nil
    var filesCompleted: Int? = nil
    var filesTotal: Int? = nil
    var remaining: RemainingDiffResult? = nil
    var activePaths: [String]? = nil
    let commands: Int
    let events: [Event]
}

@MainActor final class SyncProgressModel: ObservableObject {
    @Published var verificationScope: String?
    @Published var activity: SyncActivity?
    @Published var started: Date?
    @Published var ended: Date?
    @Published var total = 0
    @Published var completed = 0 {
        didSet {
            if ["stage", "assess"].contains(watchedAction) {
                estimate.record(completed: completed, total: total, at: Date())
            }
        }
    }
    @Published var failures = 0
    @Published var currentName = ""
    @Published var phase = "等待选择文件"
    @Published var logURL: URL?
    @Published var cancelling = false
    private var watchedAction = ""
    private var estimate = FileProgressEstimate()

    func fileCounts(action: String) -> (completed: Int, total: Int) {
        if action == "remaining-diff" {
            let total = max(0, activity?.filesTotal ?? 0)
            return (min(max(0, activity?.filesCompleted ?? 0), total), total)
        }
        if ["stage", "assess"].contains(action) {
            return (min(max(0, completed), max(0, total)), max(0, total))
        }
        return (0, 0)
    }

    func remainingLabel(action: String, at date: Date) -> String {
        if cancelling { return "停止中 · 不再预估剩余时间" }
        if ended != nil { return "处理已结束" }
        if ["accept", "accept-low"].contains(action) { return "正在核对并写入，暂不预估剩余时间" }
        guard ["stage", "assess", "remaining-diff"].contains(action) else {
            return "预计剩余：总量确定后估算"
        }
        return estimate.remainingLabel(at: date)
    }

    private func receive(_ value: SyncActivity) {
        activity = value
        if watchedAction == "remaining-diff", let total = value.filesTotal {
            estimate.record(completed: value.filesCompleted ?? 0, total: total, at: Date())
        }
    }

    private var cancellationURL: URL?
    private var activityURL: URL?
    func cancelGeneration() {
        guard let url = cancellationURL else { return }
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data().write(to: url, options: .atomic)
            cancelling = true; phase = "正在停止本批生成…"
        }
        catch { phase = "取消请求未保存：" + error.localizedDescription }
    }
    var onRemaining: ((RemainingDiffResult) -> Void)?
    private var watcher: Task<Void, Never>?

    func beginBatch(total: Int) {
        cancelling = false
        self.total = total; completed = 0; failures = 0
        started = Date(); ended = nil; activity = nil
        estimate = FileProgressEstimate(); watchedAction = ""
    }
    func watch(folder: URL, token: String, action: String, path: String?) {
        watcher?.cancel()
        if started == nil || ended != nil { beginBatch(total: 0) }
        let continuesBatch = ["stage", "assess"].contains(action) && ["stage", "assess"].contains(watchedAction)
        if !continuesBatch {
            estimate = FileProgressEstimate()
            estimate.record(completed: ["stage", "assess"].contains(action) ? completed : 0,
                            total: ["stage", "assess"].contains(action) ? total : 0, at: Date())
        }
        watchedAction = action
        activity = nil
        logURL = folder.appendingPathComponent("operation-\(token).log")
        cancellationURL = ["catalog", "stage", "assess", "remaining-diff"].contains(action) ? folder.appendingPathComponent("cancel-\(token)") : nil
        currentName = path.map { ($0 as NSString).lastPathComponent } ?? ""
        let targetName = MergeEndpointDisplay.current().targetName
        phase = action == "remaining-diff" ? "核验当前 \(targetName) 剩余差异" : action == "catalog" ? "读取作者文件与 \(targetName) 快照" : action == "authors" ? "读取提交作者" : ["accept", "accept-low"].contains(action) ? "核对并写入已确认文件" : ["stage", "assess"].contains(action) ? "生成副本并评估风险" : "保存处理结果"
        if cancelling, let url = cancellationURL { try? Data().write(to: url, options: .atomic) }
        let file = folder.appendingPathComponent("activity-\(token).json")
        activityURL = file
        watcher = Task { [weak self] in
            while !Task.isCancelled {
                let value = await Task.detached(priority: .utility) {
                    (try? Data(contentsOf: file)).flatMap { try? JSONDecoder().decode(SyncActivity.self, from: $0) }
                }.value
                guard !Task.isCancelled else { return }
                if let value, value.token == token {
                    self?.receive(value)
                    if let remaining = value.remaining { self?.onRemaining?(remaining) }
                }
                do { try await Task.sleep(for: .milliseconds(350)) } catch { return }
            }
        }
    }
    func stopWatching() {
        watcher?.cancel(); watcher = nil; cancellationURL = nil
        if let file = activityURL, let data = try? Data(contentsOf: file),
           let final = try? JSONDecoder().decode(SyncActivity.self, from: data) {
            receive(final)
            if let remaining = final.remaining { onRemaining?(remaining) }
        }
    }
    func finish() { stopWatching(); ended = Date() }
}

struct SyncProgressPanel: View {
    @ObservedObject var progress: SyncProgressModel
    let action: String
    private var targetName: String { MergeEndpointDisplay.current().targetName }
    private var title: String {
        switch action {
        case "remaining-diff": return "正在核验当前 \(targetName) 剩余差异"
        case "catalog": return "正在读取合入范围"
        case "authors": return "正在读取提交作者"
        case "accept", "accept-low": return "正在写入本地 \(targetName)"
        case "defer": return "正在保存处理结果"
        default: return "正在整理合入内容"
        }
    }
    private var explanation: String {
        switch action {
        case "catalog", "authors", "remaining-diff": return "读取提交记录与目标快照，完成后更新文件队列。"
        case "accept", "accept-low": return "核对并写入已确认内容，不自动提交 SVN。"
        case "defer": return "保存本次决定，待合入副本仍保留在备份目录。"
        default: return "仅提取所选作者的修改，保留 \(targetName) 其他内容。"
        }
    }
    private var nextAction: String {
        if progress.cancelling { return "保留现场，等待停止确认" }
        switch action {
        case "stage", "assess": return "副本就绪后，进入同步确认并查看差异"
        case "accept", "accept-low": return "查看本地写入结果"
        case "catalog", "authors": return "读取完成后，选择需要合入的文件"
        default: return "等待当前操作完成"
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    ProgressView().controlSize(.small).tint(SyncOrbit.cyan)
                        .padding(11).background(SyncOrbit.cyan.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
                        .accessibilityLabel(progress.cancelling ? "正在停止" : "操作进行中")
                    VStack(alignment: .leading, spacing: 6) {
                        Text(progress.cancelling ? "正在等待任务停止" : title)
                            .font(.system(size: 20, weight: .semibold))
                        Text(explanation).font(.system(size: 12)).foregroundStyle(SyncOrbit.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                    Text(progress.cancelling ? "停止中" : "处理中")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(progress.cancelling ? SyncOrbit.amber : SyncOrbit.cyan)
                        .padding(.horizontal, 9).padding(.vertical, 5)
                        .background(SyncOrbit.cyan.opacity(0.08), in: Capsule())
                }
                Rectangle().fill(SyncOrbit.line).frame(height: 1)
                HStack(alignment: .firstTextBaseline) {
                    Label("当前任务", systemImage: "arrow.triangle.2.circlepath")
                        .font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                    Spacer()
                    if let event = progress.activity, event.revisionIndex > 0, event.revisionTotal > 0 {
                        Text("第 \(event.revisionIndex) / \(event.revisionTotal) 次提交")
                            .font(.system(size: 12, weight: .medium)).monospacedDigit()
                    }
                }
                Text(progress.activity?.phase ?? progress.phase)
                    .font(.system(size: 13, weight: .medium)).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 14) {
                    if let event = progress.activity, event.revision > 0 {
                        Text("版本 r\(String(event.revision))").monospacedDigit()
                    }
                    if let started = progress.started {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            let seconds = max(0, Int((progress.ended ?? context.date).timeIntervalSince(started)))
                            Text(String(format: "本批用时 %d:%02d", seconds / 60, seconds % 60)).monospacedDigit()
                        }
                    }
                    Spacer(minLength: 0)
                    if let updated = progress.activity?.updatedAt {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Text("活动更新于 \(max(0, Int(context.date.timeIntervalSince1970 - updated))) 秒前").monospacedDigit()
                        }
                    }
                }.font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
            }
            .padding(20).background(SyncOrbit.panel, in: RoundedRectangle(cornerRadius: 10))
            .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(SyncOrbit.line) }
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "arrow.right.circle").foregroundStyle(SyncOrbit.cyan)
                VStack(alignment: .leading, spacing: 5) {
                    Text("接下来").font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                    Text(nextAction).font(.system(size: 12))
                }
                Spacer(minLength: 0)
            }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .background(SyncOrbit.cyan.opacity(0.045), in: RoundedRectangle(cornerRadius: 8))
            if progress.failures > 0 {
                Label("\(progress.failures) 个文件需处理，可返回文件列表查看", systemImage: "exclamationmark.triangle")
                    .font(.system(size: 12)).foregroundStyle(SyncOrbit.amber)
            }
            SyncFileProgressView(progress: progress, action: action)
        }
    }
}

struct SyncActivityDrawer: View {
    @ObservedObject var progress: SyncProgressModel
    let summary: String
    let author: String
    let snapshot: Int?
    let close: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                VStack(alignment: .leading, spacing: 7) {
                    Text("处理状态与日志").font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
                    Text("任务活动").font(.system(size: 22, weight: .semibold))
                }
                Spacer()
                WorkbenchCloseButton(hint: "关闭活动面板，任务继续执行", action: close)
            }
            HStack {
                Text(author.isEmpty ? "尚未选择作者" : author)
                Spacer()
                if let snapshot { Text("Release · r\(snapshot)").monospacedDigit() }
            }.font(.system(size: 12)).foregroundStyle(SyncOrbit.muted)
            Text(summary).font(.system(size: 13))
            Rectangle().fill(SyncOrbit.line).frame(height: 1)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if let events = progress.activity?.events, !events.isEmpty {
                        ForEach(Array(events.enumerated().reversed()), id: \.offset) { index, event in
                            HStack(alignment: .top, spacing: 12) {
                                Circle().fill(index == events.count - 1 ? SyncOrbit.cyan : SyncOrbit.muted.opacity(0.5))
                                    .frame(width: 6, height: 6).padding(.top, 5)
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(event.timeLabel).font(.system(size: 11, design: .monospaced)).foregroundStyle(SyncOrbit.muted)
                                    Text(event.message).font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else {
                        Text("暂无活动记录。开始读取或生成后，任务事件会显示在这里。")
                            .font(.system(size: 13)).foregroundStyle(SyncOrbit.muted).padding(.vertical, 24)
                    }
                }.textSelection(.enabled)
            }
            HStack {
                if let started = progress.started {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let seconds = max(0, Int((progress.ended ?? context.date).timeIntervalSince(started)))
                        Label(String(format: "累计 %02d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60), systemImage: "stopwatch").monospacedDigit()
                    }
                }
                Spacer()
                Text("保留最近 40 条事件")
            }.font(.system(size: 11)).foregroundStyle(SyncOrbit.muted)
        }.padding(26).frame(width: 510, height: 540)
            .foregroundStyle(SyncOrbit.text).environment(\.colorScheme, .light).workbenchSecondarySurface()
    }
}

/// Shared by the file detail and the task panel so count/ETA semantics cannot drift.
struct SyncFileProgressView: View {
    @ObservedObject var progress: SyncProgressModel
    let action: String

    private var scope: String {
        switch action {
        case "remaining-diff": return progress.verificationScope ?? "全范围核验"
        case "stage", "assess": return "本批生成"
        case "catalog", "authors": return "全范围检索"
        default: return "当前操作"
        }
    }

    var body: some View {
        let counts = progress.fileCounts(action: action)
        VStack(alignment: .leading, spacing: 10) {
            if counts.total > 0 {
                HStack {
                    Text("\(scope) · 已处理 \(counts.completed) / \(counts.total) 个文件")
                    Spacer(minLength: 8)
                    Text("\(Int(Double(counts.completed) / Double(counts.total) * 100))%")
                        .foregroundStyle(WorkbenchTheme.accent).monospacedDigit()
                }.font(.system(size: 12))
                ProgressView(value: Double(counts.completed), total: Double(counts.total))
                    .accessibilityLabel("\(scope)文件完成进度")
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small).accessibilityLabel("当前操作进行中")
                    Text(["accept", "accept-low"].contains(action) ? "正在处理已确认内容" : "\(scope) · 正在确定文件总数")
                        .font(.system(size: 12))
                }
            }
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(progress.remainingLabel(action: action, at: context.date))
                    .font(.system(size: 13, weight: .medium)).foregroundStyle(WorkbenchTheme.text)
            }
            if ["stage", "assess"].contains(action), !progress.currentName.isEmpty {
                Text("当前文件：" + progress.currentName).font(.system(size: 11)).lineLimit(2)
            }
            if counts.total > 0 && !progress.cancelling {
                Text("按已完成文件耗时估算，仅代表当前阶段；文件大小与网络会影响耗时。")
                    .font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
            }
            if action == "remaining-diff", progress.verificationScope != nil {
                Text("仅核验本次指定文件，其他文件的已有结果保留。")
                    .font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
            } else if ["catalog", "authors", "remaining-diff"].contains(action) {
                Text("这是整个合入范围的任务，包含其他文件。")
                    .font(.system(size: 11)).fixedSize(horizontal: false, vertical: true)
            }
            if ["stage", "assess"].contains(action) && progress.failures > 0 {
                Text("\(progress.failures) 个文件需处理").font(.system(size: 11)).foregroundStyle(SyncOrbit.amber)
            }
        }.foregroundStyle(WorkbenchTheme.muted)
    }
}
