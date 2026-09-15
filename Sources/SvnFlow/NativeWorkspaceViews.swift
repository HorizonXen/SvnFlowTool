import AppKit
import SwiftUI
import SVNCore

struct WorkspaceColumn {
    let title: String
    let width: CGFloat
}

struct WorkspaceTableRow: Equatable {
    let id: String
    let values: [String]
    var symbol: String = "doc"
    var tint: NSColor = WorkbenchTheme.mutedNS
}

private final class ContrastCell: NSTableCellView {
    override var backgroundStyle: NSView.BackgroundStyle {
        didSet {
            guard let field = textField else { return }
            // Selection uses a dark custom fill in both active and inactive windows.
            // Keep labels light instead of adopting AppKit’s emphasized text color.
            let text = NSMutableAttributedString(attributedString: field.attributedStringValue)
            text.addAttribute(.foregroundColor, value: WorkbenchTheme.textNS, range: NSRange(location: 0, length: text.length))
            field.attributedStringValue = text
        }
    }
}

private final class FlatSelectionRow: NSTableRowView {
    override var interiorBackgroundStyle: NSView.BackgroundStyle { isSelected ? .emphasized : .normal }

    override func drawSelection(in dirtyRect: NSRect) {
        WorkbenchTheme.selectionNS.setFill()
        bounds.fill()
        WorkbenchTheme.accentNS.setFill()
        NSRect(x: bounds.minX, y: bounds.minY, width: 3, height: bounds.height).fill()
    }
}

struct WorkspaceContextAction {
    let title: String
    let perform: () -> Void
    var enabled = true
}
private final class ContextTable: NSTableView {
    var actions: ((Int) -> [WorkspaceContextAction])?
    override func menu(for event: NSEvent) -> NSMenu? {
        let index = row(at: convert(event.locationInWindow, from: nil))
        guard index >= 0 else { return nil }
        if !selectedRowIndexes.contains(index) { selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false) }
        let menu = NSMenu()
        menu.autoenablesItems = false
        for action in actions?(index) ?? [] {
            let item = ContextMenuItem(title: action.title, action: #selector(ContextMenuItem.invoke), keyEquivalent: "")
            item.callback = action.perform; item.target = item; item.isEnabled = action.enabled; menu.addItem(item)
        }
        return menu.items.isEmpty ? nil : menu
    }
}
private final class ContextMenuItem: NSMenuItem {
    var callback: (() -> Void)?
    @objc func invoke() { callback?() }
}
struct WorkspaceTable: NSViewRepresentable {
    let columns: [WorkspaceColumn]
    let rows: [WorkspaceTableRow]
    @Binding var selection: String?
    var multipleSelection: Binding<Set<String>>? = nil
    var canSelect: ((String) -> Bool)? = nil
    var checkedPaths: Binding<Set<String>>? = nil
    var canCheck: ((String) -> Bool)? = nil
    var checkingEnabled = true
    var scrollToSelection = false
    var onDoubleClick: (() -> Void)?
    var contextActions: ((String) -> [WorkspaceContextAction])?

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        scroll.backgroundColor = WorkbenchTheme.canvasNS
        let table = ContextTable()
        table.actions = { [weak coordinator = context.coordinator] index in
            guard let coordinator, coordinator.displayedRows.indices.contains(index) else { return [] }
            return coordinator.parent.contextActions?(coordinator.displayedRows[index].id) ?? []
        }
        table.style = .plain
        table.rowHeight = 32
        table.intercellSpacing = NSSize(width: 0, height: 0)
        table.backgroundColor = WorkbenchTheme.canvasNS
        table.usesAlternatingRowBackgroundColors = false
        table.columnAutoresizingStyle = .lastColumnOnlyAutoresizingStyle
        table.allowsColumnReordering = true
        table.allowsMultipleSelection = multipleSelection != nil
        table.allowsEmptySelection = true
        table.focusRingType = .none
        if checkedPaths != nil {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("check"))
            column.title = "✓"; column.width = 30; column.minWidth = 30; column.maxWidth = 30
            table.addTableColumn(column)
        }
        for (index, spec) in columns.enumerated() {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(String(index)))
            column.title = spec.title
            column.width = spec.width
            column.minWidth = 40
            column.headerCell.font = .systemFont(ofSize: 12)
            column.sortDescriptorPrototype = NSSortDescriptor(key: String(index), ascending: true)
            table.addTableColumn(column)
        }
        table.delegate = context.coordinator
        table.dataSource = context.coordinator
        table.target = context.coordinator
        table.doubleAction = #selector(Coordinator.doubleClick)
        scroll.documentView = table
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        let coordinator = context.coordinator
        coordinator.parent = self
        guard let table = scroll.documentView as? NSTableView else { return }
        for (column, spec) in zip(table.tableColumns.filter { $0.identifier.rawValue != "check" }, columns) { column.title = spec.title }
        coordinator.updateRows(in: table)
    }
    @MainActor final class Coordinator: NSObject, NSTableViewDelegate, NSTableViewDataSource {
        var parent: WorkspaceTable
        var displayedRows: [WorkspaceTableRow] = []
        private var sourceRows: [WorkspaceTableRow] = []
        private var appliedDescriptors: [NSSortDescriptor] = []
        private var previousChecked: Set<String>?
        private var previousCheckingEnabled = true
        var updating = false
        init(_ parent: WorkspaceTable) { self.parent = parent }
        func updateRows(in table: NSTableView) {
            updating = true
            defer { updating = false }
            if sourceRows != parent.rows || appliedDescriptors != table.sortDescriptors {
                sourceRows = parent.rows
                appliedDescriptors = table.sortDescriptors
                let keys = appliedDescriptors.compactMap { descriptor -> (Int, Bool)? in
                    guard let key = descriptor.key, let column = Int(key) else { return nil }
                    return (column, descriptor.ascending)
                }
                if keys.isEmpty { displayedRows = sourceRows }
                else {
                    // Keep ties stable, including columns with no SVN data.
                    displayedRows = sourceRows.enumerated().sorted { left, right in
                        for (column, ascending) in keys {
                            let a = left.element.values.indices.contains(column) ? left.element.values[column] : ""
                            let b = right.element.values.indices.contains(column) ? right.element.values[column] : ""
                            let order = a.localizedStandardCompare(b)
                            if order != .orderedSame { return ascending ? order == .orderedAscending : order == .orderedDescending }
                        }
                        return left.offset < right.offset
                    }.map(\.element)
                }
                table.reloadData()
            }
            if previousChecked != parent.checkedPaths?.wrappedValue || previousCheckingEnabled != parent.checkingEnabled {
                previousChecked = parent.checkedPaths?.wrappedValue
                previousCheckingEnabled = parent.checkingEnabled
                if let column = table.tableColumns.firstIndex(where: { $0.identifier.rawValue == "check" }) {
                    table.reloadData(forRowIndexes: IndexSet(displayedRows.indices), columnIndexes: IndexSet(integer: column))
                }
            }
            let index = displayedRows.firstIndex { $0.id == parent.selection }
            let selectedIDs = parent.multipleSelection?.wrappedValue ?? Set([parent.selection].compactMap { $0 })
            let desired = IndexSet(displayedRows.indices.filter { selectedIDs.contains(displayedRows[$0].id) })
            if table.selectedRowIndexes != desired {
                table.selectRowIndexes(desired, byExtendingSelection: false)
                if parent.scrollToSelection, let index { table.scrollRowToVisible(index) }
            }
        }
        func tableView(_ tableView: NSTableView, sortDescriptorsDidChange oldDescriptors: [NSSortDescriptor]) {
            updateRows(in: tableView)
        }
        func numberOfRows(in tableView: NSTableView) -> Int { displayedRows.count }
        func tableView(_ tableView: NSTableView, rowViewForRow row: Int) -> NSTableRowView? { FlatSelectionRow() }
        func tableViewSelectionDidChange(_ notification: Notification) {
            guard !updating, let table = notification.object as? NSTableView else { return }
            let indexes = table.selectedRowIndexes.filter { displayedRows.indices.contains($0) }
            parent.multipleSelection?.wrappedValue = Set(indexes.map { displayedRows[$0].id })
            let focus = indexes.contains(table.clickedRow) ? table.clickedRow : table.selectedRow
            parent.selection = displayedRows.indices.contains(focus) ? displayedRows[focus].id : nil
        }
        func tableView(_ tableView: NSTableView, selectionIndexesForProposedSelection proposed: IndexSet) -> IndexSet {
            IndexSet(proposed.filter { displayedRows.indices.contains($0) && (parent.canSelect?(displayedRows[$0].id) ?? true) })
        }
        @objc func doubleClick(_ sender: NSTableView) {
            guard displayedRows.indices.contains(sender.clickedRow) else { return }
            parent.selection = displayedRows[sender.clickedRow].id
            parent.onDoubleClick?()
        }
        @objc func toggleChecked(_ sender: NSButton) {
            guard parent.checkingEnabled, let path = sender.identifier?.rawValue,
                  parent.canCheck?(path) ?? true else { return }
            if sender.state == .on { parent.checkedPaths?.wrappedValue.insert(path) }
            else { parent.checkedPaths?.wrappedValue.remove(path) }
        }
        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            if tableColumn?.identifier.rawValue == "check", displayedRows.indices.contains(row) {
                let path = displayedRows[row].id
                let button = NSButton(checkboxWithTitle: "", target: self, action: #selector(toggleChecked(_:)))
                button.identifier = NSUserInterfaceItemIdentifier(path)
                button.setAccessibilityLabel(displayedRows[row].values.joined(separator: " "))
                button.state = parent.checkedPaths?.wrappedValue.contains(path) == true ? .on : .off
                button.isEnabled = parent.checkingEnabled && (parent.canCheck?(path) ?? true)
                return button
            }
            guard let column = tableColumn, let index = Int(column.identifier.rawValue), displayedRows.indices.contains(row) else { return nil }
            let data = displayedRows[row]
            let cell = ContrastCell()
            let field = NSTextField(labelWithString: data.values.indices.contains(index) ? data.values[index] : "")
            field.font = .systemFont(ofSize: 12)
            field.textColor = WorkbenchTheme.textNS
            field.lineBreakMode = .byTruncatingMiddle
            field.translatesAutoresizingMaskIntoConstraints = false
            cell.addSubview(field)
            cell.textField = field
            var leading: CGFloat = 5
            if index == 0 && !data.symbol.isEmpty {
                let icon = NSImageView()
                icon.image = NSImage(systemSymbolName: data.symbol, accessibilityDescription: nil)
                icon.contentTintColor = data.tint
                icon.translatesAutoresizingMaskIntoConstraints = false
                cell.addSubview(icon)
                NSLayoutConstraint.activate([
                    icon.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 5),
                    icon.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
                    icon.widthAnchor.constraint(equalToConstant: 13), icon.heightAnchor.constraint(equalToConstant: 15)
                ])
                leading = 23
            }
            NSLayoutConstraint.activate([
                field.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: leading),
                field.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -4),
                field.centerYAnchor.constraint(equalTo: cell.centerYAnchor)
            ])
            return cell
        }
    }
}

final class WorkspaceTreeNode {
    let id: String
    let title: String
    let revision: String
    let copyID: UUID?
    let relative: String
    var children: [WorkspaceTreeNode] = []
    var changeState: ItemState = .normal
    var changeCount = 0
    var localPath = ""
    init(id: String, title: String, revision: String = "", copyID: UUID? = nil, relative: String = "") {
        self.id = id; self.title = title; self.revision = revision; self.copyID = copyID; self.relative = relative
    }
}

struct WorkspaceTree: NSViewRepresentable {
    let projectTitle: String
    let copies: [WorkingCopy]
    let directories: [UUID: [LocalEntry]]
    let changes: [UUID: [StatusItem]]
    let contentVersion: Int
    let selectedCopy: UUID?
    let selectedDirectory: String
    let onSelect: (UUID, String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        let tree = NSOutlineView()
        tree.style = .plain
        tree.headerView = nil
        tree.rowHeight = 30
        tree.intercellSpacing = NSSize(width: 0, height: 0)
        tree.indentationPerLevel = 14
        tree.backgroundColor = WorkbenchTheme.canvasNS
        tree.focusRingType = .none
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("directory"))
        column.width = 420
        tree.addTableColumn(column)
        tree.outlineTableColumn = column
        tree.columnAutoresizingStyle = .noColumnAutoresizing
        tree.delegate = context.coordinator
        tree.dataSource = context.coordinator
        tree.target = context.coordinator
        tree.action = #selector(Coordinator.clickFolder(_:))
        scroll.documentView = tree
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let tree = scroll.documentView as? NSOutlineView else { return }
        let c = context.coordinator
        c.parent = self
        let signature = copies.map { "\($0.id):\($0.revision)" }.joined() + (selectedCopy?.uuidString ?? "") + String(contentVersion) + InterfaceLanguage.code
        c.updating = true
        if c.signature != signature {
            if c.root == nil { c.expandedIDs.insert("project") }
            c.rebuild()
            c.signature = signature
            tree.reloadData()
            for node in c.allNodes where c.expandedIDs.contains(node.id) {
                tree.expandItem(node)
            }
        }
        if let node = c.allNodes.first(where: { $0.copyID == selectedCopy && $0.relative == selectedDirectory }) {
            let row = tree.row(forItem: node)
            if row >= 0 && row != tree.selectedRow { tree.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false) }
        }
        c.updating = false
    }
    @MainActor final class Coordinator: NSObject, NSOutlineViewDataSource, NSOutlineViewDelegate {
        var parent: WorkspaceTree
        var root: WorkspaceTreeNode?
        var allNodes: [WorkspaceTreeNode] = []
        var signature = ""
        var expandedIDs = Set<String>()
        var updating = false
        init(_ parent: WorkspaceTree) { self.parent = parent }
        func rebuild() {
            let root = WorkspaceTreeNode(id: "project", title: parent.projectTitle)
            allNodes = [root]
            for copy in parent.copies {
                let node = WorkspaceTreeNode(id: copy.id.uuidString, title: copy.name, revision: copy.revision, copyID: copy.id)
                node.localPath = copy.path
                root.children.append(node)
                allNodes.append(node)
                var byPath: [String: WorkspaceTreeNode] = ["": node]
                for directory in parent.directories[copy.id] ?? [] {
                    let child = WorkspaceTreeNode(id: directory.path, title: directory.name, revision: directory.revision ?? "", copyID: copy.id, relative: directory.relative)
                    let parentPath = (directory.relative as NSString).deletingLastPathComponent
                    (byPath[parentPath] ?? node).children.append(child)
                    byPath[directory.relative] = child
                    allNodes.append(child)
                }
                let summaries = DirectoryChanges.summarize(parent.changes[copy.id] ?? [], directories: Set(byPath.keys))
                for (relative, summary) in summaries {
                    byPath[relative]?.changeCount = summary.count
                    byPath[relative]?.changeState = summary.state
                }
            }
            self.root = root
        }
        func outlineView(_ outlineView: NSOutlineView, numberOfChildrenOfItem item: Any?) -> Int {
            if let node = item as? WorkspaceTreeNode { return node.children.count }
            return root == nil ? 0 : 1
        }
        func outlineView(_ outlineView: NSOutlineView, child index: Int, ofItem item: Any?) -> Any { (item as? WorkspaceTreeNode)?.children[index] ?? root! }
        func outlineView(_ outlineView: NSOutlineView, isItemExpandable item: Any) -> Bool {
            let node = item as! WorkspaceTreeNode
            return !node.children.isEmpty || (node.copyID != nil && node.relative.isEmpty)
        }
        @objc func clickFolder(_ tree: NSOutlineView) {
            guard tree.clickedRow >= 0, let node = tree.item(atRow: tree.clickedRow) as? WorkspaceTreeNode else { return }
            // Row clicks reveal folders; only the disclosure control collapses them.
            if !tree.isItemExpanded(node) {
                expandedIDs.insert(node.id)
                tree.expandItem(node)
            }
        }
        func outlineViewItemDidExpand(_ notification: Notification) {
            guard !updating, let node = notification.userInfo?["NSObject"] as? WorkspaceTreeNode else { return }
            expandedIDs.insert(node.id)
        }
        func outlineViewItemDidCollapse(_ notification: Notification) {
            guard !updating, let node = notification.userInfo?["NSObject"] as? WorkspaceTreeNode else { return }
            expandedIDs.remove(node.id)
        }
        func outlineView(_ outlineView: NSOutlineView, rowViewForItem item: Any) -> NSTableRowView? { FlatSelectionRow() }
        func outlineViewSelectionDidChange(_ notification: Notification) {
            guard !updating, let tree = notification.object as? NSOutlineView,
                  let node = tree.item(atRow: tree.selectedRow) as? WorkspaceTreeNode, let id = node.copyID else { return }
            parent.onSelect(id, node.relative)
        }
        func outlineView(_ outlineView: NSOutlineView, viewFor tableColumn: NSTableColumn?, item: Any) -> NSView? {
            let node = item as! WorkspaceTreeNode
            let cell = ContrastCell()
            let text = NSMutableAttributedString(string: node.title, attributes: [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: WorkbenchTheme.textNS])
            if node.changeCount > 0 { text.append(NSAttributedString(string: "  \(node.changeCount)", attributes: [.font: NSFont.monospacedSystemFont(ofSize: 11, weight: .medium), .foregroundColor: WorkbenchTheme.accentNS])) }
            if !node.localPath.isEmpty { cell.toolTip = node.localPath }

            let field = NSTextField(labelWithAttributedString: text)
            field.translatesAutoresizingMaskIntoConstraints = false
            cell.addSubview(field)
            cell.textField = field
            let isRoot = node.id == "project"
            if !isRoot {
                let icon = NSImageView()
                icon.image = Self.folderImage
                icon.translatesAutoresizingMaskIntoConstraints = false
                cell.addSubview(icon)
                NSLayoutConstraint.activate([icon.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 1), icon.widthAnchor.constraint(equalToConstant: 14), icon.heightAnchor.constraint(equalToConstant: 14), icon.centerYAnchor.constraint(equalTo: cell.centerYAnchor)])
                if node.changeCount > 0 {
                    let badge = NSImageView()
                    let symbol: String
                    let color: NSColor
                    switch node.changeState {
                    case .conflicted, .obstructed, .incomplete: symbol = "exclamationmark.circle.fill"; color = WorkbenchTheme.dangerNS
                    case .deleted, .missing: symbol = "minus.circle.fill"; color = WorkbenchTheme.dangerNS
                    case .added: symbol = "plus.circle.fill"; color = WorkbenchTheme.successNS
                    case .unversioned: symbol = "questionmark.circle.fill"; color = WorkbenchTheme.warningNS
                    default: symbol = "pencil.circle.fill"; color = WorkbenchTheme.accentNS
                    }
                    badge.image = NSImage(systemSymbolName: symbol, accessibilityDescription: T("Contains {0} local changes", "包含 {0} 项本地变化", node.changeCount))
                    badge.contentTintColor = color
                    badge.translatesAutoresizingMaskIntoConstraints = false
                    cell.addSubview(badge)
                    NSLayoutConstraint.activate([badge.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 9), badge.centerYAnchor.constraint(equalTo: cell.centerYAnchor, constant: 3), badge.widthAnchor.constraint(equalToConstant: 10), badge.heightAnchor.constraint(equalToConstant: 10)])
                    cell.toolTip = (node.localPath.isEmpty ? "" : node.localPath + "\n") + T("Contains {0} local changes, including subdirectories", "包含 {0} 项本地变化（含子目录）", node.changeCount)
                }
            }
            NSLayoutConstraint.activate([field.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: isRoot ? 0 : 20), field.centerYAnchor.constraint(equalTo: cell.centerYAnchor), field.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -3)])
            return cell
        }
        static var folderImage: NSImage {
            NSImage(size: NSSize(width: 16, height: 16), flipped: false) { rect in
                let shape = NSBezierPath()
                shape.move(to: NSPoint(x: 1.5, y: 3.5)); shape.line(to: NSPoint(x: 1.5, y: 12))
                shape.line(to: NSPoint(x: 6, y: 12)); shape.line(to: NSPoint(x: 8, y: 10.5))
                shape.line(to: NSPoint(x: 14.5, y: 10.5)); shape.line(to: NSPoint(x: 14.5, y: 3.5)); shape.close()
                WorkbenchTheme.accentNS.withAlphaComponent(0.2).setFill(); shape.fill()
                WorkbenchTheme.accentNS.setStroke(); shape.lineWidth = 0.8; shape.stroke()
                return true
            }
        }
    }
}

struct WorkspaceWindowStyle: NSViewRepresentable {
    var title: String
    var preventsClose = false
    func makeNSView(context: Context) -> NSView { NSView() }
    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.title = title
            if preventsClose { window.styleMask.remove(.closable) } else { window.styleMask.insert(.closable) }
            window.titlebarAppearsTransparent = false
            window.toolbar = nil
            window.styleMask.remove(.fullSizeContentView)
            window.titlebarSeparatorStyle = .line
            window.backgroundColor = WorkbenchTheme.panelNS
            window.appearance = NSAppearance(named: .aqua)
            // AppKit owns title positioning, truncation and traffic-light clearance.
            window.titleVisibility = .visible
            window.standardWindowButton(.closeButton)?.isHidden = false
            window.standardWindowButton(.miniaturizeButton)?.isHidden = false
            window.standardWindowButton(.zoomButton)?.isHidden = false
        }
    }
}

struct WorkbenchOutputText: NSViewRepresentable {
    let text: String
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true; scroll.autohidesScrollers = true
        let view = NSTextView()
        view.isEditable = false; view.isSelectable = true
        view.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        view.backgroundColor = WorkbenchTheme.canvasNS
        view.textColor = WorkbenchTheme.textNS
        view.selectedTextAttributes = [.backgroundColor: WorkbenchTheme.selectionNS, .foregroundColor: WorkbenchTheme.textNS]
        view.textContainerInset = NSSize(width: 7, height: 7)
        view.isVerticallyResizable = true
        view.autoresizingMask = [.width]
        scroll.documentView = view
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView else { return }
        if view.string != text { view.string = text }
    }
}

struct WorkbenchFileSplit<Left: View, Right: View>: View {
    @AppStorage(InterfaceLanguage.key) private var interfaceLanguage = "zh-Hans"
    @State private var fraction: CGFloat = 0.235
    @State private var dragStart: CGFloat?
    let showsLeft: Bool
    @ViewBuilder var left: () -> Left
    @ViewBuilder var right: () -> Right
    var body: some View {
        let _ = interfaceLanguage;
        GeometryReader { proxy in
            let width = max(190, min(proxy.size.width * fraction, proxy.size.width - 655))
            HStack(spacing: 0) {
                if showsLeft {
                    left().frame(width: width)
                    Rectangle().fill(WorkbenchTheme.panel).frame(width: 5)
                        .overlay(Rectangle().fill(WorkbenchTheme.border).frame(width: 0.5))
                        .onHover { if $0 { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() } }
                        .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                            if dragStart == nil { dragStart = fraction }
                            fraction = min(0.5, max(190 / proxy.size.width, (dragStart ?? fraction) + value.translation.width / proxy.size.width))
                        }.onEnded { _ in dragStart = nil })
                }
                right().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}
