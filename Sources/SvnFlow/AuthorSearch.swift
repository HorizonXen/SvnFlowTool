import Foundation

/// Filters candidates only; callers retain the original account for selection.
enum AuthorSearch {
    static func filter(_ authors: [String], query: String) -> [String] {
        let keyword = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !keyword.isEmpty else { return authors }
        return authors.filter {
            $0.range(of: keyword, options: [.caseInsensitive, .diacriticInsensitive],
                     locale: Locale(identifier: "en_US_POSIX")) != nil
        }
    }
}
