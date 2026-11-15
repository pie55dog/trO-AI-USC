import Foundation
import WatchKit

/// The watch as trO's microphone: the bracelets do the taps, the watch listens.
/// Same rules as the phone mic (frontend/src/phoneMic/controller.ts) and the
/// bracelet mic build (firmware/README.md):
///
///   new tap, both said yes   start a conversation clip (with pre-roll: the watch only
///                            hears about the tap on its next check)
///   new tap, someone said no nothing recorded
///   next tap / End / 3 min   the clip stops and uploads
///   Note button              a voice note (30 s max)
@MainActor
final class MicController: ObservableObject {
    struct Active: Equatable {
        enum Kind { case conversation, voiceNote }
        let kind: Kind
        let connectionId: Int?
        let name: String?
        let startSample: Int
    }

    struct Clip: Identifiable {
        enum Status { case uploading, sent, refused, failed }
        let id: Int
        let label: String
        let seconds: Int
        var status: Status
        var message: String?
    }

    @Published private(set) var pairing: Pairing? = PairingStore.load()
    @Published private(set) var on = false
    @Published private(set) var starting = false
    @Published private(set) var active: Active?
    @Published private(set) var elapsed = 0
    @Published private(set) var level: Float = 0
    @Published private(set) var notice: String?
    @Published private(set) var clips: [Clip] = []
    @Published var pairError: String?
    @Published private(set) var pairingBusy = false

    private let capture = AudioCapture()
    private var seen = Set<Int>()
    private var seeded = false
    private var pollTask: Task<Void, Never>?
    private var tickTimer: Timer?
    private var nextClipId = 1
    private var store: SampleStore { capture.store }
    private var rate: Int { Config.sampleRate }

    // MARK: Pairing

    func pair(code: String) async {
        pairError = nil
        pairingBusy = true
        defer { pairingBusy = false }
        do {
            let p = try await API.pair(code: code)
            PairingStore.save(p)
            pairing = p
            WKInterfaceDevice.current().play(.success)
        } catch {
            pairError = error.localizedDescription
            WKInterfaceDevice.current().play(.failure)
        }
    }

    func signOut() {
        stop()
        PairingStore.clear()
        pairing = nil
        clips = []
    }

    // MARK: Mic on / off

    func start() async {
        guard !on, !starting, pairing != nil else { return }
        starting = true
        notice = nil
        do {
            try await capture.start()
        } catch {
            notice = error.localizedDescription
            starting = false
            return
        }
        seen = []
        seeded = false
        await poll() // taps from before the mic was on aren't recorded
        on = true
        starting = false
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(Config.pollSeconds * 1_000_000_000))
                await self?.poll()
            }
        }
        tickTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    /// Turn the mic off. A conversation in progress is saved first.
    func stop() {
        if active != nil { finish(at: store.end) }
        pollTask?.cancel()
        pollTask = nil
        tickTimer?.invalidate()
        tickTimer = nil
        capture.stop()
        on = false
        starting = false
        level = 0
    }

    func endConversation() {
        if active?.kind == .conversation { finish(at: store.end) }
    }

    func toggleVoiceNote() {
        guard on else { return }
        if active?.kind == .voiceNote {
            finish(at: store.end)
            return
        }
        if active != nil { finish(at: store.end) }
        active = Active(kind: .voiceNote, connectionId: nil, name: nil, startSample: store.end)
        notice = nil
        WKInterfaceDevice.current().play(.start)
        tick()
    }

    // MARK: Taps

    private func poll() async {
        guard let p = pairing else { return }
        do {
            let list = try await API.connections(eventId: p.eventId, token: p.token)
            handle(list)
        } catch let e as APIError where e.status == 401 {
            notice = "Signed out. Pair the watch again from your phone."
            signOut()
        } catch {
            // Try again next time (the server may be waking up).
        }
    }

    private func handle(_ list: [TapPerson]) {
        let fresh = list.filter { $0.connectionId != nil && !seen.contains($0.connectionId!) }
        fresh.forEach { seen.insert($0.connectionId!) }
        if !seeded {
            seeded = true
            return
        }
        guard let newest = fresh.max(by: { $0.tappedAt < $1.tappedAt }) else { return }

        // The tap happened a moment before we heard about it: cut there.
        let cut = max(store.first, store.end - Config.prerollSeconds * rate, active?.startSample ?? 0)
        if active != nil { finish(at: cut) }

        if newest.bothConsented == true {
            active = Active(kind: .conversation, connectionId: newest.connectionId, name: newest.name, startSample: cut)
            notice = nil
            WKInterfaceDevice.current().play(.start)
        } else {
            notice = "Tapped \(firstName(newest.name)). Not recording: one of you said no."
            WKInterfaceDevice.current().play(.notification)
        }
        tick()
    }

    private func tick() {
        level = capture.level
        guard let a = active else {
            store.trim(before: store.end - (Config.prerollSeconds + 1) * rate)
            elapsed = 0
            return
        }
        let limit = a.kind == .conversation ? Config.maxConversationSeconds : Config.maxVoiceNoteSeconds
        let seconds = (store.end - a.startSample) / rate
        if seconds >= limit {
            finish(at: a.startSample + limit * rate)
            notice = a.kind == .conversation ? "Stopped at 3 minutes. Saved." : "Voice notes stop at 30 seconds. Saved."
        } else {
            store.trim(before: a.startSample)
            elapsed = seconds
        }
    }

    // MARK: Clips

    private func finish(at endSample: Int) {
        guard let a = active, let p = pairing else { active = nil; return }
        active = nil
        elapsed = 0
        let samples = store.slice(from: a.startSample, to: endSample)
        let seconds = Double(samples.count) / Double(rate)
        guard seconds >= Config.minClipSeconds else { return }
        WKInterfaceDevice.current().play(.stop)
        let clip = Clip(
            id: nextClipId,
            label: a.kind == .conversation ? "With \(firstName(a.name ?? ""))" : "Voice note",
            seconds: Int(seconds.rounded()),
            status: .uploading
        )
        nextClipId += 1
        clips = Array(([clip] + clips).prefix(10))
        let wav = WAV.encode(samples)
        let startedAt = store.wallMs(at: a.startSample)
        let kind = a.kind == .conversation ? "conversation" : "voice_note"
        Task { await send(clip.id, wav: wav, kind: kind, connectionId: a.connectionId, startedAt: startedAt, pairing: p) }
    }

    private func send(_ id: Int, wav: Data, kind: String, connectionId: Int?, startedAt: Double?, pairing p: Pairing) async {
        var last = "Couldn't upload."
        for wait in [0.0, 3, 8, 20] {
            if wait > 0 { try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) }
            do {
                try await API.upload(eventId: p.eventId, token: p.token, wav: wav, kind: kind, connectionId: connectionId, startedAtMs: startedAt)
                update(id, .sent, "Sent. Notes are on your dashboard soon.")
                return
            } catch let e as APIError {
                if e.status == 403 { update(id, .refused, "Not kept: someone turned recording off."); return }
                if (400..<500).contains(e.status) && e.status != 408 && e.status != 429 { update(id, .failed, e.message); return }
                last = e.message
            } catch {
                last = error.localizedDescription
            }
        }
        update(id, .failed, last)
    }

    private func update(_ id: Int, _ status: Clip.Status, _ message: String) {
        guard let i = clips.firstIndex(where: { $0.id == id }) else { return }
        clips[i].status = status
        clips[i].message = message
    }

    private func firstName(_ name: String) -> String {
        name.split(separator: " ").first.map(String.init) ?? name
    }
}
