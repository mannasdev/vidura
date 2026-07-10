// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "ViduraPet",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "ViduraPet",
            path: "Sources/ViduraPet"
        )
    ]
)
