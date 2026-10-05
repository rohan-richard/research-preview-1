import XCTest

/// Needs the Rumi API on http://localhost:8000 with DEV_SIGN_IN=1 and the chat server it points at.
final class BackendChatUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        // The launch test runs in every orientation and can leave the simulator sideways.
        XCUIDevice.shared.orientation = .portrait
    }

    private func snapshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    func testSignedInBackendModeGetsARealReply() {
        let app = XCUIApplication()
        app.launchArguments = ["-rumi.signedOut", "YES", "-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["rumi.floating"].waitForExistence(timeout: 10))
        app.buttons["rumi.floating"].tap()
        app.buttons["chat.aiConnection"].tap()
        XCTAssertTrue(app.staticTexts["ai.connection.title"].waitForExistence(timeout: 5))

        let signIn = app.buttons["ai.connection.signIn"]
        if signIn.waitForExistence(timeout: 2) {
            signIn.tap()
            XCTAssertTrue(app.buttons["signin.devContinue"].waitForExistence(timeout: 5))
            app.buttons["signin.devContinue"].tap()
            XCTAssertTrue(app.staticTexts["signin.signedInAs"].waitForExistence(timeout: 10))
            app.buttons["signin.close"].tap()
        }
        XCTAssertTrue(app.staticTexts["ai.connection.account"].waitForExistence(timeout: 5))

        app.buttons["ai.connection.close"].tap()
        XCTAssertFalse(app.buttons["chat.backendSetup"].waitForExistence(timeout: 2))

        // A multi-line TextField is exposed as a text view on iOS 26.
        let composer = app.descendants(matching: .any).matching(identifier: "chat.composer").firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        composer.tap()
        composer.typeText("What is one small thing I could try this week?")
        app.buttons["chat.send"].tap()

        let reply = app.staticTexts.matching(identifier: "chat.response").firstMatch
        XCTAssertTrue(reply.waitForExistence(timeout: 90))
        let settled = NSPredicate(format: "exists == false")
        let stopGone = expectation(for: settled, evaluatedWith: app.buttons["chat.stop"])
        wait(for: [stopGone], timeout: 90)
        XCTAssertFalse(app.staticTexts["chat.interrupted"].exists, "the reply was interrupted or failed")
        let text = app.staticTexts.matching(identifier: "chat.response").allElementsBoundByIndex.last?.label ?? ""
        XCTAssertGreaterThan(text.count, 10, "expected a real reply, got: \(text)")
        snapshot(app, "backend-chat-reply")
    }
}
