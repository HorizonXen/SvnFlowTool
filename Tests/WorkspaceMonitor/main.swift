import Foundation
import CoreServices

@main struct MonitorChecks {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("SvnFlowMonitor-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        var paths = Set<String>()
        var monitor: WorkspaceMonitor? = WorkspaceMonitor(root: root.path, since: FSEventsGetCurrentEventId()) { events in
            for event in events { paths.insert(event.0) }
        }
        precondition(monitor?.active == true)
        for i in 0..<200 { try Data("event".utf8).write(to: root.appendingPathComponent("文件 (\(i)).txt")) }
        for _ in 0..<40 {
            if paths.contains(where: { $0.contains("文件 (") }) { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        precondition(paths.contains(where: { $0.contains("文件 (") }), "No UTF-8 file events delivered")
        monitor?.stop(); monitor = nil
        let count = paths.count
        for i in 0..<40 {
            var transient: WorkspaceMonitor? = WorkspaceMonitor(root: root.path, since: FSEventsGetCurrentEventId()) { _ in preconditionFailure("Stopped monitor delivered events") }
            try Data().write(to: root.appendingPathComponent("restart-\(i)"))
            if i % 2 == 0 { transient?.stop() }
            transient = nil
        }
        try await Task.sleep(for: .seconds(2))
        precondition(paths.count == count)
        print("PASS: Unicode event burst, 40 monitor stop/deallocation cycles, no late callbacks")
    }
}
