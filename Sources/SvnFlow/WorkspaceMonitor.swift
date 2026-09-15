import Foundation
import CoreServices
import SVNCore

struct WorkspaceDiskSnapshot: Codable, Sendable {
    let root: String
    let statuses: [StatusItem]
    let entries: [WorkspaceEntry]
    let eventID: UInt64
    let adminStamp: String
}
actor WorkspaceSnapshotStore {
    static let shared = WorkspaceSnapshotStore()
    private func url(_ id: UUID) -> URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("SvnFlow/Workspace/\(id.uuidString).plist")
    }
    func read(_ id: UUID, root: String) -> WorkspaceDiskSnapshot? {
        guard let data = try? Data(contentsOf: url(id)), let value = try? PropertyListDecoder().decode(WorkspaceDiskSnapshot.self, from: data), value.root == root else { return nil }
        return value
    }
    func write(_ value: WorkspaceDiskSnapshot, id: UUID) {
        guard !Task.isCancelled else { return }
        let dest = url(id)
        do {
            try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            let encoder = PropertyListEncoder(); encoder.outputFormat = .binary
            try encoder.encode(value).write(to: dest, options: .atomic)
        } catch { /* A missing cache falls back to a fresh scan on next launch. */ }
    }
}
private final class WorkspaceEventSink {
    var receive: ([(String, UInt32)]) -> Void
    var active = true
    init(receive: @escaping ([(String, UInt32)]) -> Void) { self.receive = receive }
}
private final class WorkspaceEventStream {
    var ref: FSEventStreamRef?
    func stop() {
        if let ref { FSEventStreamStop(ref); FSEventStreamInvalidate(ref); FSEventStreamRelease(ref); self.ref = nil }
    }
    deinit { stop() }
}
@MainActor final class WorkspaceMonitor {
    private let handle = WorkspaceEventStream()
    private(set) var active = false
    private let sink: WorkspaceEventSink
    init(root: String, since: UInt64, receive: @escaping ([(String, UInt32)]) -> Void) {
        let sink = WorkspaceEventSink(receive: receive)
        self.sink = sink
        // The stream owns its callback context, independently of the monitor.
        var context = FSEventStreamContext(version: 0, info: Unmanaged.passUnretained(sink).toOpaque(), retain: { info in
            guard let info else { return nil }
            return UnsafeRawPointer(Unmanaged<WorkspaceEventSink>.fromOpaque(info).retain().toOpaque())
        }, release: { info in
            if let info { Unmanaged<WorkspaceEventSink>.fromOpaque(info).release() }
        }, copyDescription: nil)
        handle.ref = FSEventStreamCreate(nil, { _, info, count, paths, flags, _ in
            guard let info else { return }
            let sink = Unmanaged<WorkspaceEventSink>.fromOpaque(info).takeUnretainedValue()
            // Without UseCFTypes the API supplies char **. Copy within callback.
            let strings = paths.assumingMemoryBound(to: UnsafePointer<CChar>?.self)
            let events = (0..<count).compactMap { index -> (String, UInt32)? in
                guard let path = strings[index] else { return nil }
                return (String(cString: path), flags[index])
            }
            MainActor.assumeIsolated { if sink.active { sink.receive(events) } }
        }, &context, [root] as CFArray, since, 1.0, FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagWatchRoot))
        if let stream = handle.ref { FSEventStreamSetDispatchQueue(stream, .main); active = FSEventStreamStart(stream) }
    }
    func stop() { active = false; sink.active = false; sink.receive = { _ in }; handle.stop() }
    static func adminStamp(_ root: String) -> String {
        var folder = URL(fileURLWithPath: root)
        while folder.path != "/" {
            let admin = folder.appendingPathComponent(".svn")
            if FileManager.default.fileExists(atPath: admin.path) {
                return ["wc.db", "wc.db-wal"].map { name in
                    let attrs = try? FileManager.default.attributesOfItem(atPath: admin.appendingPathComponent(name).path)
                    return "\((attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0):\(attrs?[.size] ?? ""):\(attrs?[.systemFileNumber] ?? "")"
                }.joined(separator: "|")
            }
            folder.deleteLastPathComponent()
        }
        return "missing"
    }
}
