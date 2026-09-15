/// Presentation groups; repository verification and write eligibility remain independent.
public enum SyncStatusCategory: String, CaseIterable {
    case pending = "待处理", review = "待确认", attention = "需处理", completed = "已完成", ignored = "已忽略"

    public static func classify(_ state: String, ignored: Bool = false, processing: Bool = false) -> Self {
        if ignored { return .ignored }
        if processing { return .pending }
        switch state {
        case "可确认", "待核对", "待确认": return .review
        case "无法确认", "已合入 · 本地需处理", "待合入 · 本地需处理", "暂时受阻", "需要处理", "需处理": return .attention
        case "已合入", "已同步", "已写入本地", "已完成": return .completed
        case "已忽略": return .ignored
        default: return .pending
        }
    }

    public static func migratedFilter(_ old: String) -> String {
        if old == "全部" { return old }
        return classify(old).rawValue
    }
}
