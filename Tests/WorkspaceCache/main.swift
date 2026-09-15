import Foundation
import CoreServices
import SVNCore
@MainActor final class Events { var paths: [String] = [] }
@main struct CacheChecks {
    @MainActor static func main() async throws {
        let id = UUID(), root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).resolvingSymlinksInPath()
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let status = try WorkingCopyStatus.parse(Data("<status><target path='x'><entry path='\(root.path)/a.txt'><wc-status item='modified' props='none' revision='17'/></entry></target></status>".utf8), root: root.path)
        let snapshot = WorkspaceDiskSnapshot(root: root.path, statuses: status, entries: WorkspaceCatalog.build(root: root.path, status: status), eventID: 123, adminStamp: "test")
        await WorkspaceSnapshotStore.shared.write(snapshot, id: id)
        let read = await WorkspaceSnapshotStore.shared.read(id, root: root.path)
        precondition(read?.statuses == status && read?.eventID == 123 && read?.entries == snapshot.entries)
        let wrong = await WorkspaceSnapshotStore.shared.read(id, root: root.path + "-other")
        precondition(wrong == nil)
        let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("SvnFlow/Workspace/\(id.uuidString).plist")
        try Data("broken".utf8).write(to: cache)
        let broken = await WorkspaceSnapshotStore.shared.read(id, root: root.path)
        precondition(broken == nil)
        try FileManager.default.removeItem(at: cache)
        print("PASS cache round-trip, root identity and corrupted-cache fallback")
        let events = Events(), checkpoint = FSEventsGetCurrentEventId()
        let monitor = WorkspaceMonitor(root: root.path, since: checkpoint) { events.paths += $0.map(\.0) }
        try Data("created".utf8).write(to: root.appendingPathComponent("live.txt"))
        try await Task.sleep(for: .seconds(4))
        precondition(events.paths.contains { $0.hasSuffix("live.txt") })
        monitor.stop()
        try Data("offline".utf8).write(to: root.appendingPathComponent("offline.txt"))
        try await Task.sleep(for: .seconds(2))
        let replay = Events()
        let restored = WorkspaceMonitor(root: root.path, since: checkpoint) { replay.paths += $0.map(\.0) }
        try await Task.sleep(for: .seconds(4))
        precondition(replay.paths.contains { $0.hasSuffix("offline.txt") })
        restored.stop()
        print("PASS live file events and offline history replay")
    }
}
