import AVFoundation
import Foundation

/// Captured 16 kHz 16-bit mono samples, addressed by absolute sample index
/// (0 = first sample since the mic started). Same design as the phone mic's
/// SampleStore (frontend/src/phoneMic/audio.ts). Thread-safe: the audio thread
/// appends while the main thread slices.
final class SampleStore {
    private struct Chunk {
        let start: Int
        let samples: [Int16]
        let wallMs: Double
    }

    private var chunks: [Chunk] = []
    private var total = 0
    private let lock = NSLock()

    /// Index of the next sample to arrive.
    var end: Int { lock.withLock { total } }

    /// Oldest sample index still held.
    var first: Int { lock.withLock { chunks.first?.start ?? total } }

    func append(_ samples: [Int16], wallMs: Double) {
        guard !samples.isEmpty else { return }
        lock.withLock {
            chunks.append(Chunk(start: total, samples: samples, wallMs: wallMs))
            total += samples.count
        }
    }

    /// Drop whole chunks that end before `index`.
    func trim(before index: Int) {
        lock.withLock {
            while let c = chunks.first, c.start + c.samples.count <= index { chunks.removeFirst() }
        }
    }

    /// Samples [from, to), clamped to what's held.
    func slice(from: Int, to: Int) -> [Int16] {
        lock.withLock {
            let lo = max(from, chunks.first?.start ?? total)
            let hi = min(to, total)
            guard lo < hi else { return [] }
            var out = [Int16]()
            out.reserveCapacity(hi - lo)
            for c in chunks {
                let a = max(lo, c.start), b = min(hi, c.start + c.samples.count)
                if a < b { out.append(contentsOf: c.samples[(a - c.start)..<(b - c.start)]) }
            }
            return out
        }
    }

    /// Watch clock (Unix ms) of the sample at `index`, or nil if it's gone.
    func wallMs(at index: Int) -> Double? {
        lock.withLock {
            let i = max(index, chunks.first?.start ?? total)
            for c in chunks where i < c.start + c.samples.count {
                return c.wallMs + Double(i - c.start) / Double(Config.sampleRate) * 1000
            }
            return nil
        }
    }
}

/// 16-bit mono PCM -> a WAV file the backend's decode_wav reads.
enum WAV {
    static func encode(_ samples: [Int16], rate: Int = Config.sampleRate) -> Data {
        var d = Data()
        func put(_ s: String) { d.append(contentsOf: Array(s.utf8)) }
        func u32(_ v: UInt32) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        let bytes = UInt32(samples.count * 2)
        put("RIFF"); u32(36 + bytes); put("WAVE")
        put("fmt "); u32(16); u16(1); u16(1); u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
        put("data"); u32(bytes)
        d.reserveCapacity(d.count + Int(bytes))
        for s in samples { u16(UInt16(bitPattern: s)) }
        return d
    }
}

enum MicError: LocalizedError {
    case permissionDenied
    case noInput

    var errorDescription: String? {
        switch self {
        case .permissionDenied: return "trO needs the microphone. Allow it in the Watch app on your iPhone, or in Settings > Privacy on the watch."
        case .noInput: return "Couldn't start the microphone."
        }
    }
}

/// The watch microphone, converted to 16 kHz mono 16-bit (what the bracelet mic sends).
final class AudioCapture {
    let store = SampleStore()
    /// 0...1 loudness of the latest buffer, for the level meter.
    private(set) var level: Float = 0

    private let engine = AVAudioEngine()
    private var running = false

    static func requestPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioApplication.requestRecordPermission { cont.resume(returning: $0) }
        }
    }

    func start() async throws {
        guard !running else { return }
        guard await Self.requestPermission() else { throw MicError.permissionDenied }

        let session = AVAudioSession.sharedInstance()
        // .measurement turns off the system's voice processing and gain, which would
        // flatten the loud-me / quiet-them difference the server uses to tell speakers apart.
        try session.setCategory(.record, mode: .measurement, options: [])
        try session.setActive(true)

        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard inFormat.sampleRate > 0,
              let outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Double(Config.sampleRate), channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: inFormat, to: outFormat)
        else { throw MicError.noInput }

        input.installTap(onBus: 0, bufferSize: 4096, format: inFormat) { [weak self] buffer, _ in
            self?.handle(buffer, converter: converter, outFormat: outFormat)
        }
        engine.prepare()
        try engine.start()
        running = true
    }

    func stop() {
        guard running else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        running = false
        level = 0
    }

    private func handle(_ buffer: AVAudioPCMBuffer, converter: AVAudioConverter, outFormat: AVAudioFormat) {
        if let ch = buffer.floatChannelData?[0], buffer.frameLength > 0 {
            var sq: Float = 0
            for i in 0..<Int(buffer.frameLength) { sq += ch[i] * ch[i] }
            level = min(1, (sq / Float(buffer.frameLength)).squareRoot() * 4)
        }
        let ratio = outFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 64)
        guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed {
                status.pointee = .noDataNow
                return nil
            }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, out.frameLength > 0, let data = out.int16ChannelData?[0] else { return }
        let n = Int(out.frameLength)
        let samples = Array(UnsafeBufferPointer(start: data, count: n))
        let wallMs = Date().timeIntervalSince1970 * 1000 - Double(n) / Double(Config.sampleRate) * 1000
        store.append(samples, wallMs: wallMs)
    }
}
