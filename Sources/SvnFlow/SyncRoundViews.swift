import AppKit
import SwiftUI
import SVNCore

/// Entry and history precede the workbench; opening this view does not query SVN.
struct SyncRoundEntry: View {
    @ObservedObject var model: BranchSyncModel
    @State private var entered = false
    @State private var scope = false
    @State private var history = false
    var body: some View {
        Group {
            if entered || (model.busy && model.action == "remaining-diff") { BranchSyncWindow(model: model) }
            else {
                VStack(alignment: .leading, spacing: 24) {
                    Text("开始分支合入").font(.largeTitle.bold())
                    Text("先确认范围；进入后自动核验，仅显示差异与需处理文件。")
                        .foregroundStyle(.secondary)
                    if let report = model.report {
                        GroupBox("上次轮次 · \(report.config.author) · \(model.directionTitle)") {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("固定范围：\(report.config.start) — \(report.config.end)").textSelection(.enabled)
                                Text(report.config.target).font(.caption).textSelection(.enabled)
                                Text("\(report.files.count) 个文件 · 已保存 \(model.entries.count) 条处理记录")
                                Button("继续这轮合入") { model.restoreRound(model.folder); entered = true }
                                    .buttonStyle(.borderedProminent).disabled(model.busy || model.reviewing || model.batchAccepting)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                        }
                    }
                    HStack {
                        Button("查看历史轮次") { history = true }
                        Spacer()
                        Button("新建一轮…") { scope = true }.buttonStyle(.borderedProminent)
                    }.disabled(!model.canChangeBatch)
                    if model.busy { HStack { ProgressView().controlSize(.small); Text(model.activity) } }
                    else { Text(model.activity).font(.caption).foregroundStyle(.secondary) }
                    Text("新轮次纳入新的提交；已有副本和每次写入前的备份保留。")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(40).frame(maxWidth: 760).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .sheet(isPresented: $scope) {
            SyncScopeView(model: model, applied: { entered = true }) { scope = false }
        }
        .sheet(isPresented: $history) {
            SyncRoundHistory(model: model) { history = false; entered = true }
        }
    }
}

struct SyncRoundRecord: Identifiable, Sendable {
    let folder: URL
    let author: String
    let start: String
    let end: String
    let target: String
    let count: Int
    var id: String { folder.path }
    static func read(root: URL, current: URL) -> [Self] {
        let folders = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        return Set(folders + [current]).compactMap { folder in
            guard let data = try? Data(contentsOf: folder.appendingPathComponent("report.json")),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let config = json["config"] as? [String: Any],
                  let author = config["author"] as? String, let end = config["end"] as? String,
                  let start = config["start"] as? String, let target = config["target"] as? String else { return nil }
            return Self(folder: folder, author: author, start: start, end: end, target: target,
                        count: (json["fileItems"] as? [Any])?.count ?? 0)
        }.sorted { $0.end > $1.end }
    }
}

struct SyncRoundHistory: View {
    @ObservedObject var model: BranchSyncModel
    let resumed: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var rounds: [SyncRoundRecord] = []
    @State private var loading = true
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("历史轮次").font(.title2.bold()); Spacer(); Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction) }
            Text("按原范围继续，自动补齐核验结果；生成与确认前仍会复核。")
                .foregroundStyle(.secondary)
            if loading { ProgressView("读取本地记录…") }
            else if rounds.isEmpty { ContentUnavailableView("暂无保存轮次", systemImage: "clock") }
            List(rounds) { round in
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(round.author) · \(round.count) 个文件").font(.headline)
                    Text("\(round.start) — \(round.end)").font(.caption)
                    Text(round.target).font(.caption).foregroundStyle(.secondary)
                    Button("继续本轮") {
                        model.restoreRound(round.folder)
                        if model.folder == round.folder { resumed() }
                    }.disabled(!model.canChangeBatch)
                }.padding(.vertical, 8)
            }
            Text(model.activity).font(.caption).foregroundStyle(.secondary)
        }.padding(24).frame(width: 740, height: 550)
        .task {
            let root = model.backupRoot, current = model.folder
            rounds = await Task.detached { SyncRoundRecord.read(root: root, current: current) }.value
            loading = false
        }
    }
}

struct SyncWriteBackup: Decodable, Identifiable, Sendable {
    let id: String
    let path: String
    let created: String
    let existed: Bool
    let before: String?
    let status: String
    static func read(folder: URL) -> [Self] {
        let root = folder.appendingPathComponent("写入备份")
        return ((try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []).compactMap {
            guard let data = try? Data(contentsOf: $0.appendingPathComponent("record.json")) else { return nil }
            return try? JSONDecoder().decode(Self.self, from: data)
        }.sorted { $0.created > $1.created }
    }
}

struct SyncBackupPanel: View {
    @ObservedObject var model: BranchSyncModel
    @Environment(\.dismiss) private var dismiss
    @State private var records: [SyncWriteBackup] = []
    @State private var selected: String?
    @State private var loading = true
    private var current: SyncWriteBackup? { records.first { $0.id == selected } }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Text("本轮备份与处理记录").font(.title2.bold()); Spacer(); Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction) }
            Text(model.folder.lastPathComponent).font(.caption).textSelection(.enabled)
            HSplitView {
                List(records, selection: $selected) { record in
                    VStack(alignment: .leading, spacing: 6) {
                        Text((record.path as NSString).lastPathComponent)
                        Text(record.created).font(.caption).foregroundStyle(.secondary)
                    }.tag(record.id)
                }.frame(minWidth: 260)
                VStack(alignment: .leading, spacing: 16) {
                    if let current {
                        Text(current.path).font(.headline).textSelection(.enabled)
                        Text(current.status == "written" ? "已写入本地，尚未提交 SVN" : "写入前备份已保存 · 请核对是否完成写入")
                        Text(current.created).font(.caption)
                        Text(current.existed ? "保留此次写入前的完整原件及 SVN 属性。" : "写入前文件不存在；已保存新增前状态。")
                        Button("对比备份与当前文件") {
                            guard let target = model.report?.config.target else { return }
                            let local = URL(fileURLWithPath: target).appendingPathComponent(current.path).path
                            QueryWindows.shared.compare(local, files: ComparisonFiles(old: current.before,
                                new: FileManager.default.fileExists(atPath: local) ? local : nil,
                                oldLabel: "此次写入前备份", newLabel: "Release 当前本地文件"))
                        }.disabled(current.before.map { !FileManager.default.fileExists(atPath: $0) } ?? false)
                    } else { Text(loading ? "正在读取记录…" : records.isEmpty ? "本轮暂无新版独立写入备份；旧版原件可从下方入口查看。" : "选择一条写入记录查看备份") }
                    Spacer()
                    Button("在访达中查看本轮全部记录") { NSWorkspace.shared.open(model.folder) }
                    Text("旧版原件、候选副本及完整日志也保留在本轮目录中。")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(16).frame(minWidth: 330)
            }
        }.padding(24).frame(width: 830, height: 550)
        .task {
            let folder = model.folder
            records = await Task.detached { SyncWriteBackup.read(folder: folder) }.value
            selected = records.first?.id; loading = false
        }
    }
}
