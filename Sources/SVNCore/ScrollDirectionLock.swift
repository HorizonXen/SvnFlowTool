/// Keep a touchpad gesture on its initial dominant axis, including momentum.
public struct ScrollDirectionLock: Sendable {
    public enum Axis: Sendable { case horizontal, vertical }
    public private(set) var axis: Axis?
    public init() {}
    public mutating func direction(x: Double, y: Double, startsGesture: Bool, continuous: Bool, shift: Bool = false) -> Axis? {
        if startsGesture || !continuous { axis = nil }
        if shift { axis = .horizontal }
        if axis == nil && (x != 0 || y != 0) { axis = abs(x) > abs(y) ? .horizontal : .vertical }
        return axis
    }
}
