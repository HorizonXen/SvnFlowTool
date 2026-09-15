import Foundation

/// Estimates one phase from completed files, never from a revision being started.
public struct FileProgressEstimate: Sendable {
    public private(set) var total = 0
    public private(set) var completed = 0
    private var baselineCount = 0
    private var baselineTime: Date?
    private var lastCompletion: Date?

    public init() {}

    public mutating func record(completed count: Int, total: Int, at now: Date) {
        let total = max(0, total)
        let count = min(max(0, count), total)
        if baselineTime == nil || total != self.total || count < completed {
            baselineTime = now
            baselineCount = count
            lastCompletion = nil
        } else if count > completed {
            lastCompletion = now
        }
        self.total = total
        self.completed = count
    }

    public func remainingLabel(at now: Date) -> String {
        guard total > 0 else { return "预计剩余：总量确定后估算" }
        guard completed < total else { return "文件已处理完，正在收尾" }
        guard let baselineTime, let lastCompletion,
              completed > baselineCount else { return "预计剩余：正在估算" }
        let duration = lastCompletion.timeIntervalSince(baselineTime)
        guard duration >= 1 else { return "预计剩余：正在估算" }
        let average = duration / Double(completed - baselineCount)
        let age = max(0, now.timeIntervalSince(lastCompletion))
        let remaining = average * Double(total - completed)
        guard age < max(30, min(average * 3, remaining)) else {
            return "当前文件耗时较长，正在重新估算"
        }
        let seconds = max(10, remaining - age)
        if seconds < 60 { return "预计剩余约 \(Int(ceil(seconds / 10)) * 10) 秒" }
        if seconds < 3600 { return "预计剩余约 \(Int(ceil(seconds / 60))) 分钟" }
        return "预计剩余约 \(Int(ceil(seconds / 3600))) 小时"
    }
}
