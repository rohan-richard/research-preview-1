import XCTest

/// Drives the real Fasten widget inside the app's connect sheet with the FooClinic sandbox.
/// Needs the Rumi API on http://localhost:8000 with Fasten test keys and the webhook tunnel up.
final class RecordsConnectUITests: XCTestCase {
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

    private func tapPoint(_ app: XCUIApplication, _ x: CGFloat, _ y: CGFloat) {
        app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: x, dy: y)).tap()
    }

    @MainActor
    func testConnectFooClinicInsideTheApp() {
        let app = XCUIApplication()
        app.launchArguments = ["-rumi.signedOut", "YES", "-nudge.hasOnboarded", "YES", "-nudge.music", "NO", "-nudge.sound", "NO", "-nudge.pathway", "metabolic"]
        app.launch()
        XCTAssertTrue(app.buttons["rumi.floating"].waitForExistence(timeout: 10))
        app.buttons["rumi.floating"].tap()
        app.buttons["chat.aiConnection"].tap()
        XCTAssertTrue(app.staticTexts["ai.connection.title"].waitForExistence(timeout: 5))
        if app.buttons["ai.connection.signIn"].waitForExistence(timeout: 2) {
            app.buttons["ai.connection.signIn"].tap()
            let devContinue = app.buttons["signin.devContinue"]
            XCTAssertTrue(devContinue.waitForExistence(timeout: 5))
            for _ in 0..<3 where !app.staticTexts["signin.signedInAs"].exists {
                devContinue.tap()
                _ = app.staticTexts["signin.signedInAs"].waitForExistence(timeout: 10)
            }
            XCTAssertTrue(app.staticTexts["signin.signedInAs"].exists)
            app.buttons["signin.close"].tap()
        }
        app.buttons["ai.connection.close"].tap()
        app.buttons["chat.close"].tap()

        app.buttons["tab.care"].tap()
        let tile = app.buttons["care.Records & results"]
        XCTAssertTrue(tile.waitForExistence(timeout: 5))
        tile.tap()
        let connect = app.buttons["records.connect"]
        for _ in 0..<8 where !connect.exists || !connect.isHittable { app.swipeUp() }
        XCTAssertTrue(connect.waitForExistence(timeout: 10))
        connect.tap()
        XCTAssertTrue(app.buttons["records.connect.close"].waitForExistence(timeout: 5))
        if app.buttons["records.consent.allow"].waitForExistence(timeout: 3) { app.buttons["records.consent.allow"].tap() }

        let share = app.webViews.buttons["Share Records"]
        for _ in 0..<3 where !share.waitForExistence(timeout: 25) {
            let retry = app.buttons["records.stitch.retry"]
            if retry.waitForExistence(timeout: 5) { retry.tap() }
        }
        XCTAssertTrue(share.exists, "the Fasten widget should load")
        share.tap()
        sleep(4)
        snapshot(app, "1-widget-open")

        // The widget is a cross-origin frame, so touch it by position: the search box sits under the banner and logo.
        // The search box sits in Fasten's cross-origin frame and is not in the accessibility tree,
        // so tap it by position. The widget can re-render once after loading, so check the keyboard twice.
        for _ in 0..<3 {
            for _ in 0..<10 where !app.keyboards.firstMatch.exists { tapPoint(app, 170, 355); sleep(2) }
            sleep(2)
            if app.keyboards.firstMatch.exists { break }
        }
        app.typeText("FooClinic")
        sleep(4)
        snapshot(app, "2-search-fooclinic")

        // Tap the FooClinic row itself (a text tap only focuses it), then the portal's sign-in entry.
        tapPoint(app, 196, 444)
        sleep(5)
        snapshot(app, "3-after-pick")
        // The brand page lists its portals; the "+" on "FooClinic (Sandbox)" starts the sign-in popup.
        tapPoint(app, 336, 566)
        sleep(8)
        snapshot(app, "4-portal-step")
        // The selected portal now shows a "Sign in" button; it opens FooClinic's sign-in page in a popup.
        let portalSignIn = app.webViews.buttons["Sign in"]
        _ = portalSignIn.waitForExistence(timeout: 5)
        let opened = app.webViews["records.stitch.popup"]
        for _ in 0..<4 where !opened.exists {
            if portalSignIn.exists { press(portalSignIn) } else { tapPoint(app, 317, 445) }
            _ = opened.waitForExistence(timeout: 8)
        }
        sleep(4)
        snapshot(app, "4b-after-sign-in-tap")

        // FooClinic's sign-in page, in the popup the widget opened. Its fields name the sandbox in their placeholders.
        let username = app.webViews.textFields.matching(NSPredicate(format: "placeholderValue CONTAINS[c] 'fooclinic' OR placeholderValue CONTAINS[c] 'email' OR label CONTAINS[c] 'email'")).firstMatch
        XCTAssertTrue(username.waitForExistence(timeout: 30), "the health system sign-in should open inside the sheet")
        let popup = app.webViews["records.stitch.popup"]
        for _ in 0..<6 where username.frame.maxY > popup.frame.maxY - 40 { popup.swipeUp(); sleep(1) }
        for _ in 0..<5 where !focused(username) { press(username); sleep(2) }
        username.typeText("johndoe@fooclinic.com")
        // The keyboard and the username suggestions move the page, so find the password box again after they settle.
        sleep(2)
        let secure = app.webViews.secureTextFields.firstMatch
        XCTAssertTrue(secure.waitForExistence(timeout: 5))
        // A tap on the password box leaves the cursor in the username box (its suggestion list holds focus),
        // so move with the keyboard bar's "next field" arrow.
        let next = app.toolbars.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'next'")).firstMatch
        if next.exists { next.tap() } else { tapPoint(app, 67, 830) }
        sleep(2)
        app.typeText("f00clinic")
        snapshot(app, "5-sign-in-filled")
        let signIn = app.webViews.buttons["Sign In"]
        XCTAssertTrue(signIn.waitForExistence(timeout: 5))
        for _ in 0..<4 where signIn.frame.maxY > popup.frame.maxY - 40 { popup.swipeUp(); sleep(1) }
        press(signIn)
        sleep(6)
        snapshot(app, "5b-after-sign-in")
        let authorize = app.webViews.buttons["Authorize Access"]
        XCTAssertTrue(authorize.waitForExistence(timeout: 30))
        for _ in 0..<6 where authorize.frame.maxY > app.webViews["records.stitch"].frame.maxY - 40 { app.webViews["records.stitch"].swipeUp(); sleep(1) }
        snapshot(app, "6-authorize")
        press(authorize)
        sleep(8)
        snapshot(app, "6b-after-authorize")

        // Back on the widget's list, FooClinic is now signed in; "Continue" finishes and sends widget.complete.
        let finish = app.webViews.buttons["Continue"]
        if finish.waitForExistence(timeout: 10) { press(finish) } else { tapPoint(app, 310, 710) }
        sleep(4)
        snapshot(app, "6c-after-continue")
        // The success page's own Close button is what makes the widget send widget.complete.
        let widgetClose = app.webViews.buttons["Close"]
        if widgetClose.waitForExistence(timeout: 10) { press(widgetClose) } else { tapPoint(app, 196, 578) }

        let done = app.buttons["records.connect.done"]
        XCTAssertTrue(done.waitForExistence(timeout: 90), app.staticTexts["records.connect.error"].exists ? app.staticTexts["records.connect.error"].label : "no connection saved")
        snapshot(app, "7-importing")
        // A rerun on the same test patient reconnects a system the account already has.
        let imported = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Your records are in' OR label CONTAINS 'already in Rumi'")).firstMatch
        XCTAssertTrue(imported.waitForExistence(timeout: 180), "the import should finish")
        snapshot(app, "8-imported")
        done.tap()
    }

    // Elements inside the widget's popup report "not hittable" even when they are on screen, so tap their center.
    private func focused(_ element: XCUIElement) -> Bool {
        (element.value(forKey: "hasKeyboardFocus") as? Bool) ?? false
    }

    private func press(_ element: XCUIElement) {
        element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }
}
