import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            LivingGradientView()

            if model.hasOnboarded {
                RootView()
                    .transition(.opacity.combined(with: .scale(scale: 1.02)))
            } else {
                OnboardingFlowView()
                    .transition(.opacity)
            }
        }
        .animation(NudgeSpring.gentle, value: model.hasOnboarded)
        .task {
            await model.api.restoreSession()
            await model.signedInUserChanged()
        }
        .onChange(of: model.api.user?.id) { Task { await model.signedInUserChanged() } }
        .sheet(isPresented: Binding(get: { model.needsAboutYou && model.hasOnboarded }, set: { model.needsAboutYou = $0 })) {
            AboutYouSheet().presentationBackground(Theme.base)
        }
        .onAppear {
            // Stone Kintsugi carries the world; Barley Thunder owns onboarding.
            if model.hasOnboarded {
                SoundEngine.shared.playBed(.ambient, fade: 3.0)
            }
        }
    }
}
