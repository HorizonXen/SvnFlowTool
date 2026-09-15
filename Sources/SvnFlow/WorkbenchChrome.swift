import AppKit
import SwiftUI

/// Explicit close actions for sheets/popovers; callers retain their draft state.
struct WorkbenchCloseButton: View {
    var title = "关闭"
    var disabled = false
    var hint = "关闭当前窗口"
    let action: () -> Void
    var body: some View {
        Button(action: action) { Label(title, systemImage: "xmark") }
            .buttonStyle(WorkbenchButtonStyle()).disabled(disabled)
            .keyboardShortcut(.cancelAction).help(disabled ? "当前操作完成后可关闭" : hint)
    }
}

/// Uses the owning window, never the key window; performClose honors its delegate.
struct WorkbenchWindowClose: NSViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: L("关闭"), target: context.coordinator, action: #selector(Coordinator.close(_:)))
        button.bezelStyle = .rounded
        button.font = .systemFont(ofSize: 12, weight: .medium)
        button.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: nil)
        button.imagePosition = .imageLeading
        button.setAccessibilityLabel(L("关闭当前窗口"))
        button.toolTip = L("关闭当前窗口；正在写入时需等待操作完成")
        return button
    }
    func updateNSView(_ button: NSButton, context: Context) { button.title = L("关闭") }
    @MainActor final class Coordinator: NSObject {
        @objc func close(_ sender: NSButton) { sender.window?.performClose(nil) }
    }
}

struct WorkbenchWindowChrome<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(title).font(.system(size: 12, weight: .medium)).lineLimit(1).truncationMode(.middle)
                Spacer(minLength: 12)
                WorkbenchWindowClose().frame(width: 76, height: 30)
            }.foregroundStyle(WorkbenchTheme.muted).padding(.horizontal, 18).padding(.vertical, 8).background(WorkbenchTheme.panel)
            Divider()
            content
        }
    }
}
