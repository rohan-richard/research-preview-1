import Foundation

@MainActor protocol RumiSocketConnecting: AnyObject {
    func open(url: URL) async throws
    func send(_ text: String) async throws
    func receive() async throws -> String
    func close()
}

/// Retains the native session, delegate and task; resume is never treated as an open handshake.
final class RumiSocketConnection: RumiSocketConnecting {
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var openWaiter: CheckedContinuation<Void, any Error>?
    private var openingTimeout: Task<Void, Never>?

    func open(url: URL) async throws {
        try Task.checkCancellation()
        let delegate = RumiSessionDelegate(onOpen: { [weak self] in
            Task { @MainActor in self?.finishOpening(error: nil) }
        }, onClose: { [weak self] in
            Task { @MainActor in self?.finishOpening(error: RumiConnectionError.disconnected) }
        })
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        config.urlCache = nil
        let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
        let task = session.webSocketTask(with: url)
        // Spoken replies arrive as base64 audio frames.
        task.maximumMessageSize = 4_194_304
        self.session = session
        socket = task
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                openWaiter = continuation
                openingTimeout = Task { [weak self] in
                    do {
                        try await Task.sleep(for: .seconds(15))
                        self?.finishOpening(error: RumiConnectionError.timeout)
                        self?.close()
                    } catch { }
                }
                task.resume()
            }
            try Task.checkCancellation()
        } onCancel: { Task { @MainActor in self.close() } }
    }

    private func finishOpening(error: (any Error)?) {
        openingTimeout?.cancel(); openingTimeout = nil
        let waiter = openWaiter; openWaiter = nil
        if let error { waiter?.resume(throwing: error) } else { waiter?.resume() }
    }

    func send(_ text: String) async throws {
        try Task.checkCancellation()
        guard let socket else { throw RumiConnectionError.disconnected }
        try await socket.send(.string(text))
        try Task.checkCancellation()
    }
    func receive() async throws -> String {
        guard let socket else { throw RumiConnectionError.disconnected }
        switch try await socket.receive() {
        case .string(let text): return text
        case .data(let data):
            guard let text = String(data: data, encoding: .utf8) else { throw RumiConnectionError.protocolMismatch }
            return text
        @unknown default: throw RumiConnectionError.protocolMismatch
        }
    }
    func close() {
        finishOpening(error: CancellationError())
        socket?.cancel(with: .goingAway, reason: nil)
        session?.invalidateAndCancel()
        socket = nil; session = nil
    }
}

/// Refuses redirects for HTTP and socket handshakes; never logs bearer values or raw server reasons.
nonisolated final class RumiSessionDelegate: NSObject, URLSessionWebSocketDelegate {
    private let onOpen: @Sendable () -> Void
    private let onClose: @Sendable () -> Void
    init(onOpen: @escaping @Sendable () -> Void = {}, onClose: @escaping @Sendable () -> Void = {}) {
        self.onOpen = onOpen; self.onClose = onClose
    }
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) { onOpen() }
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) { onClose() }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) { if error != nil { onClose() } }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
}
