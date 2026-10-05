import Foundation
import Testing
@testable import Nudge

@Suite(.serialized)
@MainActor struct PortalDeviceTests {
    private static let origin = URL(string: "https://portal.test")!
    private static let snapshotJSON = """
    {"url":"/portal/home","title":"Home","viewport":{"width":390,"height":664},"scroll":{"x":0,"y":120},"pageHeight":800,
     "elements":[{"ref":1,"role":"button","name":"Visits","tag":"button","type":"button","inViewport":true},
                 {"ref":2,"role":"link","name":"Schedule an Appointment","tag":"a","inViewport":true,"href":"/portal/schedule","context":"Dr. Lee\\nMay 3"},
                 {"ref":3,"role":"textbox","name":"Password","tag":"input","type":"password","inViewport":false},
                 {"ref":4,"role":"combobox","name":"Reason","tag":"select","inViewport":true,"options":["Follow-up","New problem"],"value":"Follow-up","disabled":true},
                 {"ref":5,"role":"textbox","name":"Access code","tag":"input","type":"text","value":"","inViewport":true}],
     "text":"# Home\\nWelcome, Priya","dialogs":["Session ends in 2 minutes"]}
    """

    private func request(_ name: String, _ args: [String: JSONValue] = [:], highlight: Int? = nil) -> RumiWireProtocol.ToolRequest {
        .init(id: "req-\(name)", name: name, args: args, highlight_ref: highlight)
    }

    private func device(confirmTimeout: Duration = .seconds(300)) -> RumiPortalDevice {
        RumiPortalDevice(origin: Self.origin, accessCode: nil, confirmTimeout: confirmTimeout)
    }

    private func waitUntil(_ condition: () -> Bool) async throws {
        let limit = Date.now.addingTimeInterval(2)
        while !condition() && Date.now < limit { try await Task.sleep(for: .milliseconds(10)) }
        #expect(condition())
    }

    @Test func requestsDecodeToActionsWithServerDefaults() throws {
        #expect(try PortalAction(request("open", ["path": .string("/portal/home")])) == .open(path: "/portal/home"))
        #expect(try PortalAction(request("close")) == .close)
        #expect(try PortalAction(request("confirm", ["summary": .string("Press \"Book\"")])) == .confirm(summary: "Press \"Book\""))
        #expect(try PortalAction(request("screenshot")) == .screenshot)
        #expect(try PortalAction(request("get_screenshot")) == .screenshot)
        #expect(try PortalAction(request("click", ["ref": .number(7), "consequential": .bool(true)])) == .click(ref: 7))
        #expect(try PortalAction(request("type_text", ["ref": .number(2), "text": .string("hi")])) == .typeText(ref: 2, text: "hi", clear: true))
        #expect(try PortalAction(request("type_text", ["ref": .number(2), "text": .string("hi"), "clear": .bool(false)])) == .typeText(ref: 2, text: "hi", clear: false))
        #expect(try PortalAction(request("select_option", ["ref": .number(4), "option": .string("Follow-up")])) == .selectOption(ref: 4, option: "Follow-up"))
        #expect(try PortalAction(request("scroll", ["direction": .string("up")])) == .scroll(direction: "up", ref: nil))
        #expect(try PortalAction(request("scroll", ["ref": .number(3)])) == .scroll(direction: "down", ref: 3))
        #expect(try PortalAction(request("go_back")) == .goBack)
        #expect(try PortalAction(request("navigate", ["path": .string("/portal/visits")])) == .navigate(path: "/portal/visits"))
        #expect(try PortalAction(request("wait", ["ms": .number(9000)])) == .wait(ms: 3000))
        #expect(try PortalAction(request("wait")) == .wait(ms: 500))
        #expect(try PortalAction(request("restore_session")) == .restoreSession)
        #expect(throws: PortalError.self) { try PortalAction(request("click")) }
        #expect(throws: PortalError.self) { try PortalAction(request("type_text", ["ref": .number(2)])) }
        #expect(throws: PortalError.self) { try PortalAction(request("read_cookies")) }
    }

    @Test func unknownNamesAndCredentialTypingAreRefusedWithTheRequestID() async throws {
        let device = device()
        let unknown = await device.handle(request("read_cookies"))
        #expect(unknown.id == "req-read_cookies" && !unknown.ok && unknown.error == "unknown tool read_cookies" && unknown.result == nil)
        #expect(!device.isPresented)

        let observation = try JSONDecoder().decode(PortalObservation.self, from: Data(Self.snapshotJSON.utf8))
        #expect(RumiPortalDevice.refusal(for: .typeText(ref: 3, text: "secret", clear: true), in: observation)?.contains("password") == true)
        #expect(RumiPortalDevice.refusal(for: .typeText(ref: 5, text: "1234", clear: true), in: observation)?.contains("password") == true)
        #expect(RumiPortalDevice.refusal(for: .typeText(ref: 1, text: "fine", clear: true), in: observation) == nil)
        #expect(RumiPortalDevice.refusal(for: .typeText(ref: 3, text: "secret", clear: true), in: nil) == nil)
        #expect(RumiPortalDevice.refusal(for: .navigate(path: "https://evil.example/portal/home"), in: observation) == "navigate takes a path, not a full URL")
        #expect(RumiPortalDevice.refusal(for: .navigate(path: "/admin"), in: observation)?.contains("/portal/") == true)
        #expect(RumiPortalDevice.refusal(for: .navigate(path: "/portal/visits"), in: observation) == nil)

        device.lastObservation = observation
        let typed = await device.handle(request("type_text", ["ref": .number(3), "text": .string("secret")], highlight: 3))
        #expect(typed.id == "req-type_text" && !typed.ok && typed.error?.contains("never types into password fields") == true)
        #expect(typed.result == nil && !device.isPresented)

        let notOpen = await device.handle(request("type_text", ["ref": .number(1), "text": .string("fine")]))
        #expect(notOpen.id == "req-type_text" && !notOpen.ok && notOpen.error == "The portal is not open.")
        guard case .object(let result) = try #require(notOpen.result), case .object(let page) = try #require(result["observation"]) else {
            Issue.record("the failed action should still carry an observation")
            return
        }
        #expect(page["text"] == .string("The portal is not open.") && page["elements"] == .array([]))
    }

    @Test func confirmWaitsForThePatientAndRepliesAllowOrDeny() async throws {
        let device = device()
        let allowTask = Task { await device.handle(request("confirm", ["summary": .string("Press \"Book\"\n\nDr. Lee · May 3")])) }
        try await waitUntil { device.pendingConfirm != nil }
        #expect(device.isPresented && device.pendingConfirm == .init(id: "req-confirm", summary: "Press \"Book\"\n\nDr. Lee · May 3"))
        device.respond(allowed: true)
        let allowed = await allowTask.value
        #expect(allowed.id == "req-confirm" && allowed.ok && allowed.result == .object(["allowed": .bool(true)]))
        #expect(device.pendingConfirm == nil && device.isPresented)

        let denyTask = Task { await device.handle(request("confirm", ["summary": .string("Press \"Cancel appointment\"")])) }
        try await waitUntil { device.pendingConfirm != nil }
        device.respond(allowed: false)
        let denied = await denyTask.value
        #expect(denied.ok && denied.result == .object(["allowed": .bool(false)]))
        #expect(device.pendingConfirm == nil)
    }

    @Test func cancelAllDeniesThePendingConfirmAndHidesTheSheet() async throws {
        let device = device()
        let task = Task { await device.handle(request("confirm", ["summary": .string("Press \"Submit\"")])) }
        try await waitUntil { device.pendingConfirm != nil }
        device.cancelAll()
        let reply = await task.value
        #expect(reply.id == "req-confirm" && reply.ok)
        #expect(reply.result == .object(["allowed": .bool(false), "reason": .string("Stopped by the patient.")]))
        #expect(!device.isPresented && device.pendingConfirm == nil)
    }

    @Test func confirmTimesOutAsNotAllowed() async throws {
        let device = device(confirmTimeout: .milliseconds(50))
        let reply = await device.handle(request("confirm", ["summary": .string("Press \"Submit\"")]))
        #expect(reply.ok && reply.result == .object(["allowed": .bool(false), "reason": .string("No answer from the patient.")]))
        #expect(device.pendingConfirm == nil)
    }

    @Test func closeHidesTheSheetAndKeepsTheWebView() async throws {
        let device = device()
        let confirm = Task { await device.handle(request("confirm", ["summary": .string("Press \"Submit\"")])) }
        try await waitUntil { device.pendingConfirm != nil }
        let closed = await device.handle(request("close"))
        #expect(closed.id == "req-close" && closed.ok && closed.error == nil)
        #expect(!device.isPresented && device.pendingConfirm == nil)
        let reply = await confirm.value
        #expect(reply.result == .object(["allowed": .bool(false), "reason": .string("The task ended.")]))
    }

    @Test func bridgeSnapshotMapsToTheServerObservation() throws {
        let observation = try JSONDecoder().decode(PortalObservation.self, from: Data(Self.snapshotJSON.utf8))
        #expect(observation.url == "/portal/home" && observation.title == "Home" && observation.pageHeight == 800)
        #expect(observation.viewport == .init(width: 390, height: 664) && observation.scroll == .init(x: 0, y: 120))
        #expect(observation.dialogs == ["Session ends in 2 minutes"] && observation.text == "# Home\nWelcome, Priya")
        #expect(observation.elements.count == 5)
        #expect(observation.elements[1].href == "/portal/schedule" && observation.elements[1].context == "Dr. Lee\nMay 3" && observation.elements[1].type == nil)
        #expect(observation.elements[2].type == "password" && observation.elements[2].inViewport == false)
        #expect(observation.elements[3].options == ["Follow-up", "New problem"] && observation.elements[3].disabled == true)

        let wire = try RumiWireProtocol.toolReply(.init(id: "r1", ok: true, result: .object(["observation": try JSONValue(observation)])))
        let sent = try #require(JSONSerialization.jsonObject(with: Data(wire.utf8)) as? [String: Any])
        let value = try #require(sent["value"] as? [String: Any])
        #expect(value["id"] as? String == "r1" && value["ok"] as? Bool == true)
        let page = try #require((value["result"] as? [String: Any])?["observation"] as? [String: Any])
        #expect(page["url"] as? String == "/portal/home" && page["pageHeight"] as? Int == 800)
        #expect((page["viewport"] as? [String: Int]) == ["width": 390, "height": 664])
        let elements = try #require(page["elements"] as? [[String: Any]])
        #expect(elements[2]["type"] as? String == "password" && elements[2]["ref"] as? Int == 3)
        #expect(elements[3]["options"] as? [String] == ["Follow-up", "New problem"])
        #expect(elements[0]["href"] == nil && elements[0]["context"] == nil)
        // Integers stay integers on the wire; the server validates ref as int.
        #expect(wire.range(of: #""ref":3[,}]"#, options: .regularExpression) != nil)

        let placeholder = try JSONValue(PortalObservation.placeholder(url: "/portal/home", note: "The page is still loading."))
        guard case .object(let fields) = placeholder else {
            Issue.record("placeholder should encode as an object")
            return
        }
        #expect(fields["url"] == .string("/portal/home") && fields["text"] == .string("The page is still loading."))
        #expect(fields["elements"] == .array([]) && fields["dialogs"] == .array([]) && fields["title"] == .string(""))
    }

    @Test func webViewStaysInsideThePortal() throws {
        func url(_ text: String) throws -> URL { try #require(URL(string: text)) }
        let hosted = try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live")
        #expect(PortalPolicy.allows(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/portal/visits?tab=past"), origin: hosted))
        #expect(PortalPolicy.allows(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/portal"), origin: hosted))
        #expect(!PortalPolicy.allows(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/portal/api/auth"), origin: hosted))
        #expect(!PortalPolicy.allows(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/admin"), origin: hosted))
        #expect(!PortalPolicy.allows(try url("https://evil.example/portal/home"), origin: hosted))
        #expect(!PortalPolicy.allows(try url("http://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/portal/home"), origin: hosted))
        #expect(PortalPolicy.allowsNavigation(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/~api/portal/api/auth/device-login/complete?code=x"), origin: hosted))
        #expect(PortalPolicy.allowsNavigation(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/~api/demo/native-access"), origin: hosted))
        #expect(!PortalPolicy.allowsNavigation(try url("https://3pxarh5thg13j2zk4f873-web-linden-portal.rork.live/~api/portal/api/auth/device-login"), origin: hosted))
        #expect(PortalPolicy.api(hosted, "auth/device-login").path == "/~api/portal/api/auth/device-login")
        #expect(PortalPolicy.api(Self.origin, "auth/device-login").path == "/portal/api/auth/device-login")
        #expect(PortalPolicy.allowsNavigation(try url("https://portal.test/portal/api/auth/device-login/complete?code=x"), origin: Self.origin))
        #expect(AppConfig.portalOrigin.host == hosted.host)
    }
}
