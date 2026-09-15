import Foundation

public struct ComparisonRow: Sendable {
    public let oldNumber: Int?
    public let newNumber: Int?
    public let oldText: String
    public let newText: String
    var equivalent = false
    var ignoresLeadingWhitespace = false
    public var inline: InlineComparison { InlineComparison(old: oldText, new: newText, ignoresLeadingWhitespace: ignoresLeadingWhitespace) }
    public var fieldChanges: [ComparisonFieldChange] { ComparisonFields.changes(old: oldText, new: newText) }
    public var changed: Bool { oldNumber == nil || newNumber == nil || (!equivalent && oldText != newText) }
}
public struct FileComparison: Sendable {
    private let originalOld: String
    private let originalNew: String
    public let ignoresIndentation: Bool
    public let expandsLua: Bool
    public let luaLayoutUnavailable: Bool
    public var formattingOnly: Bool { !identical && !lineEndingChange && !rows.contains(where: \.changed) }
    public func ignoringIndentation(_ enabled: Bool) -> FileComparison {
        FileComparison(old: originalOld, new: originalNew, baseLabel: baseLabel, ignoresIndentation: enabled, expandsLua: expandsLua)
    }
    public func expandingLua(_ enabled: Bool) -> FileComparison {
        FileComparison(old: originalOld, new: originalNew, baseLabel: baseLabel, ignoresIndentation: ignoresIndentation, expandsLua: enabled)
    }
    public let rows: [ComparisonRow]
    public let baseLabel: String
    public let identical: Bool
    public let lineEndingChange: Bool
    public let changeStarts: [Int]
    public let maximumLineLength: Int
    public static func align(old: String, new: String, ignoresIndentation: Bool = false) -> [ComparisonRow] {
        func lines(_ text: String) -> [String] {
            if text.isEmpty { return [] }
            var result = text.components(separatedBy: "\n")
            if result.last == "" { result.removeLast() }
            return result
        }
        let a = lines(old), b = lines(new)
        let ak = ignoresIndentation ? LuaIndentation.keys(a) : a
        let bk = ignoresIndentation ? LuaIndentation.keys(b) : b
        let aa = ignoresIndentation ? LuaIndentation.alignmentKeys(a) : ak
        let ba = ignoresIndentation ? LuaIndentation.alignmentKeys(b) : bk
        let differences = ba.difference(from: aa)
        var removed = Set<Int>(), inserted = Set<Int>()
        for change in differences {
            switch change { case .remove(let offset, _, _): removed.insert(offset); case .insert(let offset, _, _): inserted.insert(offset) }
        }
        var i = 0, j = 0, rows: [ComparisonRow] = []
        while i < a.count || j < b.count {
            if removed.contains(i) || inserted.contains(j) {
                let takeOld = i < a.count && removed.contains(i)
                let takeNew = j < b.count && inserted.contains(j) && (!ignoresIndentation || !takeOld || aa[i] == ba[j])
                rows.append(.init(oldNumber: takeOld ? i + 1 : nil, newNumber: takeNew ? j + 1 : nil, oldText: takeOld ? a[i] : "", newText: takeNew ? b[j] : ""))
                if takeOld { i += 1 }; if takeNew { j += 1 }
            } else {
                rows.append(.init(oldNumber: i < a.count ? i + 1 : nil, newNumber: j < b.count ? j + 1 : nil, oldText: i < a.count ? a[i] : "", newText: j < b.count ? b[j] : ""))
                i += 1; j += 1
            }
        }
        return rows.map { row in
            var result = row
            if let old = row.oldNumber, let new = row.newNumber { result.equivalent = ak[old - 1] == bk[new - 1]
                result.ignoresLeadingWhitespace = ignoresIndentation && ak[old - 1] == String(row.oldText.drop(while: { $0 == " " || $0 == "\t" })) && bk[new - 1] == String(row.newText.drop(while: { $0 == " " || $0 == "\t" })) }
            return result
        }
    }
    public init(old: String, new: String, baseLabel: String, ignoresIndentation: Bool = false, expandsLua: Bool = false) {
        originalOld = old; originalNew = new; self.ignoresIndentation = ignoresIndentation
        self.expandsLua = expandsLua
        let a = expandsLua ? LuaComparisonLayout.expand(old) : nil
        let b = expandsLua ? LuaComparisonLayout.expand(new) : nil
        luaLayoutUnavailable = expandsLua && (a == nil || b == nil)
        let formatted = expandsLua && !luaLayoutUnavailable
        var rows = Self.align(old: formatted ? a!.text : old, new: formatted ? b!.text : new, ignoresIndentation: ignoresIndentation)
        if formatted {
            rows = rows.map { row in
                var mapped = ComparisonRow(oldNumber: row.oldNumber.map { a!.sourceLines[$0 - 1] }, newNumber: row.newNumber.map { b!.sourceLines[$0 - 1] }, oldText: row.oldText, newText: row.newText)
                mapped.equivalent = row.equivalent; mapped.ignoresLeadingWhitespace = row.ignoresLeadingWhitespace
                return mapped
            }
        }
        self.rows = rows; self.baseLabel = baseLabel
        changeStarts = rows.indices.filter { rows[$0].changed && ($0 == 0 || !rows[$0 - 1].changed) }
        maximumLineLength = rows.reduce(0) { longest, row in
            func width(_ text: String) -> Int { text.reduce(0) { $0 + ($1 == "\t" ? 4 : 1) } }
            return max(longest, width(row.oldText), width(row.newText))
        }
        identical = old == new
        lineEndingChange = !identical && old.hasSuffix("\n") != new.hasSuffix("\n")
    }
}

/// UTF-16 ranges can be applied directly to attributed text, including Unicode.
public struct InlineComparison: Sendable {
    public let oldRanges: [NSRange]
    public let newRanges: [NSRange]
    public init(old: String, new: String, ignoresLeadingWhitespace: Bool = false) {
        if ignoresLeadingWhitespace {
            let a = String(old.drop(while: { $0 == " " || $0 == "\t" }))
            let b = String(new.drop(while: { $0 == " " || $0 == "\t" }))
            let inner = InlineComparison(old: a, new: b)
            oldRanges = inner.oldRanges.map { NSRange(location: $0.location + old.utf16.count - a.utf16.count, length: $0.length) }
            newRanges = inner.newRanges.map { NSRange(location: $0.location + new.utf16.count - b.utf16.count, length: $0.length) }
            return
        }
        let a = Array(old), b = Array(new)
        var prefix = 0, suffix = 0
        while prefix < min(a.count, b.count), a[prefix] == b[prefix] { prefix += 1 }
        while suffix < min(a.count, b.count) - prefix, a[a.count - suffix - 1] == b[b.count - suffix - 1] { suffix += 1 }
        let x = Array(a[prefix..<(a.count - suffix)]), y = Array(b[prefix..<(b.count - suffix)])
        var removed = Set<Int>(), inserted = Set<Int>()
        // Keep pathological, entirely rewritten generated lines bounded.
        if x.count > 2000 || y.count > 2000 {
            removed = Set(x.indices); inserted = Set(y.indices)
        } else {
            for change in y.difference(from: x) {
                switch change {
                case .remove(let offset, _, _): removed.insert(offset)
                case .insert(let offset, _, _): inserted.insert(offset)
                }
            }
        }
        func ranges(_ characters: [Character], changed: Set<Int>) -> [NSRange] {
            var result: [NSRange] = [], offset = 0
            for (index, character) in characters.enumerated() {
                let length = String(character).utf16.count
                if changed.contains(index - prefix) {
                    if let last = result.last, NSMaxRange(last) == offset {
                        result[result.count - 1].length += length
                    } else { result.append(NSRange(location: offset, length: length)) }
                }
                offset += length
            }
            return result
        }
        let fields = ComparisonFields.changes(old: old, new: new)
        oldRanges = ComparisonFields.merging(ranges(a, changed: removed), with: fields.map(\.oldRange))
        newRanges = ComparisonFields.merging(ranges(b, changed: inserted), with: fields.map(\.newRange))
    }
}

public enum ComparisonDisplayLine: Equatable, Sendable {
    case row(Int)
    case folded(Range<Int>)
}
extension FileComparison {
    /// mode: all, differences, or identical; expanded folds retain original row identity.
    public func displayLines(mode: Int, context: Int = 0, expanded: Set<Int> = []) -> [ComparisonDisplayLine] {
        var included = Set<Int>()
        for index in rows.indices {
            if mode == 0 || (mode == 1 ? rows[index].changed : !rows[index].changed) {
                for nearby in max(0, index - context)..<min(rows.count, index + context + 1) { included.insert(nearby) }
            }
        }
        var result: [ComparisonDisplayLine] = [], index = 0
        while index < rows.count {
            if included.contains(index) { result.append(.row(index)); index += 1; continue }
            let start = index
            while index < rows.count && !included.contains(index) { index += 1 }
            if expanded.contains(start) { result += (start..<index).map { .row($0) } }
            else { result.append(.folded(start..<index)) }
        }
        return result
    }
}
