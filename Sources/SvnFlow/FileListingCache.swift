import Foundation
import SVNCore

@MainActor final class FileListingCache {
    struct Key: Equatable {
        let version: Int
        let language: String
        let directory: String
        let recursive: Bool
        let unchanged: Bool
        let unversioned: Bool
        let filter: String
    }
    typealias Result = WorkspaceListingIndex.Listing
    private var cachedRows: [WorkspaceTableRow]?
    private var rowsBranch = ""
    func rows(branch: String, build: () -> [WorkspaceTableRow]) -> [WorkspaceTableRow] {
        if let cachedRows, rowsBranch == branch { return cachedRows }
        let updated = build(); cachedRows = updated; rowsBranch = branch; return updated
    }
    private var key: Key?
    private var result: Result?
    func resolve(version: Int, directory: String, recursive: Bool, unchanged: Bool, unversioned: Bool, filter: String, ignored: Set<String>, index: WorkspaceListingIndex) -> Result {
        let next = Key(version: version, language: InterfaceLanguage.code, directory: directory, recursive: recursive, unchanged: unchanged, unversioned: unversioned, filter: filter)
        if key == next, let result { return result }
        let updated = index.list(directory: directory, recursive: recursive, unchanged: unchanged, unversioned: unversioned, filter: filter, ignored: ignored)
        result = updated; key = next; cachedRows = nil
        return updated
    }
}
