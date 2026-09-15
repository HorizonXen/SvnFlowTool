import Foundation

/// Ignore only indentation outside Lua strings and long comments, never their content.
enum LuaIndentation {
    static func keys(_ lines: [String]) -> [String] { scan(lines).map { $0.0 } }
    static func alignmentKeys(_ lines: [String]) -> [String] {
        var path: [String] = []
        let field = try! NSRegularExpression(pattern: #"^(\[[^\]]+\]|[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$"#)
        return scan(lines).map { value, code in
            guard code else { return "literal:" + value }
            let text = value.trimmingCharacters(in: .whitespaces)
            let context = path.joined(separator: "/")
            if text == "}" || text == "}," || text == "};" {
                if !path.isEmpty { path.removeLast() }
                return context + "/close"
            }
            let ns = text as NSString
            if let match = field.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) {
                let name = ns.substring(with: match.range(at: 1))
                let tail = ns.substring(with: match.range(at: 2))
                if tail == "{" { path.append(name); return context + "/open:" + name }
                // Generated tables keep the complete record on one line. Its key,
                // not its values, identifies the corresponding row in the other version.
                if tail.hasPrefix("{"), tail.hasSuffix("}") || tail.hasSuffix("},") || tail.hasSuffix("};") {
                    return context + "/field:" + name
                }
                if !tail.contains("{") && !tail.contains("}") { return context + "/field:" + name }
            }
            if text == "return {" || text.hasSuffix("= {") || text.hasSuffix("={") {
                path.append("root"); return context + "/root"
            }
            return context + "/text:" + value
        }
    }
    private static func scan(_ lines: [String]) -> [(String, Bool)] {
        var longEnd: String? = nil
        var quote: Character? = nil
        return lines.map { line in
            let code = longEnd == nil && quote == nil
            let key = code ? String(line.drop(while: { $0 == " " || $0 == "\t" })) : line
            var i = line.startIndex
            while i < line.endIndex {
                let tail = line[i...]
                if let end = longEnd {
                    if tail.hasPrefix(end) { i = line.index(i, offsetBy: end.count); longEnd = nil }
                    else { i = line.index(after: i) }
                } else if let q = quote {
                    if line[i] == "\\" {
                        i = line.index(after: i)
                        if i < line.endIndex { i = line.index(after: i) }
                    } else { if line[i] == q { quote = nil }; i = line.index(after: i) }
                } else {
                    let comment = tail.hasPrefix("--")
                    let start = comment ? line.index(i, offsetBy: 2) : i
                    var end = start
                    if end < line.endIndex, line[end] == "[" {
                        end = line.index(after: end)
                        var equals = ""
                        while end < line.endIndex, line[end] == "=" { equals += "="; end = line.index(after: end) }
                        if end < line.endIndex, line[end] == "[" {
                            longEnd = "]" + equals + "]"; i = line.index(after: end); continue
                        }
                    }
                    if comment { break }
                    if line[i] == "\"" || line[i] == "'" { quote = line[i] }
                    i = line.index(after: i)
                }
            }
            return (key, code)
        }
    }
}
