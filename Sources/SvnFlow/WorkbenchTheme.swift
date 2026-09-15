import AppKit
import SwiftUI

/// Shared visual language for the workspace, workflow sheets and native diff renderers.
enum WorkbenchTheme {
    // Shared light palette for SwiftUI controls and AppKit tables / diff renderers.
    static func rgb(_ hex: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
                green: CGFloat((hex >> 8) & 255) / 255,
                blue: CGFloat(hex & 255) / 255, alpha: 1)
    }
    static let canvasNS = rgb(0xFFFFFF)
    static let panelNS = rgb(0xF6F8FB)
    static let raisedNS = rgb(0xEFF3F8)
    static let borderNS = rgb(0xDCE3EC)
    static let controlBorderNS = rgb(0xBDC9D8)
    static let textNS = rgb(0x172637)
    static let mutedNS = rgb(0x526579)
    static let accentNS = rgb(0x3267D6)
    static let selectionNS = rgb(0xE8F0FF)
    static let successNS = rgb(0x237A50)
    static let warningNS = rgb(0x956000)
    static let dangerNS = rgb(0xB53E32)
    static let infoSurface = Color(nsColor: rgb(0xF0F5FF))
    static let successSurface = Color(nsColor: rgb(0xEDF7F1))
    static let warningSurface = Color(nsColor: rgb(0xFFF5ED))
    static let canvas = Color(nsColor: canvasNS)
    static let panel = Color(nsColor: panelNS)
    static let raised = Color(nsColor: raisedNS)
    static let border = Color(nsColor: borderNS)
    static let controlBorder = Color(nsColor: controlBorderNS)
    static let text = Color(nsColor: textNS)
    static let muted = Color(nsColor: mutedNS)
    static let accent = Color(nsColor: accentNS)
    static let selection = Color(nsColor: selectionNS)
    static let success = Color(nsColor: successNS)
    static let warning = Color(nsColor: warningNS)
    static let danger = Color(nsColor: dangerNS)
}

struct WorkbenchButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    var prominent = false
    @State private var hovered = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12).padding(.vertical, 8)
            .foregroundStyle(enabled ? (prominent ? Color.white : WorkbenchTheme.text) : WorkbenchTheme.muted)
            .background(enabled && prominent ? WorkbenchTheme.accent : hovered && enabled ? WorkbenchTheme.raised : WorkbenchTheme.canvas, in: RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(enabled && prominent ? WorkbenchTheme.accent : WorkbenchTheme.border, lineWidth: 1))
            .opacity(enabled ? 1 : 0.5)
            .brightness(configuration.isPressed && enabled ? -0.06 : 0)
            .onHover { hovered = $0 }
    }
}

extension View {
    /// Opaque modal surface with an inset outline, so stacked sheets stay distinct.
    func workbenchSecondarySurface() -> some View {
        self.background(WorkbenchTheme.panel)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay {
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(WorkbenchTheme.border, lineWidth: 1)
                    .allowsHitTesting(false).accessibilityHidden(true)
            }
    }

    func workbenchStyle() -> some View {
        self.foregroundStyle(WorkbenchTheme.text).background(WorkbenchTheme.canvas)
            .tint(WorkbenchTheme.accent).accentColor(WorkbenchTheme.accent)
            .buttonStyle(WorkbenchButtonStyle()).environment(\.colorScheme, .light)
    }
}

/// Includes the title bar and stays visible when a floating window loses focus.
/// The decoration must never intercept window dragging, resizing or content clicks.
@MainActor final class WorkbenchWindowOutline: NSView {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func draw(_ dirtyRect: NSRect) {
        WorkbenchTheme.borderNS.setStroke()
        let outline = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.75, dy: 0.75), xRadius: 10, yRadius: 10)
        outline.lineWidth = 1
        outline.stroke()
    }
    static func install(on window: NSWindow) {
        guard let frameView = window.contentView?.superview else { return }
        guard !frameView.subviews.contains(where: { $0 is WorkbenchWindowOutline }) else { return }
        let outline = WorkbenchWindowOutline(frame: frameView.bounds)
        outline.autoresizingMask = [.width, .height]
        outline.setAccessibilityElement(false)
        frameView.addSubview(outline, positioned: .above, relativeTo: nil)
        window.hasShadow = true
    }
}

struct WorkbenchHeading: View {
    let eyebrow: String
    let title: String
    let subtitle: String
    let symbol: String
    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: symbol).font(.system(size: 22, weight: .light))
                .foregroundStyle(WorkbenchTheme.accent).frame(width: 46, height: 46)
                .background(WorkbenchTheme.selection, in: RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 20, weight: .semibold)).lineLimit(1).truncationMode(.middle)
                if !subtitle.isEmpty { Text(subtitle).font(.system(size: 11)).foregroundStyle(WorkbenchTheme.muted).lineLimit(1).truncationMode(.middle).help(subtitle) }
            }
        }
    }
}
