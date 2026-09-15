import Foundation
import SVNCore

struct MergeEndpointDisplay: Equatable, Sendable {
    static let sourceID = UUID(uuidString: "39AF147E-C164-4DD0-A66A-000000000001")!
    static let targetID = UUID(uuidString: "39AF147E-C164-4DD0-A66A-000000000002")!

    var sourcePath: String
    var targetPath: String

    var sourceName: String { MergeEndpoints.displayName(for: sourcePath, fallback: "源目录") }
    var targetName: String { MergeEndpoints.displayName(for: targetPath, fallback: "目标目录") }
    var direction: String { MergeEndpoints.direction(sourcePath: sourcePath, targetPath: targetPath) }
    var isComplete: Bool { !sourcePath.isEmpty && !targetPath.isEmpty }

    static func current(defaults: UserDefaults = .standard) -> Self {
        guard let data = defaults.data(forKey: "SvnFlow.fixedCopies.v1"),
              let copies = try? JSONDecoder().decode([WorkingCopy].self, from: data) else {
            return Self(sourcePath: "", targetPath: "")
        }
        return Self(
            sourcePath: copies.first(where: { $0.id == sourceID })?.path ?? "",
            targetPath: copies.first(where: { $0.id == targetID })?.path ?? ""
        )
    }
}

extension WorkingCopy {
    var pathDisplayName: String { MergeEndpoints.displayName(for: path, fallback: name) }
}
