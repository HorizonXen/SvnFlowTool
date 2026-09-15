import AppKit
import SVNCore
import SwiftUI

struct WorkbookGrids: NSViewRepresentable {
    let grid: SheetGrid
    let rows: [Int]
    @Binding var selection: String?
    let swapped: Bool
    let formulas: Bool
    let fontSize: CGFloat
    let navigation: Int
    var withdraw: ((Int) -> Void)? = nil
    var withdrawEnabled = true
    var withdrawnRows: Set<Int> = []
    func makeNSView(context: Context) -> TwinGridView { TwinGridView() }
    func updateNSView(_ view: TwinGridView, context: Context) {
        view.configure(self)
        view.selected = { selection = $0 }
    }
}
@MainActor final class TwinGridView: NSView {
    let left = DirectionalScrollView(), right = DirectionalScrollView()
    let a = SheetCanvas(), b = SheetCanvas()
    private var syncing = false
    private var navigation = 0
    var selected: ((String) -> Void)?
    override init(frame: NSRect) {
        super.init(frame: frame)
        for (scroll, canvas) in [(left, a), (right, b)] {
            scroll.documentView = canvas
            scroll.hasHorizontalScroller = true; scroll.hasVerticalScroller = true
            // Reserve a permanent scrollbar track even when macOS prefers overlay scrollers.
            scroll.scrollerStyle = .legacy
            scroll.autohidesScrollers = false; scroll.borderType = .bezelBorder
            scroll.setAccessibilityRole(.scrollArea)
            scroll.setAccessibilityLabel(canvas === a ? "基础版本表格，可横向和纵向滚动" : "待合入版本表格，可横向和纵向滚动")
            scroll.contentView.postsBoundsChangedNotifications = true
            NotificationCenter.default.addObserver(self, selector: #selector(scrolled(_:)), name: NSView.boundsDidChangeNotification, object: scroll.contentView)
            canvas.clicked = { [weak self] address in
                guard let self else { return }
                self.a.dismissExplanation(); self.b.dismissExplanation()
                self.a.selection = address; self.b.selection = address
                self.a.needsDisplay = true; self.b.needsDisplay = true
                self.selected?(address)
            }
            addSubview(scroll)
        }
    }
    required init?(coder: NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        let width = (bounds.width - 5) / 2
        left.frame = NSRect(x: 0, y: 0, width: width, height: bounds.height)
        right.frame = NSRect(x: width + 5, y: 0, width: width, height: bounds.height)
    }
    func configure(_ input: WorkbookGrids) {
        for (canvas, old) in [(a, !input.swapped), (b, input.swapped)] {
            if canvas.grid.identity != input.grid.identity || canvas.old != old || canvas.selection != input.selection || canvas.fontSize != input.fontSize || canvas.rows != input.rows.filter({ $0 > 5 }) || navigation != input.navigation {
                canvas.dismissExplanation()
            }
            canvas.showsExplanation = canvas === b
            canvas.grid = input.grid; canvas.rows = input.rows.filter { $0 > 5 }; canvas.old = old
            canvas.formulas = input.formulas; canvas.fontSize = input.fontSize
            canvas.selection = input.selection
            canvas.withdraw = old ? nil : input.withdraw
            canvas.withdrawEnabled = input.withdrawEnabled
            canvas.reviewLayout = input.withdraw != nil
            canvas.withdrawnRows = old ? [] : input.withdrawnRows
            canvas.frame.size = NSSize(width: canvas.columnX(input.grid.columns), height: CGFloat(canvas.rows.count) * canvas.rowHeight + canvas.headerHeight)
            canvas.needsDisplay = true
            canvas.updateRowButtons()
        }
        if navigation != input.navigation {
            navigation = input.navigation
            if let address = input.selection, let row = Int(address.filter(\.isNumber)) {
                let letters = address.filter(\.isLetter)
                let col = (0..<input.grid.columns).first { SheetGrid.letter($0) == letters } ?? 0
                for canvas in [a, b] {
                    let y: CGFloat
                    let height: CGFloat
                    if row <= 5 { y = canvas.visibleRect.minY; height = min(canvas.headerHeight, canvas.visibleRect.height) }
                    else if let index = canvas.rows.firstIndex(of: row) { y = CGFloat(index) * canvas.rowHeight; height = canvas.headerHeight + canvas.rowHeight }
                    else { continue }
                    let x = col == 0 ? canvas.visibleRect.minX : canvas.columnX(col) - canvas.frozenWidth
                    let width = col == 0 ? min(canvas.frozenWidth, canvas.visibleRect.width) : canvas.columnWidth(col) + canvas.frozenWidth
                    canvas.scrollToVisible(NSRect(x: x, y: y, width: width, height: height))
                }
            }
        }
    }
    @objc private func scrolled(_ notification: Notification) {
        guard !syncing, let clip = notification.object as? NSClipView else { return }
        syncing = true
        a.dismissExplanation(); b.dismissExplanation()
        let target = clip === left.contentView ? right : left
        // Both canvases share the same logical row/column coordinate space. Copy
        // both axes together so dragging either scrollbar keeps the pair aligned.
        let origin = NSPoint(x: clip.bounds.origin.x, y: clip.bounds.origin.y)
        target.contentView.scroll(to: origin)
        target.reflectScrolledClipView(target.contentView)
        a.needsDisplay = true; b.needsDisplay = true
        a.updateRowButtons(); b.updateRowButtons()
        syncing = false
    }
}
@MainActor final class SheetCanvas: NSView {
    var grid = SheetGrid(nil)
    var rows: [Int] = []
    var old = true
    var formulas = false
    var fontSize: CGFloat = 11
    var selection: String?
    var clicked: ((String) -> Void)?
    var showsExplanation = false
    private var explanationPopover: NSPopover?
    func dismissExplanation() { explanationPopover?.close(); explanationPopover = nil }
    override func viewWillMove(toWindow newWindow: NSWindow?) {
        if newWindow == nil { dismissExplanation() }
        super.viewWillMove(toWindow: newWindow)
    }
    private func showExplanation(address: String, rect: NSRect) {
        guard showsExplanation, window != nil, let cell = grid.cells[address], cell.changed else { return }
        let content = WorkbookCellExplanation(address: address, reason: cell.changeExplanation, tone: cell.explanationTone, left: old ? cell.new : cell.old, right: old ? cell.old : cell.new, close: { [weak self] in self?.dismissExplanation() })
        let popover = NSPopover()
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: content.workbenchSecondarySurface())
        popover.contentSize = NSSize(width: 380, height: 300)
        explanationPopover = popover
        popover.show(relativeTo: rect.intersection(visibleRect), of: self, preferredEdge: .maxY)
    }
    var withdraw: ((Int) -> Void)?
    var withdrawEnabled = true
    var reviewLayout = false
    var withdrawnRows: Set<Int> = []
    var actionWidth: CGFloat { reviewLayout ? 60 : 0 }
    var gutterWidth: CGFloat { actionWidth + 48 }
    private var rowButtons: [Int: NSButton] = [:]
    override func layout() { super.layout(); updateRowButtons() }
    func updateRowButtons() {
        let visible = visibleRect
        var positions: [Int: CGFloat] = [:]
        if withdraw != nil {
            for (index, row) in rows.enumerated() where grid.changedRows.contains(row) || withdrawnRows.contains(row) {
                let y = headerHeight + CGFloat(index) * rowHeight
                if y >= visible.minY + headerHeight && y < visible.maxY { positions[row] = y }
            }
            if frozenRowCount > 0 {
                for row in 1...frozenRowCount where grid.changedRows.contains(row) || withdrawnRows.contains(row) { positions[row] = visible.minY + 22 + CGFloat(row - 1) * rowHeight }
            }
        }
        for row in Array(rowButtons.keys) where positions[row] == nil { rowButtons.removeValue(forKey: row)?.removeFromSuperview() }
        for (row, y) in positions {
            let button = rowButtons[row] ?? NSButton(title: "撤回", target: self, action: #selector(withdrawClicked(_:)))
            if rowButtons[row] == nil { rowButtons[row] = button; addSubview(button) }
            let restored = withdrawnRows.contains(row)
            button.title = restored ? "复原" : "撤回"
            button.tag = row; button.font = .systemFont(ofSize: 10); button.bezelStyle = .recessed
            button.isEnabled = withdrawEnabled
            button.toolTip = restored ? "复原第 \(row) 行撤回前的待合入修改" : "撤回第 \(row) 行修改，恢复 Release 快照内容"
            button.setAccessibilityLabel("\(restored ? "复原" : "撤回")第 \(row) 行修改")
            button.frame = NSRect(x: visible.minX + 4, y: y + 2, width: actionWidth - 8, height: rowHeight - 4)
        }
    }
    @objc private func withdrawClicked(_ sender: NSButton) { if withdrawEnabled { withdraw?(sender.tag) } }
    func columnWidth(_ col: Int) -> CGFloat { col < 5 ? 70 : 112 }
    func columnX(_ col: Int) -> CGFloat { gutterWidth + CGFloat(min(col, 5)) * 70 + CGFloat(max(0, col - 5)) * 112 }
    func columnAt(_ x: CGFloat) -> Int { x < gutterWidth + 350 ? max(0, Int((x - gutterWidth) / 70)) : 5 + Int((x - gutterWidth - 350) / 112) }
    var diffColor: NSColor { ComparisonAppearance.modified }
    var rowHeight: CGFloat { max(reviewLayout ? 26 : 17, fontSize + 5) }
    var frozenRowCount: Int { min(5, grid.numbers.last ?? 0) }
    var headerHeight: CGFloat { 22 + CGFloat(frozenRowCount) * rowHeight }
    var frozenWidth: CGFloat { gutterWidth + (grid.columns > 0 ? columnWidth(0) : 0) }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    private func text(_ string: String, rect: NSRect, color: NSColor = .textColor, bold: Bool = false) {
        let style = NSMutableParagraphStyle(); style.lineBreakMode = .byClipping
        (string as NSString).draw(in: rect.insetBy(dx: 4, dy: 1), withAttributes: [.font: bold ? NSFont.boldSystemFont(ofSize: fontSize) : NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular), .foregroundColor: color, .paragraphStyle: style])
    }
    private func cellText(_ cell: WorkbookDifference?, rect: NSRect, bold: Bool = false) {
        let value = NSMutableAttributedString(attributedString: ComparisonAppearance.cellText(cell, old: old, formulas: formulas))
        let style = NSMutableParagraphStyle(); style.lineBreakMode = .byClipping
        let font = bold ? NSFont.boldSystemFont(ofSize: fontSize) : NSFont.monospacedSystemFont(ofSize: fontSize, weight: ComparisonAppearance.preservesFormulaValue(cell, old: old) ? .bold : .regular)
        value.addAttributes([.font: font, .paragraphStyle: style], range: NSRange(location: 0, length: value.length))
        value.draw(in: rect.insetBy(dx: 4, dy: 1))
    }
    override func draw(_ dirtyRect: NSRect) {
        WorkbenchTheme.canvasNS.setFill(); dirtyRect.fill()
        let visible = visibleRect
        let firstCol = max(0, columnAt(visible.minX))
        let lastCol = min(grid.columns - 1, columnAt(visible.maxX))
        let firstRow = max(0, Int((visible.minY - headerHeight) / rowHeight))
        let lastRow = min(rows.count - 1, Int((visible.maxY - headerHeight) / rowHeight))
        let lines = NSBezierPath(); lines.lineWidth = 0.5
        if firstRow <= lastRow && firstCol <= lastCol {
            for index in firstRow...lastRow {
                let number = rows[index], y = headerHeight + CGFloat(index) * rowHeight
                if grid.changedRows.contains(number) {
                    ComparisonAppearance.band.setFill()
                    NSRect(x: visible.minX, y: y, width: visible.width, height: rowHeight).fill()
                }
                for col in firstCol...lastCol {
                    let address = SheetGrid.letter(col) + String(number)
                    let cell = grid.cells[address]
                    let rect = NSRect(x: columnX(col), y: y, width: columnWidth(col), height: rowHeight)
                    if cell?.changed == true {
                        ComparisonAppearance.cellBackground(cell, old: old).setFill(); rect.fill()
                    }
                    cellText(cell, rect: rect)
                    if selection == address {
                        WorkbenchTheme.accentNS.setStroke(); let border = NSBezierPath(rect: rect.insetBy(dx: 0.7, dy: 0.7)); border.lineWidth = 1.5; border.stroke()
                    }
                }
                lines.move(to: NSPoint(x: visible.minX, y: y + rowHeight)); lines.line(to: NSPoint(x: visible.maxX, y: y + rowHeight))
            }
            for col in firstCol...lastCol + 1 {
                let x = columnX(col)
                lines.move(to: NSPoint(x: x, y: visible.minY)); lines.line(to: NSPoint(x: x, y: visible.maxY))
            }
        }
        WorkbenchTheme.borderNS.setStroke(); lines.stroke()
        // Keep row numbers and the first five worksheet rows visible while scrolling.
        WorkbenchTheme.panelNS.setFill()
        NSRect(x: visible.minX, y: visible.minY, width: gutterWidth, height: visible.height).fill()
        if firstRow <= lastRow {
            for index in firstRow...lastRow {
                let number = rows[index], y = headerHeight + CGFloat(index) * rowHeight
                if grid.changedRows.contains(number) { diffColor.withAlphaComponent(0.85).setFill(); NSRect(x: visible.minX + actionWidth + 4, y: y + 5, width: 5, height: 6).fill() }
                text(String(number), rect: NSRect(x: visible.minX + actionWidth + 10, y: y, width: 38, height: rowHeight), color: WorkbenchTheme.mutedNS)
            }
        }
        // Draw the actual first five spreadsheet rows once, pinned below column letters.
        WorkbenchTheme.canvasNS.setFill()
        NSRect(x: visible.minX, y: visible.minY, width: visible.width, height: headerHeight).fill()
        WorkbenchTheme.panelNS.setFill()
        NSRect(x: visible.minX, y: visible.minY, width: visible.width, height: 22).fill()
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: NSRect(x: visible.minX + gutterWidth, y: visible.minY, width: max(0, visible.width - gutterWidth), height: headerHeight)).addClip()
        if firstCol <= lastCol {
            for col in firstCol...lastCol {
                let x = columnX(col), letter = SheetGrid.letter(col)
                text(letter, rect: NSRect(x: x, y: visible.minY, width: columnWidth(col), height: 22), color: WorkbenchTheme.mutedNS)
                if frozenRowCount > 0 {
                    for row in 1...frozenRowCount {
                        let address = letter + String(row), cell = grid.cells[address]
                        let rect = NSRect(x: x, y: visible.minY + 22 + CGFloat(row - 1) * rowHeight, width: columnWidth(col), height: rowHeight)
                        if grid.changedRows.contains(row) { ComparisonAppearance.band.setFill(); rect.fill() }
                        if cell?.changed == true { ComparisonAppearance.cellBackground(cell, old: old).setFill(); rect.fill() }
                        cellText(cell, rect: rect, bold: row == 1)
                        if selection == address {
                            WorkbenchTheme.accentNS.setStroke()
                            let border = NSBezierPath(rect: rect.insetBy(dx: 0.7, dy: 0.7)); border.lineWidth = 1.5; border.stroke()
                        }
                        WorkbenchTheme.borderNS.setFill()
                        NSRect(x: x, y: rect.maxY, width: rect.width, height: 0.5).fill()
                    }
                }
                WorkbenchTheme.borderNS.setFill()
                NSRect(x: x, y: visible.minY, width: 0.5, height: headerHeight).fill()
            }
        }
        NSGraphicsContext.restoreGraphicsState()
        WorkbenchTheme.panelNS.setFill()
        NSRect(x: visible.minX, y: visible.minY + 22, width: gutterWidth, height: headerHeight - 22).fill()
        if frozenRowCount > 0 {
            for row in 1...frozenRowCount {
                let y = visible.minY + 22 + CGFloat(row - 1) * rowHeight
                text(String(row), rect: NSRect(x: visible.minX + actionWidth + 10, y: y, width: 38, height: rowHeight), color: WorkbenchTheme.mutedNS)
                if grid.changedRows.contains(row) { diffColor.setFill(); NSRect(x: visible.minX + actionWidth + 4, y: y + 5, width: 5, height: 6).fill() }
            }
        }
        if reviewLayout {
            text(old ? "" : "操作", rect: NSRect(x: visible.minX, y: visible.minY, width: actionWidth, height: 22), color: WorkbenchTheme.mutedNS)
            WorkbenchTheme.borderNS.setFill()
            NSRect(x: visible.minX + actionWidth, y: visible.minY, width: 1, height: visible.height).fill()
        }
        // Paint column A last so it also stays fixed at the frozen-row intersection.
        if grid.columns > 0 {
            let x = visible.minX + gutterWidth, width = columnWidth(0)
            NSGraphicsContext.saveGraphicsState()
            NSBezierPath(rect: NSRect(x: x, y: visible.minY, width: width, height: visible.height)).addClip()
            WorkbenchTheme.canvasNS.setFill()
            NSRect(x: x, y: visible.minY, width: width, height: visible.height).fill()
            func drawKey(_ row: Int, y: CGFloat, bold: Bool = false) {
                let address = "A" + String(row), cell = grid.cells[address]
                let rect = NSRect(x: x, y: y, width: width, height: rowHeight)
                if grid.changedRows.contains(row) { ComparisonAppearance.band.setFill(); rect.fill() }
                if cell?.changed == true { ComparisonAppearance.cellBackground(cell, old: old).setFill(); rect.fill() }
                cellText(cell, rect: rect, bold: bold)
                if selection == address {
                    WorkbenchTheme.accentNS.setStroke()
                    let border = NSBezierPath(rect: rect.insetBy(dx: 0.7, dy: 0.7)); border.lineWidth = 1.5; border.stroke()
                }
                WorkbenchTheme.borderNS.setFill()
                NSRect(x: x, y: rect.maxY, width: width, height: 0.5).fill()
            }
            if firstRow <= lastRow {
                for index in firstRow...lastRow { drawKey(rows[index], y: headerHeight + CGFloat(index) * rowHeight) }
            }
            WorkbenchTheme.canvasNS.setFill()
            NSRect(x: x, y: visible.minY, width: width, height: headerHeight).fill()
            WorkbenchTheme.panelNS.setFill()
            NSRect(x: x, y: visible.minY, width: width, height: 22).fill()
            text("A", rect: NSRect(x: x, y: visible.minY, width: width, height: 22), color: WorkbenchTheme.mutedNS)
            if frozenRowCount > 0 {
                for row in 1...frozenRowCount { drawKey(row, y: visible.minY + 22 + CGFloat(row - 1) * rowHeight, bold: row == 1) }
            }
            NSGraphicsContext.restoreGraphicsState()
            WorkbenchTheme.mutedNS.setFill()
            NSRect(x: visible.minX + frozenWidth, y: visible.minY, width: 1, height: visible.height).fill()
        }
        WorkbenchTheme.mutedNS.setFill()
        NSRect(x: visible.minX, y: visible.minY + headerHeight, width: visible.width, height: 1).fill()
    }
    override func mouseDown(with event: NSEvent) {
        dismissExplanation()
        let point = convert(event.locationInWindow, from: nil)
        guard point.y >= visibleRect.minY + 22, point.x > visibleRect.minX + gutterWidth else { return }
        let col = point.x < visibleRect.minX + frozenWidth ? 0 : columnAt(point.x)
        guard col >= 0, col < grid.columns else { return }
        let row: Int
        let y: CGFloat
        if point.y < visibleRect.minY + headerHeight {
            row = Int((point.y - visibleRect.minY - 22) / rowHeight) + 1
            guard row <= frozenRowCount else { return }
            y = visibleRect.minY + 22 + CGFloat(row - 1) * rowHeight
        } else {
            let index = Int((point.y - headerHeight) / rowHeight)
            guard rows.indices.contains(index) else { return }
            row = rows[index]
            y = headerHeight + CGFloat(index) * rowHeight
        }
        let address = SheetGrid.letter(col) + String(row)
        clicked?(address)
        showExplanation(address: address, rect: NSRect(x: col == 0 ? visibleRect.minX + gutterWidth : max(columnX(col), visibleRect.minX + frozenWidth), y: y, width: columnWidth(col), height: rowHeight))
    }
}

private struct WorkbookCellExplanation: View {
    let address: String
    let reason: String
    let tone: WorkbookDifference.ExplanationTone
    let left: WorkbookCell?
    let right: WorkbookCell?
    let close: () -> Void
    private var accent: Color {
        switch tone {
        case .red: Color(nsColor: ComparisonAppearance.modified)
        case .green: Color(nsColor: ComparisonAppearance.added)
        case .neutral: WorkbenchTheme.muted
        }
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack { Text("\(address) · 变更原因").font(.headline); Spacer(); WorkbenchCloseButton(action: close) }.padding(12)
            Divider()
            ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(reason).foregroundStyle(accent)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                    .background(accent.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
                Divider()
                value("左侧", cell: left)
                value("右侧", cell: right)
            }.textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }
        }.frame(width: 380, height: 300).workbenchStyle()
    }
    private func value(_ title: String, cell: WorkbookCell?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(WorkbenchTheme.muted)
            Text(cell?.display ?? "（空）").font(.system(size: 12, design: .monospaced)).foregroundStyle(accent).fixedSize(horizontal: false, vertical: true)
            if let cell { Text("类型：\(cell.type)").font(.caption).foregroundStyle(WorkbenchTheme.muted) }
        }
    }
}
