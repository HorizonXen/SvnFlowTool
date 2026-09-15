import SwiftUI

/// Branch workflow components share the application palette.
enum SyncOrbit {
    static let background = WorkbenchTheme.canvas
    static let panel = WorkbenchTheme.panel
    static let sidebar = WorkbenchTheme.canvas
    static let line = WorkbenchTheme.border
    static let text = WorkbenchTheme.text
    static let muted = WorkbenchTheme.muted
    static let cyan = WorkbenchTheme.accent
    static let green = WorkbenchTheme.success
    static let amber = WorkbenchTheme.warning
}

struct SyncOrbitButton: ButtonStyle {
    var prominent = false
    func makeBody(configuration: Configuration) -> some View {
        WorkbenchButtonStyle(prominent: prominent).makeBody(configuration: configuration)
    }
}

struct SyncOrbitCard<Content: View>: View {
    var warning = false
    @ViewBuilder let content: Content
    var body: some View {
        content.padding(26).frame(maxWidth: .infinity, alignment: .leading)
            .background(SyncOrbit.panel)
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay { RoundedRectangle(cornerRadius: 9).strokeBorder(warning ? SyncOrbit.amber : WorkbenchTheme.border) }
    }
}

struct SyncOrbitCaption: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 10, weight: .medium, design: .monospaced))
            .tracking(1.8).foregroundStyle(SyncOrbit.muted)
    }
}

struct SyncOrbitSteps: View {
    /// 0 = scope, 1 = generation, 2 = review, 3 = local write, 4 = complete.
    let stage: Int
    var warning = false
    private let names = ["确定范围", "生成副本", "对比确认", "写入本地"]
    var body: some View {
        HStack(spacing: 10) {
            ForEach(names.indices, id: \.self) { index in
                if index > 0 { Rectangle().fill(SyncOrbit.line).frame(height: 1).accessibilityHidden(true) }
                HStack(spacing: 7) {
                    ZStack {
                        Circle().fill(index == stage ? SyncOrbit.cyan.opacity(0.08) : .clear)
                        Circle().strokeBorder(color(index).opacity(index == stage ? 0.9 : 0.45))
                        if index < stage { Image(systemName: "checkmark").font(.system(size: 9, weight: .semibold)) }
                        else if index == stage && warning { Image(systemName: "exclamationmark").font(.system(size: 10, weight: .bold)) }
                        else { Text("\(index + 1)").font(.system(size: 10, design: .monospaced)) }
                    }.frame(width: 24, height: 24)
                    Text(names[index]).font(.system(size: 11)).fixedSize()
                }.foregroundStyle(color(index))
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(names[index])，\(index < stage ? "已完成" : index == stage ? (warning ? "需处理" : "当前阶段") : "待进行")")
            }
        }
    }
    private func color(_ index: Int) -> Color {
        index < stage ? SyncOrbit.green : index == stage ? (warning ? SyncOrbit.amber : SyncOrbit.cyan) : SyncOrbit.muted
    }
}

struct SyncOrbitRoute: View {
    let stage: Int
    var sourceName = "源目录"
    var targetName = "目标目录"
    var body: some View {
        HStack(spacing: 13) {
            node("SOURCE", sourceName, color: SyncOrbit.cyan)
            Image(systemName: "arrow.right").foregroundStyle(stage == 1 ? SyncOrbit.cyan : SyncOrbit.muted)
                .font(.system(size: 11))
            node("STAGING", "待合入副本", color: stage == 1 || stage == 2 ? SyncOrbit.cyan : SyncOrbit.muted)
                .padding(.horizontal, 15).padding(.vertical, 10)
                .background(SyncOrbit.cyan.opacity(stage == 1 || stage == 2 ? 0.09 : 0.02), in: RoundedRectangle(cornerRadius: 6))
                .overlay { RoundedRectangle(cornerRadius: 6).strokeBorder(SyncOrbit.cyan.opacity(0.25)) }
            Image(systemName: "arrow.right").foregroundStyle(stage >= 3 ? SyncOrbit.green : SyncOrbit.muted)
                .font(.system(size: 11))
            node("TARGET", targetName, color: SyncOrbit.green)
        }.accessibilityElement(children: .ignore)
            .accessibilityLabel("源 \(sourceName)，待合入副本，目标 \(targetName)")
    }
    private func node(_ caption: String, _ title: String, color: Color) -> some View {
        VStack(spacing: 6) {
            Text(caption).font(.system(size: 9, design: .monospaced)).tracking(1.5).foregroundStyle(SyncOrbit.muted)
            Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(color)
        }
    }
}
