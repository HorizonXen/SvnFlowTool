import AppKit
import SwiftUI
import SVNCore

/// Version semantics are independent of the pane's screen position.
@MainActor enum ComparisonAppearance {
    static let band = WorkbenchTheme.rgb(0xEEF2F8)
    static let emphasis = WorkbenchTheme.rgb(0xFFF0CC)
    static let modified = WorkbenchTheme.warningNS
    static let added = WorkbenchTheme.successNS
    static let removed = WorkbenchTheme.dangerNS
    static let preservedFormulaBackground = WorkbenchTheme.rgb(0xE4F3E8)
    static let preservedFormulaText = WorkbenchTheme.rgb(0x21633B)

    static func preservesFormulaValue(_ cell: WorkbookDifference?, old: Bool) -> Bool {
        old && cell?.isValuePreservingFormulaConversion == true
    }

    static func cellBackground(_ cell: WorkbookDifference?, old: Bool) -> NSColor {
        preservesFormulaValue(cell, old: old) ? preservedFormulaBackground : emphasis
    }

    static func attributes(old: Bool, addition: Bool) -> [NSAttributedString.Key: Any] {
        var attributes: [NSAttributedString.Key: Any] = [
            .foregroundColor: old ? removed : (addition ? added : modified)
        ]
        if old {
            attributes[.strikethroughStyle] = NSUnderlineStyle.single.rawValue
            attributes[.strikethroughColor] = removed
        }
        return attributes
    }

    static func cellText(_ cell: WorkbookDifference?, old: Bool, formulas: Bool = false) -> NSAttributedString {
        let value = old ? cell?.old : cell?.new
        let string = formulas ? value?.display ?? "" : value?.value ?? ""
        guard let cell, cell.changed else { return NSAttributedString(string: string, attributes: [.foregroundColor: WorkbenchTheme.textNS]) }
        if preservesFormulaValue(cell, old: old) {
            return NSAttributedString(string: string, attributes: [.foregroundColor: preservedFormulaText])
        }
        let oldEmpty = cell.old == nil || (cell.old?.value.isEmpty == true && cell.old?.formula.isEmpty == true)
        return NSAttributedString(string: string, attributes: attributes(old: old, addition: oldEmpty))
    }
}

struct ComparisonLegend: View {
    var strikesOldValues = true
    var body: some View {
        HStack(spacing: 10) {
            Text("− 删除 / 旧值").strikethrough(strikesOldValues).foregroundStyle(Color(nsColor: ComparisonAppearance.removed))
            Text("~ 修改").foregroundStyle(Color(nsColor: ComparisonAppearance.modified))
            Text("+ 新增").foregroundStyle(Color(nsColor: ComparisonAppearance.added))
            Text("高亮标出改动").foregroundStyle(WorkbenchTheme.muted)
        }
    }
}
