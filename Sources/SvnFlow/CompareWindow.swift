import AppKit
import SwiftUI
import SVNCore

@MainActor final class CompareModel: ObservableObject {
    let path: String
    let revision: String?
    let change: ChangedPath?
    let files: ComparisonFiles?
    let query = RepositoryQuery()
    @Published var ignoresIndentation = false
    @Published var expandsLua = true
    var isLua: Bool { (path as NSString).pathExtension.lowercased() == "lua" }
    @Published var comparison: FileComparison?
    @Published var busy = false
    @Published var error = ""
    @Published var selectedChange = -1
    @Published var selectedRow: Int?
    @Published var mode = 1
    @Published var expanded: Set<Int> = []
    @Published var navigation = 0
    @Published var generation = 0
    init(path: String, revision: String? = nil, change: ChangedPath? = nil, files: ComparisonFiles? = nil) { self.path = path; self.revision = revision; self.change = change; self.files = files; self.ignoresIndentation = (path as NSString).pathExtension.lowercased() == "lua" }
    var changes: [Int] { comparison?.changeStarts ?? [] }
    func navigateChange(forward: Bool) {
        let rows = changes.sorted()
        guard !rows.isEmpty else { return }
        let current = selectedRow
        let destination = forward ? (rows.first { $0 > (current ?? -1) } ?? rows[0]) : (rows.last { $0 < (current ?? Int.max) } ?? rows[rows.count - 1])
        selectedRow = destination
        navigation += 1
    }
    func refresh() async {
        guard !busy else { return }; busy = true; error = ""
        defer { busy = false }
        do { if let files { comparison = try await query.compareFiles(files) } else if let revision { comparison = try await query.compareRepositoryFile(path, revision: revision, change: change) } else { comparison = try await query.compareFile(path) }; comparison = comparison?.ignoringIndentation(ignoresIndentation).expandingLua(isLua && expandsLua); selectedChange = -1; selectedRow = comparison?.changeStarts.first; expanded = []; generation += 1 }
        catch { comparison = nil; self.error = error.localizedDescription }
    }
}

struct CompareWindow: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @StateObject var model: CompareModel
    @State private var textReview: TextReviewInfo?
    @State private var attributionError = ""
    @State private var loadingAttribution = false
    @State private var chosenField = ""
    var showsPin = true
    var review: ComparisonReviewActions? = nil
    var body: some View {
        let _ = interfaceLanguage
        VStack(spacing: 0) {
            if let review { ComparisonReviewBar(actions: review, ready: model.comparison != nil && !model.busy && !loadingAttribution && (review.loadTextReview == nil || textReview != nil)) }
            HStack(spacing: 20) {
                WorkbenchHeading(eyebrow: model.isLua ? "COMPARE / LUA" : "COMPARE / TEXT", title: (model.path as NSString).lastPathComponent, subtitle: model.isLua ? "Lua 代码对比" : "文本对比", symbol: model.isLua ? "curlybraces" : "doc.text")
                Spacer(minLength: 0)
                Button { model.navigateChange(forward: false) } label: { Label("上一处", systemImage: "chevron.up") }.buttonStyle(WorkbenchButtonStyle()).help("上一处差异，首尾循环")
                    .disabled(model.busy || model.changes.isEmpty)
                Button { model.navigateChange(forward: true) } label: { Label("下一处", systemImage: "chevron.down") }.buttonStyle(WorkbenchButtonStyle()).help("下一处差异，首尾循环")
                    .disabled(model.busy || model.changes.isEmpty)
                Picker(T("Display", "显示"), selection: $model.mode) {
                    Text(T("Differences", "差异")).tag(1)
                    Text(T("All", "全部")).tag(0)
                }.pickerStyle(.segmented).labelsHidden().frame(width: 160)
            }.padding(.horizontal, 24).padding(.vertical, 16).background(WorkbenchTheme.canvas)
            Divider()
            if model.isLua {
                HStack(spacing: 16) {
                    Picker("Lua 阅读方式", selection: $model.expandsLua) {
                        Text("结构展开").tag(true)
                        Text("原文").tag(false)
                    }.pickerStyle(.segmented).frame(width: 200)
                        .disabled(model.busy || loadingAttribution || review?.busy == true)
                    Text(model.comparison?.luaLayoutUnavailable == true ? "无法安全展开，已显示原文" : model.expandsLua ? "按 Lua 层级展开 · 显示原文行号 · 原文件不变" : "保留原文排版与行号")
                        .foregroundStyle(WorkbenchTheme.muted)
                    Spacer()
                }.padding(.horizontal, 24).padding(.vertical, 8).background(WorkbenchTheme.panel)
            }
            if loadingAttribution { Text("正在读取逐行 SVN 来源…").foregroundStyle(WorkbenchTheme.muted).padding(5) }
            if !attributionError.isEmpty { Text(attributionError).foregroundStyle(WorkbenchTheme.danger).textSelection(.enabled).padding(5) }
            if let info = textReview {
                Text("逐行来源：作者 · SVN 日期（UTC） · 版本号。待合入尚未提交；源分支最新值固定于本批 r\(info.revision)。")
                    .font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted).padding(5)
            }
            HStack(spacing: 1) {
                header(model.comparison?.baseLabel ?? L("Base Revision"))
                header(model.files?.newLabel ?? model.revision.map { L("Repository · r") + $0 } ?? L("Working Copy"))
            }.background(WorkbenchTheme.border)
            if let comparison = model.comparison {
                if comparison.rows.isEmpty {
                    Text("两侧文件均为空").foregroundStyle(WorkbenchTheme.muted).frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                TextComparisonPanes(comparison: comparison,
                    lines: comparison.displayLines(mode: model.mode, context: model.isLua && model.expandsLua ? 4 : 2, expanded: model.expanded),
                    isLua: model.isLua, oldAnnotations: textReview?.old ?? [], newAnnotations: textReview?.new ?? [],
                    generation: model.generation, navigation: model.navigation, selection: $model.selectedRow,
                    expand: { model.expanded.insert($0) })
                }
                Divider()
                if let info = textReview, !info.choices.isEmpty { fieldChoices(info) }
                if let index = model.selectedRow, comparison.rows.indices.contains(index) {
                    detail(comparison.rows[index])
                } else {
                    Text(T("Select a line to inspect its changes", "选择一行查看具体文字差异")).foregroundStyle(WorkbenchTheme.muted).frame(maxWidth: .infinity, minHeight: 62)
                }
            } else if model.busy {
                ProgressView(L("Loading comparison…")).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 12) {
                    Text(L(model.error)).foregroundStyle(WorkbenchTheme.danger).textSelection(.enabled)
                    Button("重新读取") { Task { await refresh() } }.buttonStyle(WorkbenchButtonStyle())
                }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Divider()
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                if let comparison = model.comparison {
                    Text(comparison.identical ? L("Files are identical") : comparison.formattingOnly ? "仅排版不同 · 原文件未改变" : T("{0} change blocks", "{0} 处差异", model.changes.count))
                    if comparison.lineEndingChange { Text(T("· Final newline differs", "· 文件末尾换行不同")).foregroundStyle(WorkbenchTheme.warning) }
                }
                Spacer()
                ComparisonLegend(strikesOldValues: false)
                Text(T("Read only · UTF-8 · Synchronized scrolling", "只读 · UTF-8 · 左右同步滚动"))
            }.font(.system(size: 11)).padding(7).background(WorkbenchTheme.panel)
        }.font(.system(size: 12)).workbenchStyle().task { await refresh() }
        .onChange(of: model.expandsLua) { _, enabled in
            model.comparison = model.comparison?.expandingLua(model.isLua && enabled)
            model.expanded = []; model.selectedRow = model.comparison?.changeStarts.first; model.generation += 1
        }
        .onChange(of: model.ignoresIndentation) { _, enabled in
            model.comparison = model.comparison?.ignoringIndentation(enabled)
            model.expanded = []; model.selectedRow = model.comparison?.changeStarts.first; model.generation += 1
        }
        .onChange(of: model.selectedRow) { _, index in
            guard let index, let rows = model.comparison?.rows, rows.indices.contains(index), let info = textReview else { return }
            let row = rows[index]
            if let choice = info.choices.first(where: { ($0.newLine != nil && $0.newLine == row.newNumber) || ($0.oldLine != nil && $0.oldLine == row.oldNumber) }) { chosenField = choice.id }
        }
        .onChange(of: model.mode) { _, _ in model.expanded = [] }
    }
    func refresh() async {
        guard !loadingAttribution, review?.busy != true else { return }
        textReview = nil; attributionError = ""
        await model.refresh()
        await loadAttribution()
    }
    func loadAttribution() async {
        guard let load = review?.loadTextReview, model.comparison != nil else { return }
        loadingAttribution = true
        defer { loadingAttribution = false }
        do {
            textReview = try await load(); model.generation += 1
            if !(textReview?.choices.contains { $0.id == chosenField } ?? false) { chosenField = textReview?.choices.first?.id ?? "" }
        } catch { attributionError = "逐行来源读取失败，请重新打开对比重试：" + error.localizedDescription }
    }
    func fieldChoices(_ info: TextReviewInfo) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Picker("选择字段", selection: $chosenField) {
                ForEach(info.choices) { choice in Text(choice.label).tag(choice.id) }
            }
            if let choice = info.choices.first(where: { $0.id == chosenField }) {
                HStack(alignment: .top, spacing: 10) {
                    ForEach(0..<3, id: \.self) { side in
                        VStack(alignment: .leading, spacing: 4) {
                            Button((choice.selected == side ? "✓ " : "") + ["采用 Release", "采用原待合入", "采用源分支最新"][side]) {
                                Task { await choose(choice.id, side: side) }
                            }.disabled(review?.busy == true || loadingAttribution || model.busy)
                            Text(choice.origins[side]).font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted).textSelection(.enabled)
                            ScrollView { Text(choice.values[side] ?? "（该版本无此字段）").font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 48)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                Text("选择只修改待合入副本。可反复改选，确认文件后才写入本地 Release。").font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted)
            }
        }.padding(8).background(WorkbenchTheme.canvas)
    }
    func choose(_ key: String, side: Int) async {
        guard let review, let choose = review.chooseText, !review.busy else { return }
        review.busy = true; review.error = ""
        defer { review.busy = false }
        do {
            review.summary = try await choose(key, side)
            await model.refresh()
            textReview = nil; attributionError = ""
            await loadAttribution()
        } catch { review.error = error.localizedDescription }
    }
    func header(_ title: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(model.path).lineLimit(1).truncationMode(.middle).help(model.path)
            HStack { Text(title).fontWeight(.semibold); Spacer(); Text(L("Read Only")).foregroundStyle(WorkbenchTheme.muted) }
        }.font(.system(size: 11)).padding(8).frame(maxWidth: .infinity).background(WorkbenchTheme.canvas)
    }
    func detail(_ row: ComparisonRow) -> some View {
        let diff = row.inline
        let fields = row.fieldChanges
        return VStack(alignment: .leading, spacing: 0) {
            if !fields.isEmpty {
                ScrollView(.horizontal) {
                    HStack(spacing: 18) {
                        ForEach(fields.indices, id: \.self) { index in
                            let field = fields[index]
                            HStack(spacing: 5) {
                                Text(field.name + "：")
                                Text(field.oldValue).foregroundStyle(WorkbenchTheme.danger)
                                Text("→").foregroundStyle(WorkbenchTheme.muted)
                                Text(field.newValue).foregroundStyle(WorkbenchTheme.warning)
                            }.fixedSize()
                        }
                    }.font(.system(size: 12, design: .monospaced)).textSelection(.enabled).padding(8)
                }.frame(height: 36)
            }
            Text(model.isLua && model.expandsLua ? "选中片段 · 原文行号与文字差异" : T("Selected line · character differences", "选中行 · 文字差异")).font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted).padding(.horizontal, 8).padding(.vertical, 4)
            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 3) {
                    detailLine(row.oldText, number: row.oldNumber, ranges: diff.oldRanges, old: true)
                    detailLine(row.newText, number: row.newNumber, ranges: diff.newRanges, old: false, addition: diff.oldRanges.isEmpty)
                }.padding(.horizontal, 8).padding(.bottom, 5)
            }.frame(height: 55)
        }.background(WorkbenchTheme.canvas)
    }
    func detailLine(_ text: String, number: Int?, ranges: [NSRange], old: Bool, addition: Bool = false) -> some View {
        let value = comparisonAttributedText(text, ranges: ranges, old: old, addition: addition)
        return HStack(alignment: .top, spacing: 6) {
            Text((old ? "− " : "+ ") + (number.map(String.init) ?? "—")).foregroundStyle(WorkbenchTheme.muted).frame(width: 60, alignment: .trailing)
            Text(AttributedString(value)).textSelection(.enabled).fixedSize(horizontal: true, vertical: false)
        }.font(.system(size: 11, design: .monospaced))
    }
}
