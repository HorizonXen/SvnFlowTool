import SwiftUI

/// Small, independently drawn desktop glyphs; sized to the reference toolbar.
struct WorkbenchIcon: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    let kind: String
    var body: some View {
        let _ = interfaceLanguage;
        ZStack {
            switch kind {
            case "update":
                papers.offset(x: 3)
                symbol("arrow.right", color: WorkbenchTheme.success).offset(x: -5, y: 2)
            case "merge": symbol("arrow.triangle.branch", color: WorkbenchTheme.success)
            case "commit":
                papers.offset(x: -3)
                symbol("checkmark", color: WorkbenchTheme.warning).offset(x: 5, y: 4)
            case "add":
                paper.offset(x: -2)
                symbol("plus", color: WorkbenchTheme.success).offset(x: 4, y: 4)
            case "remove":
                paper.offset(x: -2, y: -1)
                Rectangle().fill(WorkbenchTheme.danger).frame(width: 13, height: 3).offset(y: 5)
            case "move": papers
            case "revert":
                paper
                symbol("arrow.uturn.backward", color: WorkbenchTheme.danger).offset(x: 4, y: 4)
            case "delete": symbol("xmark", color: WorkbenchTheme.danger)
            case "fix": symbol("cross.case.fill", color: WorkbenchTheme.muted)
            case "changes": HStack(spacing: 3) { smallPaper; smallPaper }
            case "annotate":
                paper.offset(x: -3, y: -2)
                symbol("clock", color: WorkbenchTheme.muted).scaleEffect(0.7).offset(x: 5, y: 5)
            case "log":
                VStack(spacing: 2) { ForEach(0..<3) { _ in Rectangle().stroke(WorkbenchTheme.muted, lineWidth: 0.8).frame(width: 15, height: 5) } }
            case "graph": symbol("point.3.connected.trianglepath.dotted", color: WorkbenchTheme.accent)
            case "main", "review":
                VStack(spacing: 0) {
                    HStack(spacing: 0) { Rectangle().stroke(WorkbenchTheme.accent, lineWidth: 0.8).frame(width: 7); Rectangle().stroke(WorkbenchTheme.accent, lineWidth: 0.8) }
                    if kind == "review" { Rectangle().stroke(WorkbenchTheme.accent, lineWidth: 0.8).frame(height: 6) }
                }.frame(width: 21, height: 17).background(WorkbenchTheme.canvas)
            default: symbol(kind, color: WorkbenchTheme.muted)
            }
        }.frame(width: 23, height: 24)
    }
    var paper: some View {
        ZStack(alignment: .topTrailing) {
            Rectangle().fill(WorkbenchTheme.raised)
            Rectangle().stroke(WorkbenchTheme.muted, lineWidth: 0.8)
            Rectangle().fill(WorkbenchTheme.muted).frame(width: 4, height: 4)
        }.frame(width: 11, height: 15)
    }
    var smallPaper: some View { paper.scaleEffect(0.65).frame(width: 8, height: 14) }
    var papers: some View { ZStack { paper.offset(x: -3, y: -2); paper.offset(x: 2, y: 2) } }
    func symbol(_ name: String, color: Color) -> some View {
        Image(systemName: name).font(.system(size: 19, weight: .regular)).foregroundStyle(color)
    }
}

struct WorkbenchTool: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    let title: String
    let icon: String
    var enabled = true
    var selected = false
    var dropdown = false
    let action: () -> Void
    @State private var hovered = false
    var body: some View {
        let _ = interfaceLanguage;
        Button(action: action) {
            VStack(spacing: 2) {
                WorkbenchIcon(kind: icon)
                HStack(spacing: 2) {
                    Text(title).font(.system(size: 11)).fixedSize()
                    if dropdown { Image(systemName: "chevron.down").font(.system(size: 5, weight: .bold)) }
                }
            }.frame(width: title == L("Annotate") ? 56 : 45, height: 47)
                .background(selected ? WorkbenchTheme.selection : hovered && enabled ? WorkbenchTheme.raised : .clear)
                .foregroundStyle(enabled ? WorkbenchTheme.text : WorkbenchTheme.muted)
                .overlay(RoundedRectangle(cornerRadius: 3).stroke(selected ? WorkbenchTheme.accent : .clear))
                .clipShape(RoundedRectangle(cornerRadius: 3))
                .contentShape(Rectangle())
                .opacity(enabled ? 1 : 0.6)
        }.buttonStyle(.plain).disabled(!enabled).onHover { hovered = $0 }.help(title)
    }
}
