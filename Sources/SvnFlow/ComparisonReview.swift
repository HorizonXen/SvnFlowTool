import AppKit
import SwiftUI

struct TextReviewInfo: Decodable {
    struct Choice: Decodable, Identifiable {
        let id: String
        let label: String
        let values: [String?]
        let origins: [String]
        let oldLine: Int?
        let newLine: Int?
        let selected: Int
    }
    let old: [String]
    let new: [String]
    let choices: [Choice]
    let revision: Int
}

/// Optional confirmation controls shared by the existing comparison windows.
@MainActor final class ComparisonReviewActions: ObservableObject {
    let title: String
    @Published var summary: String
    @Published var confirmationHint = "左侧：Release SVN 快照　右侧：待合入结果。确认后写入本地 Release，尚不提交 SVN。"
    @Published var withdrawnRows: [String: Set<Int>] = [:]
    var withdrawRow: ((String, Int) async throws -> String)?
    var loadTextReview: (() async throws -> TextReviewInfo)?
    var chooseText: ((String, Int) async throws -> String)?
    let accept: () async throws -> Void
    let skip: () async throws -> Void
    let next: () -> Void
    let pause: () -> Void
    var progress: SyncProgressModel?
    var targetPath = ""
    var resultSummary: () -> String = { "已确认并写入本地 Release，尚未提交 SVN。" }
    @Published var showsWriteProgress = false
    @Published var writeResult = ""
    @Published var busy = false
    @Published var error = ""
    var resolved = false
    weak var window: NSWindow?
    init(title: String, summary: String, accept: @escaping () async throws -> Void, skip: @escaping () async throws -> Void, next: @escaping () -> Void, pause: @escaping () -> Void) {
        self.title = title; self.summary = summary; self.accept = accept; self.skip = skip; self.next = next; self.pause = pause
    }
    func decide(_ apply: Bool) async {
        guard !busy, !resolved, !showsWriteProgress else { return }
        busy = true; error = ""
        if apply { writeResult = ""; showsWriteProgress = true }
        do {
            if apply { try await accept() } else { try await skip() }
            resolved = true; busy = false
            if apply { writeResult = resultSummary() }
            else { window?.close(); next() }
        } catch {
            self.error = error.localizedDescription; busy = false
            // Keep the failure visible until the user returns to the file list.
        }
    }
    func finishWritePresentation() {
        guard !busy, showsWriteProgress else { return }
        showsWriteProgress = false
    }
    func writePresentationDidDismiss() {
        guard !busy else { return }
        window?.close()
        if resolved { next() }
    }
    func didClose() { if !resolved { pause() } }
}

struct ComparisonReviewBar: View {
    @ObservedObject var actions: ComparisonReviewActions
    let ready: Bool
    @State private var details = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(actions.title).fontWeight(.semibold)
                Button(details ? "收起合入说明" : "合入说明") { details.toggle() }
                Spacer()
                if actions.busy { ProgressView().controlSize(.small) }
                Button("暂不合入，下一文件") { Task { await actions.decide(false) } }.disabled(actions.busy || actions.resolved || actions.showsWriteProgress)
                Button("确认写入本地，下一文件") { Task { await actions.decide(true) } }
                    .buttonStyle(WorkbenchButtonStyle(prominent: true)).disabled(actions.busy || actions.resolved || actions.showsWriteProgress || !ready)
            }
            Text(actions.confirmationHint)
                .font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted)
            if details { ScrollView { Text(actions.summary).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 130) }
            if !actions.error.isEmpty { Text(actions.error).foregroundStyle(WorkbenchTheme.danger).textSelection(.enabled) }
        }.padding(10).background(Color.accentColor.opacity(0.08))
        .sheet(isPresented: $actions.showsWriteProgress, onDismiss: actions.writePresentationDidDismiss) {
            ComparisonWriteProgressSheet(actions: actions)
                .interactiveDismissDisabled()
        }
    }
}


private struct ComparisonWriteProgressSheet: View {
    @ObservedObject var actions: ComparisonReviewActions
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(actions.busy ? "正在确认合入" : actions.error.isEmpty ? "合入确认完成" : "合入未完成",
                  systemImage: actions.busy ? "arrow.triangle.2.circlepath" : actions.error.isEmpty ? "checkmark.circle" : "exclamationmark.triangle")
                .font(.system(size: 20, weight: .semibold))
            Text(actions.targetPath).font(.system(size: 13)).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            if actions.busy {
                if let progress = actions.progress { ComparisonWriteActivity(progress: progress) }
                else { ProgressView("正在核对并写入本地 Release…") }
                Text("核验完成后才写入 Release，目录可能暂时没有变化。请等待本次操作结束。")
                    .foregroundStyle(.secondary)
            } else {
                ScrollView {
                    Text(actions.error.isEmpty ? actions.writeResult : actions.error)
                        .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                }.frame(maxHeight: 160)
                if !actions.error.isEmpty {
                    Text("请返回文件列表核验，保留现场与备份。尚未提交 SVN。")
                        .foregroundStyle(.secondary)
                }
            }
            HStack {
                Spacer()
                Button(actions.busy ? "处理中…" : actions.error.isEmpty ? "继续下一文件" : "返回文件列表") {
                    actions.finishWritePresentation()
                }.disabled(actions.busy).keyboardShortcut(.defaultAction)
            }
        }.font(.system(size: 13)).padding(20).frame(width: 520)
    }
}

private struct ComparisonWriteActivity: View {
    @ObservedObject var progress: SyncProgressModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ProgressView().controlSize(.small)
            Text(progress.activity?.phase ?? progress.phase)
                .fixedSize(horizontal: false, vertical: true)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let seconds = max(0, Int(context.date.timeIntervalSince(progress.started ?? context.date)))
                Text("已用时 \(seconds / 60) 分 \(seconds % 60) 秒")
                    .monospacedDigit().foregroundStyle(.secondary)
            }
        }
    }
}
