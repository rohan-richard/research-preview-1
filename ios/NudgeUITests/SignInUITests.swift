import XCTest

/// Needs the Rumi API on http://localhost:8000 with DEV_SIGN_IN=1.
final class SignInUITests: XCTestCase {
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
    func testDeveloperSignInSurvivesRelaunchAndSignsOut() {
        let app = XCUIApplication()
        app.launchArguments = ["-rumi.signedOut", "YES", "-nudge.hasOnboarded", "NO", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()

        // A session left over from an earlier run is ended first.
        if app.buttons["onboarding.signedInAs"].waitForExistence(timeout: 4) {
            app.buttons["onboarding.signedInAs"].tap()
            app.buttons["signin.signOut"].tap()
            XCTAssertTrue(app.buttons["signin.apple"].waitForExistence(timeout: 5))
            app.buttons["signin.close"].tap()
        }

        XCTAssertTrue(app.buttons["onboarding.signIn"].waitForExistence(timeout: 10))
        app.buttons["onboarding.signIn"].tap()
        XCTAssertTrue(app.buttons["signin.apple"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["signin.google"].exists)
        snapshot(app, "1-sign-in-sheet")
        app.buttons["signin.devContinue"].tap()

        let signedIn = app.buttons["onboarding.signedInAs"]
        let error = app.staticTexts["signin.error"]
        XCTAssertTrue(signedIn.waitForExistence(timeout: 20), error.exists ? error.label : "no sign-in result")
        // The sheet stays open in its signed-in state until closed.
        XCTAssertTrue(app.staticTexts["signin.signedInAs"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["signin.signedInAs"].label, "dev@rumi.local")
        snapshot(app, "2-signed-in")
        app.buttons["signin.close"].tap()
        XCTAssertEqual(signedIn.label, "Signed in as dev@rumi.local")
        snapshot(app, "3-welcome-signed-in")

        app.terminate()
        // Relaunch without the signed-out option, so the stored sign-in is kept.
        app.launchArguments = ["-nudge.hasOnboarded", "NO", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(signedIn.waitForExistence(timeout: 10))
        XCTAssertEqual(signedIn.label, "Signed in as dev@rumi.local")

        signedIn.tap()
        XCTAssertTrue(app.buttons["signin.signOut"].waitForExistence(timeout: 5))
        app.buttons["signin.signOut"].tap()
        XCTAssertTrue(app.buttons["signin.apple"].waitForExistence(timeout: 5))
        app.buttons["signin.close"].tap()
        XCTAssertTrue(app.buttons["onboarding.signIn"].waitForExistence(timeout: 5))
    }
}
