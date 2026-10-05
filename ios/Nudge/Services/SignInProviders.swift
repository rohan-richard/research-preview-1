import AuthenticationServices
import CryptoKit
import Foundation
import UIKit

nonisolated enum SignInNonce {
    static func random() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    static func sha256Hex(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func base64URL(_ digest: SHA256.Digest) -> String {
        Data(digest).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

nonisolated struct AppleCredential {
    let idToken: String
    let given: String?
    let family: String?

    init(_ authorization: ASAuthorization) throws {
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let data = credential.identityToken, let token = String(data: data, encoding: .utf8) else {
            throw RumiAPIError.badResponse
        }
        idToken = token
        given = credential.fullName?.givenName
        family = credential.fullName?.familyName
    }
}

/// Google's OpenID Connect flow in the system browser sheet, with PKCE. No SDK needed.
/// Needs an iOS-type OAuth client ID from the Google Cloud console.
final class GoogleSignIn: NSObject {
    struct Outcome {
        let idToken: String
        let nonce: String
    }

    private let clientID: String

    init(clientID: String) {
        self.clientID = clientID
    }

    // 123-abc.apps.googleusercontent.com becomes com.googleusercontent.apps.123-abc
    private var redirectScheme: String {
        clientID.split(separator: ".").reversed().joined(separator: ".")
    }

    private var redirectURI: String { "\(redirectScheme):/oauth2redirect" }

    func signIn() async throws -> Outcome {
        guard !clientID.isEmpty else {
            throw RumiAPIError.api(status: 0, code: "google_not_configured", message: "Google sign-in needs an iOS client ID in AppConfig.")
        }
        let nonce = SignInNonce.random()
        let verifier = SignInNonce.random()
        var parts = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
        parts.queryItems = [
            .init(name: "client_id", value: clientID),
            .init(name: "redirect_uri", value: redirectURI),
            .init(name: "response_type", value: "code"),
            .init(name: "scope", value: "openid email profile"),
            .init(name: "nonce", value: nonce),
            .init(name: "code_challenge", value: SignInNonce.base64URL(SHA256.hash(data: Data(verifier.utf8)))),
            .init(name: "code_challenge_method", value: "S256"),
        ]
        let callback = try await authenticate(parts.url!)
        guard let code = URLComponents(url: callback, resolvingAgainstBaseURL: false)?
            .queryItems?.first(where: { $0.name == "code" })?.value else { throw RumiAPIError.badResponse }
        return Outcome(idToken: try await exchange(code: code, verifier: verifier), nonce: nonce)
    }

    private func authenticate(_ url: URL) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: redirectScheme) { callback, error in
                if let callback { continuation.resume(returning: callback) }
                else { continuation.resume(throwing: error ?? RumiAPIError.badResponse) }
            }
            session.presentationContextProvider = self
            session.start()
        }
    }

    private func exchange(code: String, verifier: String) async throws -> String {
        var form = URLComponents()
        form.queryItems = [
            .init(name: "code", value: code),
            .init(name: "client_id", value: clientID),
            .init(name: "redirect_uri", value: redirectURI),
            .init(name: "code_verifier", value: verifier),
            .init(name: "grant_type", value: "authorization_code"),
        ]
        var request = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data((form.percentEncodedQuery ?? "").utf8)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw RumiAPIError.badResponse }
        struct Token: Decodable { let id_token: String }
        return try JSONDecoder().decode(Token.self, from: data).id_token
    }
}

extension GoogleSignIn: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
                .flatMap(\.windows).first { $0.isKeyWindow } ?? ASPresentationAnchor()
        }
    }
}
