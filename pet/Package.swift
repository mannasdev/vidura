// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "ViduraPet",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .target(
            name: "ViduraPetKit",
            path: "Sources/ViduraPetKit"
        ),
        .executableTarget(
            name: "ViduraPet",
            dependencies: ["ViduraPetKit"],
            path: "Sources/ViduraPet"
        ),
        .testTarget(
            name: "ViduraPetKitTests",
            dependencies: ["ViduraPetKit"],
            path: "Tests/ViduraPetKitTests"
        )
    ]
)
