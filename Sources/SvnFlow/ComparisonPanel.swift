import AppKit
import SwiftUI

@MainActor final class WorkbenchApplicationDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .aqua)
        if let url = Bundle.main.url(forResource: "AppIcon-v3", withExtension: "icns"), let icon = NSImage(contentsOf: url) { NSApp.applicationIconImage = icon }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if QueryWindows.shared.branchSyncBusy || Model.activeReverts > 0 { NSSound.beep(); return .terminateCancel }
        return .terminateNow
    }
    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        QueryWindows.shared.comparisonDockMenu()
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        let frontWindow = sender.modalWindow ?? sender.keyWindow ?? sender.mainWindow
        var windows = sender.orderedWindows.filter {
            $0.styleMask.contains(.titled) && ($0.isVisible || $0.isMiniaturized) && $0.sheetParent == nil
        }
        let remainingWindows = sender.windows.filter { $0.isMiniaturized && $0.styleMask.contains(.titled) }
            + QueryWindows.shared.openWindows
        for window in remainingWindows where !windows.contains(where: { $0 === window }) {
            windows.append(window)
        }
        guard !windows.isEmpty else { return true }
        sender.unhide(nil)
        sender.activate(ignoringOtherApps: true)
        // Restore back to front so the previously active window keeps focus.
        for window in windows.reversed() {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.orderFront(nil)
        }
        if let frontWindow { frontWindow.makeKeyAndOrderFront(nil) }
        else { windows.first?.makeKeyAndOrderFront(nil) }
        return false
    }
}

/// Fixed app-local tiers: workbench < assistant < comparison.
class WorkflowPanel: NSPanel {
    var preferredLevel: NSWindow.Level { .floating }
    var suspended = false { didSet { level = suspended ? .normal : preferredLevel } }
    override var canBecomeKey: Bool { true }
    func configureLayer() {
        isFloatingPanel = true
        hidesOnDeactivate = true
        becomesKeyOnlyIfNeeded = false
        level = suspended ? .normal : preferredLevel
        isExcludedFromWindowsMenu = false
    }
}
final class ComparisonPanel: WorkflowPanel {
    override var preferredLevel: NSWindow.Level { .init(rawValue: NSWindow.Level.floating.rawValue + 1) }
}
struct ComparisonPinButton: View {
    var body: some View {
        Label("固定层级", systemImage: "pin.fill")
            .font(.system(size: 11))
            .foregroundStyle(Color.accentColor)
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(Color.accentColor.opacity(0.1), in: RoundedRectangle(cornerRadius: 5))
            .help("窗口层级固定：对比界面 > 同步助手 > 工作台")
    }
}
