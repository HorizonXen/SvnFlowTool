import SwiftUI
import SVNCore

struct LocalIgnoreSheet: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @ObservedObject var model: Model
    @Environment(\.dismiss) private var dismiss
    var paths: [String] { model.ignoredPaths.filter { path in model.selected.map { UpdateRefresh.contains(path, in: $0.path) } ?? false }.sorted() }
    var body: some View {
        let _ = interfaceLanguage;
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text(L("管理忽略项")).font(.headline); Spacer(); WorkbenchCloseButton { dismiss() } }
            Text(L("仅在本应用中隐藏当前工作副本的文件和目录，重启后仍生效。不会修改文件、SVN 属性或仓库；目录规则包含全部子项。")).foregroundStyle(WorkbenchTheme.muted)
            List {
                ForEach(paths, id: \.self) { path in
                    HStack {
                        Image(systemName: "eye.slash").foregroundStyle(WorkbenchTheme.muted)
                        Text(model.selected.map { String(path.dropFirst($0.path.count + 1)) } ?? path).lineLimit(2).textSelection(.enabled)
                        Spacer()
                        Button(L("恢复显示")) { model.restoreLocally([path]) }
                    }.padding(.vertical, 3)
                }
            }.overlay { if paths.isEmpty { Text(L("当前工作副本没有忽略项")).foregroundStyle(WorkbenchTheme.muted) } }
            HStack {
                Button(L("全部恢复")) { model.restoreLocally(paths) }.disabled(paths.isEmpty)
                Spacer()
                Button(L("完成")) { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }.padding(20).frame(width: 620, height: 380).workbenchStyle().workbenchSecondarySurface()
    }
}
