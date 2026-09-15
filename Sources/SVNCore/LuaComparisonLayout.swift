import Foundation

/// A display-only lexer. Never evaluates Lua or writes the source file.
/// Expand keyed tables while keeping short value arrays together.
public enum LuaComparisonLayout {
    public struct Layout: Sendable {
        public let text: String
        public let sourceLines: [Int]
    }
    private struct Token { let text: String; let line: Int; let spaced: Bool }
    public static func expand(_ source: String) -> Layout? {
        guard source.utf8.count <= 2_000_000 else { return nil }
        let chars = Array(source)
        var tokens: [Token] = [], i = 0, line = 1
        while i < chars.count {
            let c = chars[i]
            if c.isWhitespace { if c == "\n" || c == "\r\n" { line += 1 }; i += 1; continue }
            let start = i, startLine = line
            let comment = c == "-" && i + 1 < chars.count && chars[i + 1] == "-"
            let bracketStart = comment ? i + 2 : i
            var longEnd: [Character]? = nil, contentStart = bracketStart
            if bracketStart < chars.count, chars[bracketStart] == "[" {
                var j = bracketStart + 1
                while j < chars.count && chars[j] == "=" { j += 1 }
                if j < chars.count && chars[j] == "[" {
                    longEnd = ["]"] + Array(repeating: "=", count: j - bracketStart - 1) + ["]"]
                    contentStart = j + 1
                }
            }
            if let end = longEnd {
                i = contentStart
                while i + end.count <= chars.count && Array(chars[i..<(i + end.count)]) != end { i += 1 }
                guard i + end.count <= chars.count else { return nil }
                i += end.count
            } else if comment {
                while i < chars.count && chars[i] != "\n" && chars[i] != "\r\n" { i += 1 }
            } else if c == "\"" || c == "'" {
                i += 1
                var closed = false
                while i < chars.count {
                    if chars[i] == "\\" { i += 2; continue }
                    if chars[i] == c { i += 1; closed = true; break }
                    i += 1
                }
                guard closed, i <= chars.count else { return nil }
            } else if c.isLetter || c.isNumber || c == "_" {
                i += 1
                while i < chars.count && (chars[i].isLetter || chars[i].isNumber || chars[i] == "_") { i += 1 }
            } else {
                let tail = String(chars[i..<min(chars.count, i + 3)])
                let op = ["...", "..", "==", "~=", "<=", ">=", "//", "<<", ">>", "::"].first { tail.hasPrefix($0) }
                i += op?.count ?? 1
            }
            let text = String(chars[start..<i])
            // Keep multiline literals/comments byte-for-byte in the ordinary viewer.
            guard !text.contains("\n"), !text.contains("\r") else { return nil }
            tokens.append(Token(text: text, line: startLine, spaced: start > 0 && chars[start - 1].isWhitespace))
        }
        var delimiters: [String] = []
        for token in tokens {
            if ["{", "[", "("].contains(token.text) { delimiters.append(token.text) }
            if let expected = ["}": "{", "]": "[", ")": "("][token.text] {
                guard delimiters.popLast() == expected else { return nil }
            }
        }
        guard delimiters.isEmpty else { return nil }
        var stack: [Int] = [], pairs: [Int: Int] = [:], keyed = Set<Int>()
        for index in tokens.indices {
            switch tokens[index].text {
            case "{": stack.append(index)
            case "}":
                guard let open = stack.popLast() else { return nil }
                pairs[open] = index
            case "=": if let open = stack.last { keyed.insert(open) }
            default: break
            }
        }
        guard stack.isEmpty else { return nil }
        // Long arrays also expand so generated data does not remain a huge line.
        for (open, close) in pairs where close - open > 40 { keyed.insert(open) }
        var output: [String] = [], numbers: [Int] = [], buffer = "", bufferLine = 1
        var frames: [Bool] = [], indent = 0, previous: Token?
        func flush() {
            let value = buffer.trimmingCharacters(in: .whitespaces)
            if !value.isEmpty { output.append(String(repeating: "    ", count: min(indent, 32)) + value); numbers.append(bufferLine) }
            buffer = ""
        }
        func append(_ token: Token) {
            if buffer.isEmpty { bufferLine = token.line }
            if !buffer.isEmpty, buffer.last?.isWhitespace != true, token.spaced { buffer += " " }
            buffer += token.text
        }
        for index in tokens.indices {
            let token = tokens[index]
            if let previous, token.line != previous.line { flush() }
            switch token.text {
            case "{":
                let expanded = keyed.contains(index)
                append(token); frames.append(expanded)
                if expanded { flush(); indent += 1 }
            case "}":
                let expanded = frames.popLast() ?? false
                if expanded { flush(); indent = max(0, indent - 1) }
                append(token)
            case ",", ";":
                append(token)
                if frames.last == true { flush() } else { buffer += " " }
            case "=":
                buffer = buffer.trimmingCharacters(in: .whitespaces) + " = "
                if bufferLine < 1 { bufferLine = token.line }
            default:
                append(token)
                if token.text.hasPrefix("--") { flush() }
            }
            previous = token
        }
        flush()
        return Layout(text: output.isEmpty ? "" : output.joined(separator: "\n") + (source.hasSuffix("\n") ? "\n" : ""), sourceLines: numbers)
    }
}
