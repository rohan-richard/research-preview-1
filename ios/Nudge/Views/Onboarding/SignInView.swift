import AuthenticationServices
import SwiftUI

/// Sign in with Apple or Google against the Rumi API. Opened from the welcome screen and from Settings.
struct SignInView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme

    @State private var busy = false
    @State private var errorText: String? = nil
    @State private var appleNonce = SignInNonce.random()

    var body: some View {
        ZStack {
            LivingGradientView()
            VStack(spacing: 0) {
                HStack {
                    Text("Rumi").font(NudgeType.display(32)).foregroundStyle(Theme.ink)
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark").font(.system(size: 16)).frame(width: 44, height: 44)
                    }
                    .foregroundStyle(Theme.ink)
                    .accessibilityLabel("Close sign-in")
                    .accessibilityIdentifier("signin.close")
                }
                .padding(.horizontal, 24).padding(.top, 8)
                VStack(spacing: 24) {
                    Text(model.api.user == nil ? "Sign in" : "Signed in")
                        .font(NudgeType.serif(30)).foregroundStyle(Theme.ink)
                    if let user = model.api.user { signedIn(user) } else { providers }
                    if let errorText {
                        Text(errorText)
                            .font(NudgeType.rounded(13)).foregroundStyle(Theme.gold)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("signin.error")
                    }
                }
                .padding(.horizontal, 24).padding(.top, 36)
                .frame(maxWidth: 540).frame(maxWidth: .infinity)
                Spacer()
            }
        }
    }

    private var providers: some View {
        VStack(spacing: 12) {
            SignInWithAppleButton(.signIn) { request in
                request.requestedScopes = [.fullName, .email]
                // Apple puts the hash in the ID token, so the hash is what the API compares.
                request.nonce = SignInNonce.sha256Hex(appleNonce)
            } onCompletion: { result in
                Task { await finishApple(result) }
            }
            .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
            .frame(height: 54)
            .clipShape(.rect(cornerRadius: 16))
            .accessibilityIdentifier("signin.apple")

            Button { Task { await startGoogle() } } label: {
                HStack(spacing: 10) {
                    Text("G").font(NudgeType.serif(20)).foregroundStyle(Theme.warm)
                    Text("Continue with Google")
                }
                .font(NudgeType.rounded(16, .semibold)).foregroundStyle(Theme.ink)
                .frame(maxWidth: .infinity, minHeight: 54)
                .background(Theme.surface, in: .rect(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Theme.edge, lineWidth: 1))
            }
            .buttonStyle(NudgeButtonStyle())
            .accessibilityIdentifier("signin.google")

            #if DEBUG
            Button("Developer sign-in") {
                Task { await run { try await model.api.devSignIn(email: "dev@rumi.local") } }
            }
            .font(NudgeType.rounded(14, .medium)).foregroundStyle(Theme.inkMuted).frame(minHeight: 44)
            .accessibilityIdentifier("signin.devContinue")
            #endif
        }
        .disabled(busy)
        .opacity(busy ? 0.6 : 1)
    }

    private func signedIn(_ user: RumiUser) -> some View {
        VStack(spacing: 12) {
            Text(user.email)
                .font(NudgeType.rounded(16, .semibold)).foregroundStyle(Theme.ink)
                .accessibilityIdentifier("signin.signedInAs")
            Button("Sign out") { Task { busy = true; await model.api.signOut(); busy = false } }
                .font(NudgeType.rounded(14, .semibold)).foregroundStyle(Theme.warm).frame(minHeight: 44)
                .accessibilityIdentifier("signin.signOut")
        }
        .disabled(busy)
    }

    private func finishApple(_ result: Result<ASAuthorization, Error>) async {
        if case .failure(let error) = result, (error as? ASAuthorizationError)?.code == .canceled { return }
        await run {
            let credential = try AppleCredential(try result.get())
            try await model.api.signIn(provider: "apple", idToken: credential.idToken, nonce: SignInNonce.sha256Hex(appleNonce),
                                       given: credential.given, family: credential.family)
        }
        appleNonce = SignInNonce.random()
    }

    private func startGoogle() async {
        await run {
            do {
                let google = try await GoogleSignIn(clientID: AppConfig.googleClientID).signIn()
                try await model.api.signIn(provider: "google", idToken: google.idToken, nonce: google.nonce)
            } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
                return
            }
        }
    }

    private func run(_ work: () async throws -> Void) async {
        busy = true
        errorText = nil
        defer { busy = false }
        do {
            try await work()
            if model.api.isSignedIn { Haptics.success() }
        } catch {
            errorText = error.localizedDescription
        }
    }
}
