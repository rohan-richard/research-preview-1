import Foundation

enum AppConfig {
    /// The Rumi API. Debug builds talk to the API on this Mac. Override with the
    /// launch argument `-rumi.apiURL https://…` (UI tests and TestFlight builds).
    static var apiBaseURL: URL {
        if let text = UserDefaults.standard.string(forKey: "rumi.apiURL"), let url = URL(string: text) { return url }
        #if DEBUG
        return URL(string: "http://localhost:8000")!
        #else
        return URL(string: "https://api.rumi.example")!
        #endif
    }
    /// The iOS-type OAuth client ID from the Google Cloud console. Empty until one exists.
    static let googleClientID = UserDefaults.standard.string(forKey: "rumi.googleClientID") ?? ""

    /// The patient portal that the chat server works in through this phone. Override with `-rumi.portalOrigin https://…`.
    /// The hosted AmalgamRx Hospitals demo portal needs a private access code (`-rumi.portalAccessCode …`) or a saved device
    /// sign-in, and `restore_session` is how the chat server asks this phone to use the saved sign-in.
    static var portalOrigin: URL {
        if let text = UserDefaults.standard.string(forKey: "rumi.portalOrigin"), let url = URL(string: text), url.host != nil { return url }
        return URL(string: "https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live")!
    }
    static var portalAccessCode: String? { UserDefaults.standard.string(forKey: "rumi.portalAccessCode") }
}
