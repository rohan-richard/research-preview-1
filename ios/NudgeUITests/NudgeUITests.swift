import XCTest

final class NudgeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        // The launch test runs in every orientation and can leave the simulator sideways.
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testOnboardingChoicesBackAndSkipReachTodayWithoutChat() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "NO", "-nudge.music", "NO", "-rumi.signedOut", "YES", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["onboarding.continue"].waitForExistence(timeout: 10))
        app.buttons["onboarding.continue"].tap()
        let scenario = app.buttons["onboarding.scenario.oncology"]
        XCTAssertTrue(scenario.waitForExistence(timeout: 5))
        scenario.tap()
        XCTAssertTrue(scenario.isSelected)
        app.buttons["onboarding.continue"].tap()
        XCTAssertTrue(app.buttons["onboarding.connectRecords"].waitForExistence(timeout: 5))
        app.buttons["onboarding.continue"].tap()
        XCTAssertTrue(app.buttons["onboarding.skip"].waitForExistence(timeout: 5))
        app.buttons["onboarding.back"].tap()
        app.buttons["onboarding.back"].tap()
        XCTAssertTrue(scenario.waitForExistence(timeout: 5))
        XCTAssertTrue(scenario.isSelected)
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.skip"].tap()
        XCTAssertTrue(app.buttons["tab.today"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["tab.care"].exists)
        XCTAssertTrue(app.buttons["tab.messages"].exists)
        XCTAssertTrue(app.buttons["tab.you"].exists)
        XCTAssertFalse(app.buttons["onboarding.continue"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Warm Today after short onboarding"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    @MainActor
    func testDemoConnectionNeedsBirthdayAndConsent() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "NO", "-nudge.music", "NO", "-rumi.signedOut", "YES", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["onboarding.continue"].waitForExistence(timeout: 10))
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.connectRecords"].tap()
        XCTAssertTrue(app.buttons["fasten.continue.0"].waitForExistence(timeout: 5))
        app.buttons["fasten.continue.0"].tap()
        XCTAssertTrue(app.staticTexts["fasten.error"].waitForExistence(timeout: 5))
        let birthday = app.buttons["fasten.sampleDOB"]
        // The pinned Confirm bar covers this button, and XCUITest still calls it hittable.
        app.swipeUp()
        birthday.tap()
        app.buttons["fasten.continue.0"].tap()
        XCTAssertTrue(app.buttons["fasten.continue.1"].waitForExistence(timeout: 5))
        let disabled = NSPredicate(format: "enabled == false")
        let waitForDisabled = XCTNSPredicateExpectation(predicate: disabled, object: app.buttons["fasten.continue.1"])
        XCTAssertEqual(XCTWaiter.wait(for: [waitForDisabled], timeout: 5), .completed)
        let consent = app.switches["fasten.consent"]
        XCTAssertTrue(consent.waitForExistence(timeout: 5))
        if !consent.isHittable { app.swipeUp() }
        consent.tap()
        XCTAssertTrue(app.buttons["fasten.continue.1"].isEnabled)
        app.buttons["fasten.continue.1"].tap()
        XCTAssertTrue(app.buttons["fasten.continue.3"].waitForExistence(timeout: 10))
        let image = XCTAttachment(screenshot: app.screenshot()); image.name = "Fasten demo import review"; image.lifetime = .keepAlways; add(image)
        app.buttons["fasten.continue.3"].tap()
        XCTAssertTrue(app.buttons["onboarding.connectRecords"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testFloatingRumiAndComposerSurviveClosing() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-rumi.signedOut", "YES", "-nudge.sound", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["rumi.floating"].waitForExistence(timeout: 10))
        app.buttons["tab.care"].tap()
        XCTAssertTrue(app.buttons["rumi.floating"].exists)
        app.buttons["rumi.floating"].tap()
        let composer = app.descendants(matching: .any)["chat.composer"]
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        composer.tap(); composer.typeText("A draft to keep")
        // Drafts persist between launches, so compare with what the box holds.
        let draft = composer.value as? String
        app.buttons["chat.close"].tap()
        app.buttons["rumi.floating"].tap()
        XCTAssertEqual(app.descendants(matching: .any)["chat.composer"].value as? String, draft)
    }

    @MainActor
    func testMedicationHelpKeepsSelectedContextWithoutSending() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "YES", "-nudge.pathway", "metabolic", "-nudge.music", "NO", "-rumi.signedOut", "YES", "-nudge.sound", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["tab.care"].waitForExistence(timeout: 10))
        app.buttons["tab.care"].tap()
        app.buttons["care.Meds & refills"].tap()
        let medication = app.buttons["medication.open.atorvastatin"]
        XCTAssertTrue(medication.waitForExistence(timeout: 5))
        for _ in 0..<4 where !medication.isHittable { app.swipeUp() }
        medication.tap()
        let help = app.buttons["Help me frame the question"]
        XCTAssertTrue(help.waitForExistence(timeout: 5))
        help.tap()
        XCTAssertTrue(app.buttons["chat.context.remove"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["chat.context.title"].label.localizedCaseInsensitiveContains("atorvastatin"))
        XCTAssertFalse(app.buttons["chat.stop"].exists)
        app.buttons["chat.context.remove"].tap()
        XCTAssertFalse(app.buttons["chat.context.remove"].exists)
        app.buttons["chat.close"].tap()
        XCTAssertTrue(help.waitForExistence(timeout: 5))
    }

    @MainActor
    func testClosingSignInDoesNotEnterApp() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "NO", "-nudge.music", "NO", "-rumi.signedOut", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["onboarding.signIn"].waitForExistence(timeout: 10))
        app.buttons["onboarding.signIn"].tap()
        XCTAssertTrue(app.buttons["signin.apple"].waitForExistence(timeout: 5))
        app.buttons["signin.close"].tap()
        XCTAssertTrue(app.buttons["onboarding.continue"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tab.today"].exists)
    }

    @MainActor
    func testWelcomePreviewDoesNotChangeActiveScenario() {
        let app = XCUIApplication()
        app.launchArguments = ["-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-rumi.signedOut", "YES", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["today.settings"].waitForExistence(timeout: 10))
        app.buttons["today.settings"].tap()
        let preview = app.buttons["settings.previewWelcome"]
        // Settings rows are built only when they scroll into view.
        for _ in 0..<6 where !preview.waitForExistence(timeout: 1) || !preview.isHittable { app.swipeUp() }
        XCTAssertTrue(preview.exists)
        preview.tap()
        XCTAssertTrue(app.buttons["onboarding.continue"].waitForExistence(timeout: 5))
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.scenario.oncology"].tap()
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.continue"].tap()
        app.buttons["onboarding.skip"].tap()
        let original = app.buttons["settings.scenario.metabolic"]
        XCTAssertTrue(original.waitForExistence(timeout: 5))
        XCTAssertTrue(original.isSelected)
    }
}
