import AppKit
import SVNCore

/// Constrain the inactive axis before AppKit publishes scrolling notifications.
private final class DirectionalClipView: NSClipView {
    var axis: ScrollDirectionLock.Axis?
    var lockedOrigin = NSPoint.zero
    override func scroll(to newOrigin: NSPoint) {
        var point = newOrigin
        switch axis {
        case .vertical: point.x = lockedOrigin.x
        case .horizontal: point.y = lockedOrigin.y
        case nil: break
        }
        super.scroll(to: point)
    }
    override func constrainBoundsRect(_ proposedBounds: NSRect) -> NSRect {
        var proposed = proposedBounds
        switch axis {
        case .vertical: proposed.origin.x = lockedOrigin.x
        case .horizontal: proposed.origin.y = lockedOrigin.y
        case nil: break
        }
        return super.constrainBoundsRect(proposed)
    }
}
final class DirectionalScrollView: NSScrollView {
    private var direction = ScrollDirectionLock()
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        contentView = DirectionalClipView()
        horizontalScrollElasticity = .none
        verticalScrollElasticity = .none
        usesPredominantAxisScrolling = true
    }
    required init?(coder: NSCoder) { fatalError() }
    override func scrollWheel(with event: NSEvent) {
        guard let clip = contentView as? DirectionalClipView else { super.scrollWheel(with: event); return }
        let continuous = !event.phase.isEmpty || !event.momentumPhase.isEmpty
        let axis = direction.direction(x: event.scrollingDeltaX, y: event.scrollingDeltaY,
                                       startsGesture: event.phase.contains(.began) || event.phase.contains(.mayBegin),
                                       continuous: continuous, shift: event.modifierFlags.contains(.shift))
        clip.lockedOrigin = clip.bounds.origin
        clip.axis = axis
        defer { clip.axis = nil }
        super.scrollWheel(with: event)
    }
}
