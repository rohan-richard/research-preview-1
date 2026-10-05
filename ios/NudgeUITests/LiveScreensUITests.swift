import XCTest

/// Walks the main screens as the signed-in test patient and keeps a screenshot of each.
final class LiveScreensUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = true
        // The launch test runs in every orientation and can leave the simulator sideways.
        XCUIDevice.shared.orientation = .portrait
    }

    private func snapshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func back(_ app: XCUIApplication) {
        let button = app.navigationBars.buttons.firstMatch
        if button.waitForExistence(timeout: 2) { button.tap() }
        sleep(1)
    }

    @MainActor
    func testSignedInScreensShowRealData() {
        let app = XCUIApplication()
        app.launchArguments = ["-rumi.signedOut", "YES", "-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["rumi.floating"].waitForExistence(timeout: 10))
        app.buttons["rumi.floating"].tap()
        app.buttons["chat.aiConnection"].tap()
        app.buttons["ai.connection.signIn"].tap()
        let devContinue = app.buttons["signin.devContinue"]
        XCTAssertTrue(devContinue.waitForExistence(timeout: 5))
        for _ in 0..<3 where !app.staticTexts["signin.signedInAs"].exists {
            devContinue.tap()
            _ = app.staticTexts["signin.signedInAs"].waitForExistence(timeout: 10)
        }
        app.buttons["signin.close"].tap()
        app.buttons["ai.connection.close"].tap()
        app.buttons["chat.close"].tap()
        sleep(6)

        app.buttons["tab.care"].tap()
        sleep(1)
        snapshot(app, "1-care")
        for (tile, name) in [("care.Records & results", "2-records"), ("care.Meds & refills", "4-meds"), ("care.Appointments", "5-visits"), ("care.Care plan", "5b-care-plan")] {
            let button = app.buttons[tile]
            guard button.waitForExistence(timeout: 5) else { continue }
            button.tap()
            sleep(2)
            snapshot(app, name)
            if name == "2-records" {
                for _ in 0..<3 { app.swipeUp() }
                snapshot(app, "3-records-lower")
            }
            back(app)
        }

        for (row, name) in [("Conditions", "5c-conditions"), ("Care team", "5e-care-team")] {
            let button = app.staticTexts[row].firstMatch
            guard button.waitForExistence(timeout: 3) else { continue }
            button.tap()
            sleep(2)
            snapshot(app, name)
            back(app)
        }

        app.buttons["tab.today"].tap()
        sleep(2)
        snapshot(app, "5d-today")

        app.buttons["tab.you"].tap()
        sleep(1)
        snapshot(app, "6-you")
        let journeys = app.buttons["you.journeys"]
        if journeys.waitForExistence(timeout: 3) {
            journeys.tap()
            sleep(2)
            snapshot(app, "7-journeys")
            back(app)
        }

        app.buttons["tab.today"].tap()
        let settings = app.buttons["today.settings"]
        if settings.waitForExistence(timeout: 5) {
            settings.tap()
            let privacy = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Privacy Center'")).firstMatch
            for _ in 0..<6 where !privacy.isHittable { app.swipeUp() }
            privacy.tap()
            sleep(3)
            for _ in 0..<4 { app.swipeUp() }
            snapshot(app, "8-privacy")
        }
    }
}
