import SwiftUI

/// trO's colors (frontend/src/styles.css): near-black, maroon, Trojan yellow, cream.
extension Color {
    static let troYellow = Color(red: 0xFD / 255, green: 0xE8 / 255, blue: 0x72 / 255) // #fde872
    static let troMaroon = Color(red: 0x86 / 255, green: 0x2B / 255, blue: 0x2B / 255) // #862b2b
    static let troCream = Color(red: 0xFC / 255, green: 0xFC / 255, blue: 0xF9 / 255) // #fcfcf9
}

private func clock(_ s: Int) -> String { String(format: "%d:%02d", s / 60, s % 60) }

struct RootView: View {
    @EnvironmentObject var mic: MicController

    var body: some View {
        if mic.pairing == nil {
            PairView()
        } else {
            MicView()
        }
    }
}

// MARK: - Pairing

/// Type the 6-digit code from the phone (Phone mic page > "Get watch code").
struct PairView: View {
    @EnvironmentObject var mic: MicController
    @State private var code = ""

    private let keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"]

    var body: some View {
        ScrollView {
            VStack(spacing: 6) {
                Text("trO")
                    .font(.system(size: 22, weight: .semibold, design: .serif))
                    .foregroundStyle(Color.troYellow)
                Text(mic.pairingBusy ? "Pairing…" : "Code from your phone")
                    .font(.footnote)
                    .foregroundStyle(Color.troCream.opacity(0.8))
                HStack(spacing: 4) {
                    ForEach(0..<6, id: \.self) { i in
                        Text(i < code.count ? String(Array(code)[i]) : "·")
                            .font(.system(.title3, design: .monospaced).weight(.semibold))
                            .frame(width: 18)
                            .foregroundStyle(Color.troYellow)
                    }
                }
                .accessibilityLabel("Code: \(code.map(String.init).joined(separator: " "))")
                if let error = mic.pairError {
                    Text(error).font(.caption2).foregroundStyle(.red).multilineTextAlignment(.center)
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 3), spacing: 4) {
                    ForEach(keys, id: \.self) { key in
                        Button { press(key) } label: {
                            Text(key).font(.title3.weight(.medium)).frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .buttonStyle(.bordered)
                        .tint(key == "✓" ? .troYellow : .gray)
                        .disabled(mic.pairingBusy || (key == "✓" && code.count != 6))
                        .accessibilityLabel(key == "⌫" ? "Delete" : key == "✓" ? "Pair" : key)
                    }
                }
            }
        }
    }

    private func press(_ key: String) {
        switch key {
        case "⌫": if !code.isEmpty { code.removeLast() }
        case "✓": submit()
        default:
            guard code.count < 6 else { return }
            code += key
            if code.count == 6 { submit() }
        }
    }

    private func submit() {
        let c = code
        Task {
            await mic.pair(code: c)
            if mic.pairing == nil { code = "" }
        }
    }
}

// MARK: - Recording

struct MicView: View {
    @EnvironmentObject var mic: MicController

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                status
                controls
                if let notice = mic.notice {
                    Text(notice).font(.caption2).foregroundStyle(Color.troCream.opacity(0.8)).multilineTextAlignment(.center)
                }
                if !mic.clips.isEmpty { clipList }
                Button("Unpair watch", role: .destructive) { mic.signOut() }
                    .font(.caption2)
                    .buttonStyle(.plain)
                    .foregroundStyle(.red.opacity(0.8))
                    .padding(.top, 6)
            }
        }
        .navigationTitle(mic.pairing?.eventName ?? "trO")
    }

    @ViewBuilder private var status: some View {
        let a = mic.active
        ZStack {
            Circle().stroke(Color.troCream.opacity(0.15), lineWidth: 6)
            Circle()
                .trim(from: 0, to: CGFloat(max(0.04, mic.level)))
                .stroke(a == nil ? Color.troCream.opacity(0.5) : Color.troYellow, style: StrokeStyle(lineWidth: 6, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.easeOut(duration: 0.2), value: mic.level)
            VStack(spacing: 2) {
                Image(systemName: !mic.on ? "mic.slash" : a == nil ? "ear" : "record.circle.fill")
                    .font(.title3)
                    .foregroundStyle(a == nil ? Color.troCream : Color.troYellow)
                if let a {
                    Text(a.kind == .conversation ? "With \(a.name ?? "")" : "Voice note")
                        .font(.caption2).lineLimit(1)
                    Text("\(clock(mic.elapsed)) / \(clock(a.kind == .conversation ? Config.maxConversationSeconds : Config.maxVoiceNoteSeconds))")
                        .font(.caption2.monospacedDigit()).foregroundStyle(Color.troCream.opacity(0.7))
                } else {
                    Text(mic.on ? "Waiting for a tap" : "Mic off").font(.caption2)
                }
            }
            .padding(10)
        }
        .frame(width: 104, height: 104)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private var controls: some View {
        if !mic.on {
            Button {
                Task { await mic.start() }
            } label: {
                Label(mic.starting ? "Starting…" : "Start listening", systemImage: "mic.fill")
            }
            .tint(.troMaroon)
            .disabled(mic.starting)
        } else {
            if mic.active?.kind == .conversation {
                Button { mic.endConversation() } label: { Label("End conversation", systemImage: "stop.fill") }
                    .tint(.troYellow)
            }
            Button { mic.toggleVoiceNote() } label: {
                Label(mic.active?.kind == .voiceNote ? "Stop note" : "Voice note", systemImage: "waveform")
            }
            Button("Turn off mic") { mic.stop() }
                .font(.footnote)
        }
    }

    private var clipList: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(mic.clips) { c in
                HStack {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("\(c.label) · \(clock(c.seconds))").font(.caption2)
                        if let m = c.message { Text(m).font(.system(size: 10)).foregroundStyle(Color.troCream.opacity(0.6)) }
                    }
                    Spacer(minLength: 2)
                    Image(systemName: icon(c.status)).foregroundStyle(c.status == .sent ? Color.troYellow : Color.troCream.opacity(0.7))
                }
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.troCream.opacity(0.08)))
    }

    private func icon(_ s: MicController.Clip.Status) -> String {
        switch s {
        case .uploading: return "arrow.up.circle"
        case .sent: return "checkmark.circle.fill"
        case .refused: return "hand.raised.circle"
        case .failed: return "exclamationmark.circle"
        }
    }
}
