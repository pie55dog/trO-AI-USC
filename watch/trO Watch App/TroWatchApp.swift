import SwiftUI

/// trO for Apple Watch: the watch is the microphone while the bracelets do the taps.
/// See watch/README.md.
@main
struct TroWatchApp: App {
    @StateObject private var mic = MicController()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                RootView()
            }
            .environmentObject(mic)
            .tint(.troYellow)
        }
    }
}
