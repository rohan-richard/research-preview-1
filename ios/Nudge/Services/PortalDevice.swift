import Foundation
import UIKit
import WebKit

/// Carries out chat-server tool requests inside the patient's own portal session, in a web view the patient watches.
@Observable final class RumiPortalDevice: RumiToolDevice {
    struct PendingConfirm: Equatable {
        let id: String
        let summary: String
    }

    let origin: URL
    private(set) var isPresented = false
    private(set) var pendingConfirm: PendingConfirm?
    private(set) var isLoading = false
    private(set) var loadError: String?
    private(set) var webView: WKWebView?
    var lastObservation: PortalObservation?

    private let confirmTimeout: Duration
    private let signIn: PortalDeviceSignIn
    private var accessCode: String?
    private var navigation: PortalNavigation?
    private var running: Task<RumiWireProtocol.ToolReply, Never>?
    private var confirmWaiter: CheckedContinuation<(Bool, String?), Never>?
    private var confirmDeadline: Task<Void, Never>?
    // The page as it looked when the patient tapped Allow; the next click refuses to run if it changed.
    private var approvedPage: PortalObservation?

    init(origin: URL = AppConfig.portalOrigin, accessCode: String? = AppConfig.portalAccessCode, confirmTimeout: Duration = .seconds(300)) {
        self.origin = origin
        self.accessCode = accessCode
        self.confirmTimeout = confirmTimeout
        signIn = PortalDeviceSignIn(origin: origin)
    }

    func handle(_ request: RumiWireProtocol.ToolRequest) async -> RumiWireProtocol.ToolReply {
        let task = Task { await self.run(request) }
        running = task
        defer { if running == task { running = nil } }
        return await task.value
    }

    func cancelAll() {
        resolveConfirm(allowed: false, reason: "Stopped by the patient.")
        running?.cancel()
        webView?.evaluateJavaScript("window.agentBridge?.stop?.()", completionHandler: nil)
        approvedPage = nil
        isPresented = false
    }

    /// The patient's answer to the confirm card.
    func respond(allowed: Bool) {
        resolveConfirm(allowed: allowed, reason: nil)
    }

    /// The patient swiped the sheet away. The task keeps running; the next action shows it again.
    func hide() {
        isPresented = false
    }

    func reload() {
        guard let webView else { return }
        loadError = nil
        let current = webView.url.flatMap { PortalPolicy.allows($0, origin: origin) ? $0 : nil }
        webView.load(request(for: current ?? origin.appending(path: "portal/home")))
    }

    static func refusal(for action: PortalAction, in observation: PortalObservation?) -> String? {
        switch action {
        case .typeText(let ref, _, _):
            guard let element = observation?.elements.first(where: { $0.ref == ref }) else { return nil }
            let credential = element.name.range(of: "username|password|access code", options: [.regularExpression, .caseInsensitive]) != nil
            guard element.type == "password" || (element.tag == "input" && credential) else { return nil }
            return "refused: the assistant never types into password fields; ask the patient to sign in"
        case .navigate(let path):
            return PortalPolicy.navigateProblem(path)
        default:
            return nil
        }
    }

    // MARK: Requests

    private func run(_ request: RumiWireProtocol.ToolRequest) async -> RumiWireProtocol.ToolReply {
        let action: PortalAction
        do { action = try PortalAction(request) } catch { return .init(id: request.id, ok: false, error: describe(error)) }
        switch action {
        case .open(let path):
            return await open(path: path, id: request.id)
        case .close:
            close()
            return .init(id: request.id, ok: true)
        case .confirm(let summary):
            return await confirm(summary, id: request.id)
        case .screenshot:
            return await screenshot(id: request.id)
        default:
            return await perform(action, highlight: request.highlight_ref, id: request.id)
        }
    }

    private func open(path: String, id: String) async -> RumiWireProtocol.ToolReply {
        let webView = ensureWebView()
        isPresented = true
        do {
            webView.load(request(for: try portalURL(path)))
            try await waitForLoad()
            try await settle()
            return await observed(ok: true, error: nil, id: id)
        } catch is CancellationError {
            return .init(id: id, ok: false, error: "Stopped by the patient.")
        } catch {
            return await observed(ok: false, error: describe(error), id: id)
        }
    }

    private func close() {
        resolveConfirm(allowed: false, reason: "The task ended.")
        approvedPage = nil
        isPresented = false
    }

    private func confirm(_ summary: String, id: String) async -> RumiWireProtocol.ToolReply {
        resolveConfirm(allowed: false, reason: "Replaced by a newer request.")
        pendingConfirm = PendingConfirm(id: id, summary: summary)
        approvedPage = nil
        isPresented = true
        let timeout = confirmTimeout
        confirmDeadline = Task { [weak self] in
            try? await Task.sleep(for: timeout)
            guard !Task.isCancelled else { return }
            self?.resolveConfirm(allowed: false, reason: "No answer from the patient.")
        }
        let (allowed, reason) = await withCheckedContinuation { confirmWaiter = $0 }
        if allowed { approvedPage = try? await bridge().snapshotWithRetry() }
        var result: [String: JSONValue] = ["allowed": .bool(allowed)]
        if let reason { result["reason"] = .string(reason) }
        return .init(id: id, ok: true, result: .object(result))
    }

    private func resolveConfirm(allowed: Bool, reason: String?) {
        confirmDeadline?.cancel()
        confirmDeadline = nil
        pendingConfirm = nil
        guard let waiter = confirmWaiter else { return }
        confirmWaiter = nil
        waiter.resume(returning: (allowed, reason))
    }

    private func screenshot(id: String) async -> RumiWireProtocol.ToolReply {
        do {
            let bridge = try bridge()
            let current = try await bridge.snapshotWithRetry()
            guard current.title != "Sign in", !current.elements.contains(where: { $0.type == "password" }) else {
                throw PortalError.refused("Sign-in screens are never sent to the assistant.")
            }
            let config = WKSnapshotConfiguration()
            config.snapshotWidth = 780
            config.afterScreenUpdates = true
            let image = try await bridge.webView.takeSnapshot(configuration: config)
            guard let jpeg = image.jpegData(compressionQuality: 0.6) else { throw PortalError.badResult("could not encode screenshot") }
            return .init(id: id, ok: true, result: .object(["jpeg_base64": .string(jpeg.base64EncodedString())]))
        } catch {
            return .init(id: id, ok: false, error: describe(error))
        }
    }

    private func perform(_ action: PortalAction, highlight: Int?, id: String) async -> RumiWireProtocol.ToolReply {
        if let refusal = Self.refusal(for: action, in: lastObservation) { return .init(id: id, ok: false, error: refusal) }
        var ok = true
        var errorText: String?
        do {
            let bridge = try bridge()
            isPresented = true
            if let highlight { try? await bridge.highlight(ref: highlight) }
            try Task.checkCancellation()
            switch action {
            case .click(let ref):
                let expected = expectedPage(for: ref)
                approvedPage = nil
                try await bridge.click(ref: ref, expected: expected)
            case .typeText(let ref, let text, let clear):
                try await bridge.typeText(ref: ref, text: text, clear: clear)
            case .selectOption(let ref, let option):
                try await bridge.selectOption(ref: ref, option: option)
            case .scroll(let direction, let ref):
                try await bridge.scroll(direction: direction, ref: ref)
            case .goBack:
                guard bridge.webView.canGoBack else { throw PortalError.refused("nothing to go back to") }
                bridge.webView.goBack()
                try await waitForLoad()
            case .navigate(let path):
                bridge.webView.load(URLRequest(url: try portalURL(path)))
                try await waitForLoad()
            case .wait(let ms):
                try await Task.sleep(for: .milliseconds(ms))
            case .restoreSession:
                try await signIn.restore(into: bridge.webView)
                try await waitForLoad()
            case .open, .close, .confirm, .screenshot:
                throw PortalError.badRequest("\(action) is not a page action")
            }
            try await settle()
        } catch is CancellationError {
            return .init(id: id, ok: false, error: "Stopped by the patient.")
        } catch {
            ok = false
            errorText = describe(error)
        }
        return await observed(ok: ok, error: errorText, id: id)
    }

    private func expectedPage(for ref: Int) -> Any {
        guard let approvedPage, let element = approvedPage.elements.first(where: { $0.ref == ref }) else { return NSNull() }
        return ["url": approvedPage.url, "text": approvedPage.text, "name": element.name]
    }

    private func observed(ok: Bool, error errorText: String?, id: String) async -> RumiWireProtocol.ToolReply {
        let observation: PortalObservation
        do {
            observation = try await bridge().snapshotWithRetry()
        } catch {
            observation = .placeholder(url: webView?.url?.path ?? "", note: loadError ?? (ok ? "The page is still loading." : describe(error)))
        }
        lastObservation = observation
        let value = try? JSONValue(observation)
        return .init(id: id, ok: ok, error: errorText, result: value.map { .object(["observation": $0]) })
    }

    private func describe(_ error: any Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    // MARK: Web view

    private static let bridgeScript: String = {
        guard let url = Bundle.main.url(forResource: "agent-bridge", withExtension: "js"),
              let source = try? String(contentsOf: url, encoding: .utf8) else {
            assertionFailure("agent-bridge.js is missing from the app bundle")
            return ""
        }
        return source
    }()

    private func ensureWebView() -> WKWebView {
        if let webView { return webView }
        let config = WKWebViewConfiguration()
        // Portal cookies stay inside WebKit's store. The app never reads them; the store keeps the login across launches.
        config.websiteDataStore = .default()
        // The portal hands its device sign-in token only to this app name.
        config.applicationNameForUserAgent = "CarePortalAssistant/1.0"
        config.userContentController.add(signIn, name: "careportal")
        config.userContentController.addUserScript(WKUserScript(source: Self.bridgeScript, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        let webView = WKWebView(frame: .zero, configuration: config)
        let navigation = PortalNavigation(device: self)
        webView.navigationDelegate = navigation
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        self.navigation = navigation
        self.webView = webView
        return webView
    }

    private func bridge() throws -> PortalBridge {
        guard let webView else { throw PortalError.notOpen }
        if let loadError { throw PortalError.refused(loadError) }
        guard let url = webView.url, PortalPolicy.allows(url, origin: origin) else {
            throw PortalError.refused("The assistant can only work inside the patient portal.")
        }
        return PortalBridge(webView: webView)
    }

    private func portalURL(_ path: String) throws -> URL {
        guard PortalPolicy.navigateProblem(path) == nil, let url = URL(string: path, relativeTo: origin)?.absoluteURL,
              PortalPolicy.allows(url, origin: origin) else {
            throw PortalError.refused("navigate is limited to paths under /portal/ on the portal origin")
        }
        return url
    }

    // The hosted demo portal admits a phone only after one POST with the private access code; the response sets the cookie.
    private func request(for url: URL) -> URLRequest {
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let accessCode {
            request.url = origin.appending(path: "~api/demo/native-access")
            request.httpMethod = "POST"
            request.setValue(accessCode, forHTTPHeaderField: "X-Demo-Key")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
        }
        return request
    }

    private func waitForLoad() async throws {
        try await Task.sleep(for: .milliseconds(150))
        for _ in 0..<32 {
            try Task.checkCancellation()
            if let loadError { throw PortalError.refused(loadError) }
            if webView?.isLoading == false { return }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw PortalError.timeout("page did not finish loading")
    }

    // The bridge is injected at document end, so right after a navigation it may not exist yet.
    private func settle() async throws {
        for _ in 0..<8 {
            try Task.checkCancellation()
            do { try await bridge().waitForSettle(); return } catch { try await Task.sleep(for: .milliseconds(250)) }
        }
    }

    fileprivate func loadStarted() {
        isLoading = true
        loadError = nil
    }

    fileprivate func loadFinished(url: URL?) {
        isLoading = false
        if let url, PortalPolicy.allows(url, origin: origin) { accessCode = nil }
    }

    fileprivate func loadFailed(status: Int) {
        isLoading = false
        loadError = status >= 500
            ? "The portal hosting service is not available right now (\(status)). Try again shortly."
            : "The portal could not open (\(status)). It may need the private access code or a sign-in."
    }

    fileprivate func loadFailed(_ error: any Error) {
        isLoading = false
        guard loadError == nil, (error as NSError).code != NSURLErrorCancelled else { return }
        loadError = "The portal could not be loaded. Check the connection and try again."
    }
}

// MARK: - Requests and page data

nonisolated enum PortalError: LocalizedError, Equatable {
    case notOpen
    case badRequest(String)
    case badResult(String)
    case refused(String)
    case timeout(String)

    var errorDescription: String? {
        switch self {
        case .notOpen: "The portal is not open."
        case .badRequest(let text): text
        case .badResult(let text): "unexpected result from page: \(text)"
        case .refused(let text): text
        case .timeout(let text): text
        }
    }
}

nonisolated enum PortalAction: Equatable {
    case open(path: String)
    case close
    case confirm(summary: String)
    case screenshot
    case click(ref: Int)
    case typeText(ref: Int, text: String, clear: Bool)
    case selectOption(ref: Int, option: String)
    case scroll(direction: String, ref: Int?)
    case goBack
    case navigate(path: String)
    case wait(ms: Int)
    case restoreSession

    init(_ request: RumiWireProtocol.ToolRequest) throws {
        let args = request.args
        func ref() throws -> Int {
            guard let value = args["ref"]?.intValue else { throw PortalError.badRequest("\(request.name) needs a ref") }
            return value
        }
        switch request.name {
        case "open": self = .open(path: args["path"]?.stringValue ?? "/portal/home")
        case "close": self = .close
        case "confirm": self = .confirm(summary: args["summary"]?.stringValue ?? "Continue")
        case "screenshot", "get_screenshot": self = .screenshot
        case "click": self = .click(ref: try ref())
        case "type_text":
            guard let text = args["text"]?.stringValue else { throw PortalError.badRequest("type_text needs text") }
            self = .typeText(ref: try ref(), text: text, clear: args["clear"]?.boolValue ?? true)
        case "select_option":
            guard let option = args["option"]?.stringValue else { throw PortalError.badRequest("select_option needs option") }
            self = .selectOption(ref: try ref(), option: option)
        case "scroll": self = .scroll(direction: args["direction"]?.stringValue ?? "down", ref: args["ref"]?.intValue)
        case "go_back": self = .goBack
        case "navigate": self = .navigate(path: args["path"]?.stringValue ?? "")
        case "wait": self = .wait(ms: min(max(args["ms"]?.intValue ?? 500, 0), 3000))
        case "restore_session": self = .restoreSession
        default: throw PortalError.refused("unknown tool \(request.name)")
        }
    }
}

/// The page as the bridge script reports it. Field names match backend/tools/portal_browser/observation.py.
nonisolated struct PortalObservation: Codable, Equatable {
    struct Element: Codable, Equatable {
        var ref: Int
        var role: String
        var name: String
        var tag: String
        var type: String? = nil
        var value: String? = nil
        var checked: Bool? = nil
        var pressed: Bool? = nil
        var selected: Bool? = nil
        var disabled: Bool? = nil
        var inViewport: Bool? = nil
        var options: [String]? = nil
        var href: String? = nil
        var context: String? = nil
    }
    struct Size: Codable, Equatable {
        var width: Int
        var height: Int
    }
    struct Point: Codable, Equatable {
        var x: Int
        var y: Int
    }

    var url: String
    var title: String
    var viewport: Size
    var scroll: Point
    var pageHeight: Int
    var elements: [Element]
    var text: String
    var dialogs: [String]

    static func placeholder(url: String, note: String) -> PortalObservation {
        PortalObservation(url: url, title: "", viewport: Size(width: 0, height: 0), scroll: Point(x: 0, y: 0),
                          pageHeight: 0, elements: [], text: note, dialogs: [])
    }
}

nonisolated extension JSONValue {
    init(_ value: some Encodable) throws {
        self = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    }
}

/// Which URLs the web view may show. Only portal pages, never the portal's own API, except the two sign-in hand-offs.
nonisolated enum PortalPolicy {
    static func allows(_ url: URL, origin: URL) -> Bool {
        let normalized = url.standardized
        return sameOrigin(normalized, origin)
            && (normalized.path == "/portal" || normalized.path.hasPrefix("/portal/"))
            && !normalized.path.hasPrefix("/portal/api")
    }

    static func allowsNavigation(_ url: URL, origin: URL) -> Bool {
        if allows(url, origin: origin) { return true }
        let normalized = url.standardized
        let handoffs = [(hosted(origin) ? "/~api" : "") + "/portal/api/auth/device-login/complete", "/~api/demo/native-access"]
        return sameOrigin(normalized, origin) && handoffs.contains(normalized.path)
    }

    static func api(_ origin: URL, _ path: String) -> URL {
        origin.appending(path: (hosted(origin) ? "~api/" : "") + "portal/api/" + path)
    }

    static func navigateProblem(_ path: String) -> String? {
        if path.contains("://") || path.hasPrefix("//") { return "navigate takes a path, not a full URL" }
        if path != "/portal" && !path.hasPrefix("/portal/") { return "navigate is limited to paths under /portal/ on the portal origin" }
        return nil
    }

    // The hosted demo mounts the portal API under /~api; a plain deployment serves it at the root.
    private static func hosted(_ origin: URL) -> Bool {
        origin.host?.hasSuffix(".rork.live") == true
    }

    private static func sameOrigin(_ url: URL, _ origin: URL) -> Bool {
        url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port && url.user == nil && url.password == nil
    }
}

// MARK: - Bridge script calls

private struct PortalBridge {
    let webView: WKWebView

    func snapshot() async throws -> PortalObservation {
        // Serialize on the JS side: handing WebKit's result object to JSONSerialization can raise an NSException.
        let raw = try await webView.callAsyncJavaScript("return JSON.stringify(await window.agentBridge.snapshot());",
                                                        arguments: [:], in: nil, contentWorld: .page)
        guard let json = raw as? String, let data = json.data(using: .utf8) else {
            throw PortalError.badResult("snapshot returned \(String(describing: raw).prefix(80))")
        }
        return try JSONDecoder().decode(PortalObservation.self, from: data)
    }

    func snapshotWithRetry(attempts: Int = 12) async throws -> PortalObservation {
        var lastError: any Error = PortalError.timeout("snapshot never became available")
        for _ in 0..<attempts {
            try Task.checkCancellation()
            do { return try await snapshot() } catch { lastError = error }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw lastError
    }

    func highlight(ref: Int) async throws {
        _ = try await call("highlight", [("ref", ref), ("ms", 400)])
    }

    func waitForSettle() async throws {
        _ = try await call("waitForSettle", [("opts", ["quietMs": 500, "timeoutMs": 5000])])
    }

    func click(ref: Int, expected: Any) async throws {
        _ = try await call("click", [("ref", ref), ("expected", expected)])
    }

    func typeText(ref: Int, text: String, clear: Bool) async throws {
        _ = try await call("typeText", [("ref", ref), ("text", text), ("clear", clear)])
    }

    func selectOption(ref: Int, option: String) async throws {
        _ = try await call("selectOption", [("ref", ref), ("option", option)])
    }

    func scroll(direction: String, ref: Int?) async throws {
        var arg: [String: Any] = ["direction": direction]
        if let ref { arg["ref"] = ref }
        _ = try await call("scroll", [("arg", arg)])
    }

    // The JS side catches errors and returns them as text, because WebKit otherwise
    // collapses every exception into "A JavaScript exception occurred".
    private func call(_ function: String, _ ordered: [(String, Any)]) async throws -> Any? {
        let params = ordered.map(\.0).joined(separator: ", ")
        let body = """
        try {
          const value = await window.agentBridge.\(function)(\(params));
          return JSON.stringify({ ok: true, value: value === undefined ? null : value });
        } catch (e) {
          return JSON.stringify({ ok: false, error: String((e && e.message) || e) });
        }
        """
        let raw = try await webView.callAsyncJavaScript(body, arguments: Dictionary(uniqueKeysWithValues: ordered), in: nil, contentWorld: .page)
        guard let json = raw as? String, let data = json.data(using: .utf8),
              let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw PortalError.badResult("\(function) returned \(String(describing: raw).prefix(80))")
        }
        if result["ok"] as? Bool != true {
            throw PortalError.refused(result["error"] as? String ?? "\(function) failed")
        }
        return result["value"]
    }
}

private final class PortalNavigation: NSObject, WKNavigationDelegate {
    private weak var device: RumiPortalDevice?

    init(device: RumiPortalDevice) {
        self.device = device
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let device, let url = action.request.url, PortalPolicy.allowsNavigation(url, origin: device.origin) else {
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, let http = response.response as? HTTPURLResponse, http.statusCode >= 400 {
            device?.loadFailed(status: http.statusCode)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        device?.loadStarted()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        device?.loadFinished(url: webView.url)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: any Error) {
        device?.loadFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) {
        device?.loadFailed(error)
    }
}

/// The saved device sign-in for one portal origin. After a manual sign-in the portal page posts a token to the
/// `careportal` handler; `restore` trades that token for a one-time login code and loads it. No password is involved.
final class PortalDeviceSignIn: NSObject, WKScriptMessageHandler {
    private let origin: URL
    private let service = "app.rumi.portal"
    private var account: String { "device:" + origin.absoluteString }

    init(origin: URL) {
        self.origin = origin
    }

    nonisolated func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.frameInfo.isMainFrame, let pageURL = message.frameInfo.request.url, PortalPolicy.allows(pageURL, origin: origin),
                  let body = message.body as? [String: Any], body["type"] as? String == "device_token",
                  let token = body["token"] as? String, !token.isEmpty else { return }
            Keychain.write(token, key: account, service: service)
        }
    }

    func restore(into webView: WKWebView) async throws {
        guard let token = Keychain.read(account, service: service) else {
            throw PortalError.refused("No saved sign-in on this phone. Ask the patient to sign in.")
        }
        var request = URLRequest(url: PortalPolicy.api(origin, "auth/device-login"))
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["token": token])
        // A separate session: the token exchange never sees the web view's cookies.
        let (data, response) = try await URLSession(configuration: .ephemeral).data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        if http.statusCode == 401 || http.statusCode == 403 {
            Keychain.delete(account, service: service)
            throw PortalError.refused("The saved sign-in expired. Ask the patient to sign in again.")
        }
        guard http.statusCode == 200, let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let code = json["code"] as? String,
              var parts = URLComponents(url: PortalPolicy.api(origin, "auth/device-login/complete"), resolvingAgainstBaseURL: false) else {
            throw PortalError.refused("The portal could not restore the sign-in. Ask the patient to sign in.")
        }
        parts.queryItems = [URLQueryItem(name: "code", value: code), URLQueryItem(name: "next", value: "/portal/home")]
        guard let url = parts.url else { throw URLError(.badURL) }
        webView.load(URLRequest(url: url))
    }
}
