import AppKit
import SwiftUI
import SVNCore

@MainActor func comparisonAttributedText(_ text: String, ranges: [NSRange], old: Bool, addition: Bool = false, fontSize: CGFloat = 11) -> NSAttributedString {
    let value = NSMutableAttributedString(string: text, attributes: [
        .font: NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular),
        .foregroundColor: WorkbenchTheme.textNS
    ])
    for range in ranges {
        value.addAttributes([.foregroundColor: old ? ComparisonAppearance.removed : (addition ? ComparisonAppearance.added : ComparisonAppearance.modified)], range: range)
        value.addAttribute(.backgroundColor, value: ComparisonAppearance.emphasis, range: range)
    }
    return value
}

/// Paint the whole aligned line, including the empty side of insertions/deletions.
@MainActor final class DiffTextView: NSTextView {
    var rowHeight: CGFloat = 19
    var rowKinds: [Int] = [] // 0 unchanged, 1 changed, 2 alignment gap, 3 folded
    override func drawBackground(in rect: NSRect) {
        super.drawBackground(in: rect)
        let first = max(0, Int((rect.minY - 4) / rowHeight))
        let last = min(rowKinds.count - 1, Int((rect.maxY - 4) / rowHeight))
        guard first <= last else { return }
        for index in first...last where rowKinds[index] != 0 {
            let band = NSRect(x: 0, y: 4 + CGFloat(index) * rowHeight, width: bounds.width, height: rowHeight)
            if rowKinds[index] == 1 {
                ComparisonAppearance.band.setFill(); band.fill()
                ComparisonAppearance.modified.setFill()
                NSRect(x: visibleRect.minX, y: band.minY, width: 3, height: band.height).fill()
            } else if rowKinds[index] == 2 {
                WorkbenchTheme.panelNS.setFill(); band.fill()
            } else { WorkbenchTheme.panelNS.setFill(); band.fill() }
        }
    }
}

struct TextComparisonPanes: NSViewRepresentable {
    let comparison: FileComparison
    let lines: [ComparisonDisplayLine]
    var isLua = false
    var oldAnnotations: [String] = []
    var newAnnotations: [String] = []
    let generation: Int
    let navigation: Int
    @Binding var selection: Int?
    let expand: (Int) -> Void
    func makeNSView(context: Context) -> TwinTextComparisonView { TwinTextComparisonView() }
    func updateNSView(_ view: TwinTextComparisonView, context: Context) {
        view.selected = { selection = $0 }
        view.expand = expand
        view.configure(self)
    }
}

@MainActor final class TwinTextComparisonView: NSView, NSTextViewDelegate {
    private let left = DirectionalScrollView(), right = DirectionalScrollView()
    private let a = DiffTextView(), b = DiffTextView()
    private var lines: [ComparisonDisplayLine] = []
    private var oldOffsets: [Int] = [], newOffsets: [Int] = []
    private var generation = -1, navigation = -1
    private var syncing = false, configuring = false
    private var documentWidth: CGFloat = 0
    private var rowHeight: CGFloat = 19
    private var fontSize: CGFloat = 11
    var selected: ((Int) -> Void)?
    var expand: ((Int) -> Void)?
    override init(frame: NSRect) {
        super.init(frame: frame)
        for (scroll, text) in [(left, a), (right, b)] {
            scroll.documentView = text
            scroll.backgroundColor = WorkbenchTheme.canvasNS
            text.backgroundColor = WorkbenchTheme.canvasNS
            text.insertionPointColor = WorkbenchTheme.accentNS
            text.selectedTextAttributes = [.backgroundColor: WorkbenchTheme.selectionNS, .foregroundColor: WorkbenchTheme.textNS]
            text.linkTextAttributes = [.foregroundColor: WorkbenchTheme.accentNS, .underlineStyle: NSUnderlineStyle.single.rawValue]
            scroll.hasHorizontalScroller = true; scroll.hasVerticalScroller = true
            // Reserve a permanent scrollbar track even when macOS prefers overlay scrollers.
            scroll.scrollerStyle = .legacy
            scroll.autohidesScrollers = false; scroll.borderType = .noBorder
            scroll.contentView.postsBoundsChangedNotifications = true
            text.isEditable = false; text.isSelectable = true; text.isRichText = true
            // Both document frames are owned here, not resized independently by TextKit.
            text.isHorizontallyResizable = true; text.isVerticallyResizable = true
            text.autoresizingMask = []
            text.textContainer?.widthTracksTextView = false
            text.textContainerInset = NSSize(width: 5, height: 4)
            text.layoutManager?.allowsNonContiguousLayout = true
            text.delegate = self
            text.setAccessibilityLabel(text === a ? "前一版本" : "所选版本")
            NotificationCenter.default.addObserver(self, selector: #selector(scrolled(_:)), name: NSView.boundsDidChangeNotification, object: scroll.contentView)
            addSubview(scroll)
        }
    }
    required init?(coder: NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        let width = max(0, (bounds.width - 1) / 2)
        left.frame = NSRect(x: 0, y: 0, width: width, height: bounds.height)
        right.frame = NSRect(x: width + 1, y: 0, width: width, height: bounds.height)
        resizeDocuments()
    }
    override func draw(_ dirtyRect: NSRect) { WorkbenchTheme.borderNS.setFill(); bounds.fill() }
    private func resizeDocuments() {
        let width = max(documentWidth, left.contentSize.width)
        let height = max(CGFloat(lines.count) * rowHeight + 12, left.contentSize.height)
        for text in [a, b] {
            text.textContainer?.containerSize = NSSize(width: width - 10, height: CGFloat.greatestFiniteMagnitude)
            text.minSize = NSSize(width: width, height: height)
            text.maxSize = NSSize(width: width, height: height)
            text.frame.size = NSSize(width: width, height: height)
            if let container = text.textContainer { text.layoutManager?.ensureLayout(for: container) }
        }
    }
    func configure(_ input: TextComparisonPanes) {
        rowHeight = input.isLua ? 23 : 19; fontSize = input.isLua ? 13 : 11
        a.rowHeight = rowHeight; b.rowHeight = rowHeight
        configuring = true; syncing = true
        defer {
            right.contentView.scroll(to: left.contentView.bounds.origin)
            right.reflectScrolledClipView(right.contentView)
            syncing = false; configuring = false
        }
        let rebuilt = generation != input.generation || lines != input.lines
        if rebuilt {
            generation = input.generation; lines = input.lines
            let old = NSMutableAttributedString(), new = NSMutableAttributedString()
            oldOffsets = []; newOffsets = []
            a.rowKinds = []; b.rowKinds = []
            var longest: CGFloat = 0
            let paragraph = NSMutableParagraphStyle()
            paragraph.minimumLineHeight = rowHeight; paragraph.maximumLineHeight = rowHeight
            paragraph.lineBreakMode = .byClipping
            paragraph.defaultTabInterval = 26.4
            paragraph.tabStops = []
            for line in lines {
                oldOffsets.append(old.length); newOffsets.append(new.length)
                switch line {
                case .folded(let range):
                    a.rowKinds.append(3); b.rowKinds.append(3)
                    let label = T("⊞  Expand {0} unchanged lines", "⊞  展开未变更的 {0} 行", range.count) + "\n"
                    let fold = NSAttributedString(string: label, attributes: [.font: NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular), .foregroundColor: WorkbenchTheme.mutedNS, .backgroundColor: WorkbenchTheme.panelNS, .link: "fold:\(range.lowerBound)"])
                    old.append(fold); new.append(fold)
                    longest = max(longest, fold.size().width)
                case .row(let index):
                    let row = input.comparison.rows[index]
                    a.rowKinds.append(row.changed ? (row.oldNumber == nil ? 2 : 1) : 0)
                    b.rowKinds.append(row.changed ? (row.newNumber == nil ? 2 : 1) : 0)
                    let diff = row.changed ? row.inline : InlineComparison(old: "", new: "")
                    for (output, text, number, ranges, isOld) in [(old, row.oldText, row.oldNumber, diff.oldRanges, true), (new, row.newText, row.newNumber, diff.newRanges, false)] {
                        let marker = row.changed && number != nil ? (row.oldNumber != nil && row.newNumber != nil ? "~" : (isOld ? "−" : "+")) : " "
                        let annotations = isOld ? input.oldAnnotations : input.newAnnotations
                        let source = number.flatMap { annotations.indices.contains($0 - 1) ? annotations[$0 - 1] : nil }
                        let annotation = source.map { $0 + "  │  " } ?? ""
                        let prefix = annotation + String(format: "%6@ %@ ", number.map(String.init) ?? "", marker)
                        let value = NSMutableAttributedString(string: prefix, attributes: [.font: NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular), .foregroundColor: WorkbenchTheme.mutedNS])
                        value.append(comparisonAttributedText(text, ranges: ranges, old: isOld, addition: diff.oldRanges.isEmpty, fontSize: fontSize))
                        value.append(NSAttributedString(string: "\n"))
                        value.addAttribute(.paragraphStyle, value: paragraph, range: NSRange(location: 0, length: value.length))
                        longest = max(longest, value.size().width)
                        output.append(value)
                    }
                }
            }
            for value in [old, new] { value.addAttribute(.paragraphStyle, value: paragraph, range: NSRange(location: 0, length: value.length)) }
            documentWidth = longest + 40
            a.textStorage?.setAttributedString(old); b.textStorage?.setAttributedString(new)
            resizeDocuments()
            a.needsDisplay = true; b.needsDisplay = true
        }
        if rebuilt || navigation != input.navigation {
            navigation = input.navigation
            if let selected = input.selection, let position = lines.firstIndex(of: .row(selected)) {
                let row = input.comparison.rows[selected]
                let inline = row.inline
                let offset = inline.oldRanges.first?.location ?? inline.newRanges.first?.location ?? 0
                let content = inline.oldRanges.isEmpty ? row.newText : row.oldText
                let prefix = (content as NSString).substring(to: min(offset, (content as NSString).length))
                let x = (prefix as NSString).size(withAttributes: [.font: NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular)]).width + 60
                let point = NSPoint(x: max(0, x - left.contentSize.width / 3), y: max(0, CGFloat(position) * rowHeight - rowHeight * 2))
                // Keep selection a caret so it doesn't obscure the edit colors.
                a.setSelectedRange(NSRange(location: oldOffsets[position], length: 0))
                b.setSelectedRange(NSRange(location: newOffsets[position], length: 0))
                left.contentView.scroll(to: point); left.reflectScrolledClipView(left.contentView)
            } else if rebuilt {
                left.contentView.scroll(to: .zero); left.reflectScrolledClipView(left.contentView)
            }
        }
    }
    @objc private func scrolled(_ notification: Notification) {
        guard !syncing, let clip = notification.object as? NSClipView else { return }
        syncing = true; defer { syncing = false }
        let target = clip === left.contentView ? right : left
        target.contentView.scroll(to: clip.bounds.origin)
        target.reflectScrolledClipView(target.contentView)
    }
    func textViewDidChangeSelection(_ notification: Notification) {
        guard !configuring, let text = notification.object as? NSTextView else { return }
        let offsets = text === a ? oldOffsets : newOffsets
        guard let index = offsets.lastIndex(where: { $0 <= text.selectedRange().location }), lines.indices.contains(index), case .row(let row) = lines[index] else { return }
        selected?(row)
    }
    func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
        let value = (link as? URL)?.absoluteString ?? (link as? String ?? "")
        guard value.hasPrefix("fold:"), let start = Int(value.dropFirst(5)) else { return false }
        expand?(start); return true
    }
}
