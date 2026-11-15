import Foundation
import Security

/// A tap from GET /events/{id}/connections (only the fields the watch needs).
struct TapPerson: Decodable {
    let connectionId: Int?
    let name: String
    let bothConsented: Bool?
    let tappedAt: String
}

struct Pairing: Codable {
    let token: String
    let eventId: Int
    let eventName: String
    let firstName: String
}

struct APIError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }
}

/// The trO backend (backend/README.md). Every call is HTTPS with the person's login token.
enum API {
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private static func send(_ request: URLRequest, body: Data? = nil) async throws -> Data {
        let (data, response): (Data, URLResponse)
        do {
            if let body {
                (data, response) = try await URLSession.shared.upload(for: request, from: body)
            } else {
                (data, response) = try await URLSession.shared.data(for: request)
            }
        } catch {
            throw APIError(status: 0, message: "Can't reach trO. Check that your iPhone or Wi-Fi is nearby.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError(status: status, message: (detail ?? "Something went wrong (\(status)).").capitalizedFirst)
        }
        return data
    }

    private static func request(_ path: String, method: String = "GET", token: String? = nil) -> URLRequest {
        var r = URLRequest(url: Config.apiBase.appendingPathComponent(path))
        r.httpMethod = method
        r.timeoutInterval = 30
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return r
    }

    /// Trade the 6-digit code from the phone for a login token (POST /auth/watch).
    static func pair(code: String) async throws -> Pairing {
        var r = request("auth/watch", method: "POST")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body = try JSONSerialization.data(withJSONObject: ["code": code])
        return try decoder.decode(Pairing.self, from: try await send(r, body: body))
    }

    static func connections(eventId: Int, token: String) async throws -> [TapPerson] {
        try decoder.decode([TapPerson].self, from: try await send(request("events/\(eventId)/connections", token: token)))
    }

    /// One clip as a raw WAV body (POST /events/{id}/recordings). 403 = someone said no to recording.
    static func upload(eventId: Int, token: String, wav: Data, kind: String, connectionId: Int?, startedAtMs: Double?) async throws {
        var comps = URLComponents(url: Config.apiBase.appendingPathComponent("events/\(eventId)/recordings"), resolvingAgainstBaseURL: false)!
        var q = [URLQueryItem(name: "kind", value: kind)]
        if let connectionId { q.append(URLQueryItem(name: "connection_id", value: String(connectionId))) }
        if let startedAtMs { q.append(URLQueryItem(name: "started_at", value: String(Int(startedAtMs)))) }
        comps.queryItems = q
        var r = URLRequest(url: comps.url!)
        r.httpMethod = "POST"
        r.timeoutInterval = 60
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue("audio/wav", forHTTPHeaderField: "Content-Type")
        _ = try await send(r, body: wav)
    }
}

/// The pairing (login token included) lives in the Keychain, readable only on this
/// watch after it's been unlocked once, and never synced or backed up.
enum PairingStore {
    private static let service = "edu.usc.tro.watch"
    private static let account = "pairing"

    private static var base: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static func load() -> Pairing? {
        var q = base
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    static func save(_ pairing: Pairing) {
        clear()
        guard let data = try? JSONEncoder().encode(pairing) else { return }
        var q = base
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }

    static func clear() {
        SecItemDelete(base as CFDictionary)
    }
}

extension String {
    var capitalizedFirst: String {
        guard let head = first else { return self }
        return String(head).uppercased() + String(dropFirst())
    }
}
