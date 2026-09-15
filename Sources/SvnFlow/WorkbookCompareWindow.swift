import SwiftUI
import AppKit
import SVNCore

struct SheetGrid: Sendable {
    let identity = UUID()
    var cells: [String: WorkbookDifference] = [:]
    var numbers: [Int] = []
    var changedRows: Set<Int> = []
    var columns = 1
    init(_ sheet: WorkbookSheetComparison?) {
        changedRows.formUnion(sheet?.changedPhysicalRows ?? [])
        for cell in sheet?.rows ?? [] {
            let row = Int(cell.address.filter(\.isNumber)) ?? 1
            cells[cell.address] = cell
            if cell.changed {
                changedRows.insert(row)
            }
            var column = 0
            for b in cell.address.utf8 where b >= 65 && b <= 90 { column = column * 26 + Int(b - 64) }
            columns = max(columns, column)
        }
        self.numbers = sheet?.rowNumbers ?? []
    }
    static func letter(_ index: Int) -> String {
        var n = index + 1, text = ""
        while n > 0 { n -= 1; text = String(UnicodeScalar(65 + n % 26)!) + text; n /= 26 }
        return text
    }
}
@MainActor final class WorkbookModel: ObservableObject {
    let path: String
    let revision: String?
    let change: ChangedPath?
    let files: ComparisonFiles?
    @Published var comparison: WorkbookComparison?
    @Published var busy = false
    @Published var error = ""
    @Published var sheet = ""
    @Published var selection: String?
    @Published var mode = 1
    @Published var grid = SheetGrid(nil)
    @Published var navigation = 0
    init(path: String, revision: String?, change: ChangedPath? = nil, files: ComparisonFiles? = nil) { self.path = path; self.revision = revision; self.change = change; self.files = files }
    var current: WorkbookSheetComparison? { comparison?.sheets.first { $0.name == sheet } }
    var visibleRows: [Int] { grid.numbers.filter { $0 <= 5 || mode == 0 || grid.changedRows.contains($0) } }
    var totalChanges: Int { comparison?.sheets.reduce(0) { $0 + $1.changedCount } ?? 0 }
    var formulaChanges: Int { comparison?.sheets.reduce(0) { count, sheet in count + sheet.rows.filter { ($0.old?.formula ?? "") != ($0.new?.formula ?? "") }.count } ?? 0 }
    var summary: String {
        guard let comparison else { return "等待比较" }
        if comparison.bytesEqual { return "文件内容完全相同" }
        if totalChanges == 0 { return comparison.inspectionError == nil ? "单元格值与公式相同 · 文件结构或设置存在变化" : "单元格值与公式相同 · 内部结构尚未完成核验" }
        return "全工作簿 \(totalChanges) 个单元格差异 · \(formulaChanges) 处公式差异"
    }
    func chooseSheet() { grid = SheetGrid(current); selection = nil }
    func navigateChange(forward: Bool) {
        let rows = grid.changedRows.sorted()
        guard !rows.isEmpty else { return }
        let current = selection.flatMap { Int($0.filter(\.isNumber)) }
        let destination = forward ? (rows.first { $0 > (current ?? -1) } ?? rows[0]) : (rows.last { $0 < (current ?? Int.max) } ?? rows[rows.count - 1])
        selection = (0..<grid.columns).map { SheetGrid.letter($0) + String(destination) }.first { grid.cells[$0]?.changed == true } ?? "A\(destination)"
        navigation += 1
    }
    func load() async {
        guard !busy else { return }; busy = true; error = ""; defer { busy = false }
        do {
            if let files { comparison = try await RepositoryQuery().compareWorkbookFiles(files) }
            else { comparison = try await RepositoryQuery().compareWorkbook(path, revision: revision, change: change) }
            if comparison?.sheets.contains(where: { $0.name == sheet }) != true { sheet = comparison?.sheets.first(where: { $0.changedCount > 0 })?.name ?? comparison?.sheets.first?.name ?? "" }
            chooseSheet()
        } catch { comparison = nil; grid = SheetGrid(nil); self.error = error.localizedDescription }
    }

}
struct WorkbookCompareWindow: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @StateObject var model: WorkbookModel
    @State private var withdrawing = false
    var showsPin = true
    var review: ComparisonReviewActions? = nil
    var body: some View {
        let _ = interfaceLanguage;
        VStack(spacing: 0) {
            if let review { ComparisonReviewBar(actions: review, ready: model.comparison != nil && !model.busy) }
            HStack(spacing: 20) {
                WorkbenchHeading(eyebrow: "COMPARE / WORKBOOK", title: (model.path as NSString).lastPathComponent, subtitle: "", symbol: "tablecells")
                Spacer(minLength: 0)
                Button { model.navigateChange(forward: false) } label: { Label("上一处", systemImage: "chevron.up") }.buttonStyle(WorkbenchButtonStyle()).help("上一处差异，首尾循环")
                    .disabled(model.busy || model.grid.changedRows.isEmpty)
                Button { model.navigateChange(forward: true) } label: { Label("下一处", systemImage: "chevron.down") }.buttonStyle(WorkbenchButtonStyle()).help("下一处差异，首尾循环")
                    .disabled(model.busy || model.grid.changedRows.isEmpty)
                Picker(T("Display", "显示"), selection: $model.mode) {
                    Text(L("差异")).tag(1)
                    Text(L("全部")).tag(0)
                }.pickerStyle(.segmented).labelsHidden().frame(width: 160)
            }.padding(.horizontal, 24).padding(.vertical, 16).background(WorkbenchTheme.canvas)
            Divider()
            HStack {
                Image(systemName: model.totalChanges == 0 ? "equal.circle" : "not.equal")
                Text(model.summary).textSelection(.enabled)
                ComparisonLegend()
                Spacer()
            }.font(.system(size: 11)).padding(.horizontal, 12).frame(height: 27).background(WorkbenchTheme.panel)
            ZStack {
                HStack(spacing: 4) {
                    Canvas { context, size in
                        let maxRow = max(model.grid.numbers.last ?? 1, 1)
                        for row in model.grid.changedRows { context.fill(Path(CGRect(x: 2, y: CGFloat(row) / CGFloat(maxRow) * size.height, width: 8, height: 2)), with: .color(WorkbenchTheme.warning)) }
                    }.frame(width: 12).background(WorkbenchTheme.canvas)
                    VStack(spacing: 0) {
                        HStack(spacing: 5) { sourceHeader(old: true); sourceHeader(old: false) }
                        WorkbookGrids(grid: model.grid, rows: Array(Set(model.visibleRows).union(review?.withdrawnRows[model.sheet] ?? [])).sorted(), selection: $model.selection, swapped: false, formulas: false, fontSize: 13, navigation: model.navigation, withdraw: review == nil ? nil : { row in withdrawRow(row) }, withdrawEnabled: !withdrawing && !model.busy, withdrawnRows: review?.withdrawnRows[model.sheet] ?? [])
                            .frame(minHeight: 360)
                    }
                }
                if model.busy { ProgressView(L("读取工作表并比较…")).padding(24).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8)) }
                if !model.error.isEmpty { Text(L(model.error)).foregroundStyle(WorkbenchTheme.danger).padding(24).background(.regularMaterial).textSelection(.enabled) }
                if !model.busy && model.comparison != nil && model.visibleRows.isEmpty { Text(L("当前筛选下没有行")).foregroundStyle(WorkbenchTheme.muted) }
            }
            WorkbookInlineDetail(selection: model.selection, cell: model.selection.flatMap { model.grid.cells[$0] })
            HStack { Text(model.selection ?? L("未选择单元格")); Text(review == nil ? L("｜只读 · 禁止编辑") : "｜右侧操作列：撤回修改；误点后可点击“复原”"); Spacer(); Text(T("First 5 rows and column A frozen · Synchronized scrolling", "已冻结前 5 行及首列 · 左右同步滚动")) }.font(.system(size: 10)).foregroundStyle(WorkbenchTheme.muted).padding(.horizontal, 16).frame(height: 19).background(WorkbenchTheme.panel)
            ScrollView(.horizontal) {
                HStack(spacing: 1) {
                    ForEach(model.comparison?.sheets ?? []) { sheet in
                        Button { model.sheet = sheet.name } label: {
                            HStack(spacing: 5) { if sheet.changedCount > 0 { Rectangle().fill(WorkbenchTheme.warning).frame(width: 6, height: 6) }; Text(sheet.name); Text("\(sheet.changedCount)").foregroundStyle(WorkbenchTheme.muted); if !sheet.oldExists || !sheet.newExists { Text(sheet.oldExists ? "已删除" : "新增").foregroundStyle(WorkbenchTheme.warning) } }.padding(.horizontal, 9).frame(height: 24).background(model.sheet == sheet.name ? WorkbenchTheme.canvas : WorkbenchTheme.panel).overlay(alignment: .top) { if model.sheet == sheet.name { Rectangle().fill(Color.accentColor).frame(height: 2) } }
                        }.buttonStyle(.plain)
                    }
                }
            }.frame(height: 25).background(WorkbenchTheme.panel)
            HStack(spacing: 24) { Label(T("{0} differing rows", "{0} 个差异行", model.grid.changedRows.count), systemImage: "not.equal").foregroundStyle(WorkbenchTheme.warning); Text(T("{0} differing cells", "{0} 个差异单元格", model.current?.changedCount ?? 0)); Text(T("{0} rows shown", "{0} 行显示", model.visibleRows.count)); Spacer(); Text(L("按单元格地址对齐 · 只读")) }.font(.system(size: 10)).padding(.horizontal, 12).frame(height: 20).background(WorkbenchTheme.canvas)
        }.font(.system(size: 11)).workbenchStyle().task { await model.load() }.onChange(of: model.sheet) { _, _ in model.chooseSheet() }
    }
    private func withdrawRow(_ row: Int) {
        guard let actions = review, let withdraw = actions.withdrawRow, !actions.busy, !withdrawing else { return }
        let sheet = model.sheet
        withdrawing = true
        Task {
            actions.busy = true; actions.error = ""
            defer { actions.busy = false; withdrawing = false }
            do {
                actions.summary = try await withdraw(sheet, row)
                await model.load()
                model.selection = "A\(row)"
            } catch { actions.error = error.localizedDescription }
        }
    }
    private func sourceHeader(old: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 4) { Image(systemName: "doc"); Text(old ? "\(model.comparison?.label ?? "BASE") / \((model.path as NSString).lastPathComponent)" : model.path).lineLimit(1).truncationMode(.middle); Spacer(minLength: 0) }.padding(.horizontal, 6).frame(height: 23).background(WorkbenchTheme.canvas).border(WorkbenchTheme.border)
            HStack(spacing: 12) { Text(old ? (model.files?.oldLabel ?? L("SVN 基础版本")) : (model.files?.newLabel ?? model.revision.map { L("Repository · r") + $0 } ?? "本地工作副本 · 未提交")); Text(!old && review != nil ? "可撤回行修改" : L("只读")); Text(L("MS Excel 工作簿")); Text("Unicode (UTF-8)"); Spacer(minLength: 0)

            }.font(.system(size: 9)).lineLimit(1).frame(height: 24).padding(.horizontal, 6).background(WorkbenchTheme.canvas)
        }.frame(maxWidth: .infinity)
    }
}

private struct WorkbookInlineDetail: View {
    let selection: String?
    let cell: WorkbookDifference?
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: cell == nil ? "info.circle" : "square.grid.2x2")
                Text(selection.map { "\($0) · 完整值" } ?? "选择单元格查看完整值")
                    .font(.system(size: 12, weight: .semibold))
                Spacer()
                Text(cell?.changeExplanation ?? "表格为只读；点击差异单元格查看变更原因")
                    .font(.system(size: 10))
                    .foregroundStyle(WorkbenchTheme.muted)
                    .lineLimit(1)
            }
            HStack(spacing: 12) {
                valueColumn(title: "左侧 · 基础版本", value: cell?.old?.display, tone: ComparisonAppearance.removed)
                valueColumn(title: "右侧 · 待合入版本", value: cell?.new?.display, tone: ComparisonAppearance.added)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, minHeight: 125, maxHeight: 125, alignment: .topLeading)
        .background(WorkbenchTheme.panel)
        .overlay(alignment: .top) { Divider() }
        .textSelection(.enabled)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(selection.map { "\($0) 单元格完整值" } ?? "单元格完整值")
    }
    private func valueColumn(title: String, value: String?, tone: NSColor) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundStyle(WorkbenchTheme.muted)
            ScrollView(.vertical) {
                Text(value ?? "（空）")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(Color(nsColor: tone))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(maxHeight: 72)
            .background(WorkbenchTheme.canvas)
            .clipShape(.rect(cornerRadius: 5))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
