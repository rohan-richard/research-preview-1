import XCTest

/// Needs the Rumi API on http://localhost:8000 with DEV_SIGN_IN=1 and a FooClinic connection on dev@rumi.local.
final class RecordsUITests: XCTestCase {
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

    private func signInIfNeeded(_ app: XCUIApplication) {
        app.buttons["rumi.floating"].tap()
        app.buttons["chat.aiConnection"].tap()
        XCTAssertTrue(app.staticTexts["ai.connection.title"].waitForExistence(timeout: 5))
        if app.buttons["ai.connection.signIn"].waitForExistence(timeout: 2) {
            app.buttons["ai.connection.signIn"].tap()
            XCTAssertTrue(app.buttons["signin.devContinue"].waitForExistence(timeout: 5))
            app.buttons["signin.devContinue"].tap()
            XCTAssertTrue(app.staticTexts["signin.signedInAs"].waitForExistence(timeout: 10))
            app.buttons["signin.close"].tap()
        }
        app.buttons["ai.connection.close"].tap()
        app.buttons["chat.close"].tap()
    }

    @MainActor
    func testRecordsCardShowsTheRealConnectionAndOpensTheFastenWidget() {
        let app = XCUIApplication()
        app.launchArguments = ["-rumi.signedOut", "YES", "-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["rumi.floating"].waitForExistence(timeout: 10))
        signInIfNeeded(app)

        app.buttons["tab.care"].tap()
        let tile = app.buttons["care.Records & results"]
        XCTAssertTrue(tile.waitForExistence(timeout: 5))
        tile.tap()

        let connect = app.buttons["records.connect"]
        for _ in 0..<8 where !connect.exists || !connect.isHittable { app.swipeUp() }
        XCTAssertTrue(connect.waitForExistence(timeout: 10))
        let card = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'FooClinic'")).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15), "the FooClinic connection should be listed")
        let counts = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'conditions'")).firstMatch
        XCTAssertTrue(counts.waitForExistence(timeout: 10))
        snapshot(app, "1-records-card")

        connect.tap()
        XCTAssertTrue(app.buttons["records.connect.close"].waitForExistence(timeout: 5))
        if app.buttons["records.consent.allow"].waitForExistence(timeout: 3) { app.buttons["records.consent.allow"].tap() }
        let share = app.webViews.buttons["Share Records"]
        XCTAssertTrue(share.waitForExistence(timeout: 30), "the Fasten widget should load inside the sheet")
        snapshot(app, "2-connect-sheet-widget")
        share.tap()
        let search = app.webViews.textFields.firstMatch
        if search.waitForExistence(timeout: 15) {
            search.tap()
            search.typeText("FooClinic")
            let foo = app.webViews.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'FooClinic'")).firstMatch
            _ = foo.waitForExistence(timeout: 15)
        }
        snapshot(app, "3-widget-search")
        app.buttons["records.connect.close"].tap()
    }
}
