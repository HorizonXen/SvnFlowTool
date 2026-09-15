import Foundation

public struct ComparisonFieldChange: Sendable {
    public let name: String
    public let oldValue: String
    public let newValue: String
    let oldRange: NSRange
    let newRange: NSRange
}

/// A conservative reader for scalar fields in generated, single-line Lua tables.
/// Quoted text is one token; long literals and ambiguous duplicate names fall back
/// to the ordinary character diff instead of inventing a field relationship.
enum ComparisonFields {
    private static let tokens = try! NSRegularExpression(pattern: #"--.*|\[=*\[|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_][A-Za-z_0-9]*|[-+]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)|\S"#)
    private static let identifier = try! NSRegularExpression(pattern: #"^[A-Za-z_][A-Za-z_0-9]*$"#)
    private static let scalar = try! NSRegularExpression(pattern: #"^(?:true|false|nil|[-+]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')$"#)
    private struct Field { let name: String; let value: String; let range: NSRange }
    private static func fields(_ text: String) -> [Field] {
        let ns = text as NSString
        let matches = tokens.matches(in: text, range: NSRange(location: 0, length: ns.length))
        let values = matches.map { ns.substring(with: $0.range) }
        guard values.contains("{"), values.contains("}"), values.count >= 4 else { return [] }
        var result: [Field] = []
        for i in values.indices {
            let value = values[i]
            if value.hasPrefix("--") { break }
            if value.hasPrefix("["), value.hasSuffix("["), value.count >= 2 { return [] }
            guard i > 0, i + 3 < values.count, ["{", ",", ";"].contains(values[i - 1]),
                  identifier.firstMatch(in: value, range: NSRange(location: 0, length: value.utf16.count)) != nil,
                  values[i + 1] == "=", [",", "}", ";"].contains(values[i + 3]) else { continue }
            let literal = values[i + 2]
            guard scalar.firstMatch(in: literal, range: NSRange(location: 0, length: literal.utf16.count)) != nil else { continue }
            result.append(Field(name: value, value: literal, range: matches[i + 2].range))
        }
        let counts = Dictionary(grouping: result, by: \.name)
        return result.filter { counts[$0.name]?.count == 1 }
    }
    static func changes(old: String, new: String) -> [ComparisonFieldChange] {
        let a = fields(old), b = Dictionary(uniqueKeysWithValues: fields(new).map { ($0.name, $0) })
        return a.compactMap { field in
            guard let other = b[field.name], field.value != other.value else { return nil }
            return ComparisonFieldChange(name: field.name, oldValue: field.value, newValue: other.value, oldRange: field.range, newRange: other.range)
        }
    }
    static func merging(_ ranges: [NSRange], with values: [NSRange]) -> [NSRange] {
        var result: [NSRange] = []
        for range in (ranges + values).sorted(by: { $0.location < $1.location }) {
            if let last = result.last, NSMaxRange(last) >= range.location {
                result[result.count - 1] = NSUnionRange(last, range)
            } else { result.append(range) }
        }
        return result
    }
}
