// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SvnFlow",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "SvnFlow", targets: ["SvnFlow"])],
    targets: [
        .target(name: "SVNCore"),
        .executableTarget(name: "SVNPerformance", dependencies: ["SVNCore"], path: "Tests/Performance"),
        .executableTarget(name: "SvnFlow", dependencies: ["SVNCore"]),
        .executableTarget(name: "SVNCoreChecks", dependencies: ["SVNCore"], path: "Tests/SVNCoreTests")
    ]
)
