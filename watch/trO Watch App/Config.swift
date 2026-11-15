import Foundation

/// Settings that change between the live demo and a laptop setup.
enum Config {
    /// The trO backend. For `./scripts/local-server.sh`, use the laptop's address, e.g.
    /// `http://192.168.1.20:8000` (and allow it in Info.plist's NSAppTransportSecurity).
    static let apiBase = URL(string: "https://tro-api.onrender.com")!

    /// Same rules as the phone mic (frontend/src/phoneMic/controller.ts) and the bracelet mic.
    static let sampleRate = 16_000
    static let prerollSeconds = 6
    static let maxConversationSeconds = 180
    static let maxVoiceNoteSeconds = 30
    static let minClipSeconds = 1.0
    static let pollSeconds = 2.5
}
