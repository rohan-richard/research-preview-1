import SwiftUI

/// Four short patient-led steps, with optional AI suggestions that require selection before entering the brief.
struct VisitPrepView: View {
    @Environment(AppModel.self) private var model
    let appointmentID: UUID
    @State private var draft: AppointmentPrep? = nil
    @State private var suggestions: String = ""
    @State private var aiTask: Task<Void, Never>? = nil
    @State private var isGenerating: Bool = false
    @State private var aiError: String? = nil
    @State private var showAIConsent: Bool = false
    @State private var showDeliveryInfo: Bool = false
    @State private var generationID: UUID? = nil
    private var appointment: Appointment? { model.appointment(withID: appointmentID) }
    private var visitLine: String { guard let appointment else { return "" }; return "\(appointment.with) · \(appointment.date.formatted(date: .abbreviated, time: .shortened))" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Make this visit count.").font(NudgeType.display(30)).accessibilityIdentifier("prep.title")
                Text(visitLine).font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                if let appointment, appointment.status != .cancelled, let draft {
                    Picker("Preparation step", selection: Binding(get: { draft.step }, set: { self.draft?.step = $0; save() })) {
                        Text("Focus").tag(0); Text("Changes").tag(1); Text("Questions").tag(2); Text("Review").tag(3)
                    }.pickerStyle(.segmented).accessibilityIdentifier("prep.steps")
                    Text("Saved as you go · only for this visit").font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                    switch draft.step {
                    case 0:
                        section("What would make this visit useful?", hint: "One thing you'd like to understand, decide or get help with.", key: \.goal, id: "goal")
                        section("What would make getting care easier?", hint: "Time, cost, getting there, language, or someone you'd like with you. Optional.", key: \.practicalNeeds, id: "practical")
                    case 1:
                        section("What's changed since your last visit?", hint: "Symptoms, when they started, what helps or gets in the way. Use your own words.", key: \.changes, id: "changes")
                        section("Anything about your medicines?", hint: "Questions, side effects, missed doses or trouble getting a refill. Don't change a dose based on this app.", key: \.medicationConcerns, id: "medications")
                    case 2:
                        section("Your questions, in your order.", hint: "Put the most important question first.", key: \.questions, id: "questions")
                        if !model.guideItems.filter({ !$0.resolved }).isEmpty {
                            DisclosureGroup("Choose from your discussion guide") {
                                ForEach(model.guideItems.filter { !$0.resolved }) { question in
                                    Button(question.text) { appendQuestion(question.text) }.frame(minHeight: 44).multilineTextAlignment(.leading)
                                }
                            }
                        }
                        Button { showAIConsent = true } label: { Label("Think it through with Rumi", systemImage: "sparkles").frame(minHeight: 44) }
                            .disabled(isGenerating || !model.aiRouter.canSend).accessibilityIdentifier("prep.askAI")
                        Text("Using Rumi chat · see Settings → AI connection")
                            .font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                        if isGenerating {
                            HStack { ProgressView(); Text("Drafting possible questions…"); Spacer(); Button("Stop") { stopAI() } }
                                .font(NudgeType.rounded(13))
                        }
                        if let aiError { Text(aiError).font(NudgeType.rounded(13)).foregroundStyle(Theme.attention) }
                        if !suggestions.isEmpty && !isGenerating {
                            OrganicSurface {
                                VStack(alignment: .leading, spacing: 12) {
                                    Kicker(text: "AI suggestions · review before using")
                                    Text(suggestions).font(NudgeType.rounded(15)).textSelection(.enabled)
                                    Button("Add these to my questions") { appendQuestion(suggestions); suggestions = "" }.frame(minHeight: 44)
                                    Button("Not for me") { suggestions = "" }.frame(minHeight: 44)
                                }.padding(18)
                            }
                        }
                    default:
                        OrganicSurface {
                            Text(draft.brief(visit: visitLine)).font(NudgeType.rounded(15)).lineSpacing(5).textSelection(.enabled).padding(20)
                        }
                        if let date = draft.reviewedAt {
                            Label("Reviewed by you · \(date.formatted(date: .abbreviated, time: .shortened))", systemImage: "checkmark.circle")
                                .font(NudgeType.rounded(13)).foregroundStyle(Theme.warm)
                            ShareLink(item: draft.reviewedText ?? draft.brief(visit: visitLine)) { Label("Export reviewed brief", systemImage: "square.and.arrow.up").frame(minHeight: 44) }
                        } else {
                            Button("I've reviewed this brief") {
                                self.draft?.reviewedAt = .now
                                self.draft?.reviewedText = draft.brief(visit: visitLine)
                                save()
                            }.disabled(!draft.hasContent).frame(minHeight: 44).accessibilityIdentifier("prep.review")
                        }
                        Button("Send to care team") { showDeliveryInfo = true }.frame(minHeight: 44)
                        Text("Exporting opens the share sheet. It does not mean the care team received or reviewed your brief.")
                            .font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
                    }
                    if draft.step < 3 {
                        Button("Continue") { self.draft?.step += 1; save() }
                            .buttonStyle(.borderedProminent).controlSize(.large).tint(Theme.buttonFill).foregroundStyle(Theme.onAccent)
                            .accessibilityIdentifier("prep.continue")
                    }
                } else if appointment == nil || appointment?.status == .cancelled {
                    ContentUnavailableView("This visit isn't available for preparation", systemImage: "calendar", description: Text("Choose an available appointment. No other visit has been substituted."))
                }
            }.padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 180)
        }
        .foregroundStyle(Theme.ink).tint(Theme.warm).scrollDismissesKeyboard(.interactively)
        .onAppear { if draft == nil { draft = model.visitPreps[appointmentID.uuidString] ?? .init(appointmentID: appointmentID) } }
        .onDisappear { stopAI(); save() }
        .onChange(of: model.aiRouter.revision) { _, _ in stopAI(); suggestions = "" }
        .alert("Use AI for these questions?", isPresented: $showAIConsent) {
            Button("Draft suggestions") { generateQuestions() }
            Button("Not now", role: .cancel) { }
        } message: { Text("Using Rumi chat. Your entries on this visit-prep screen and the selected sample visit are sent to Rumi's chat server. Only use sample information in this demo. Suggestions aren't medical advice or part of your brief until you add them.") }
        .alert("EHR delivery isn't connected yet", isPresented: $showDeliveryInfo) {
            Button("OK", role: .cancel) { }
        } message: { Text("Nothing has been sent to \(appointment?.with ?? "your care team"). Keep or export the reviewed copy to bring to the visit.") }
    }

    private func section(_ title: String, hint: String, key: WritableKeyPath<AppointmentPrep, String>, id: String) -> some View {
        OrganicSurface {
            VStack(alignment: .leading, spacing: 12) {
                Text(title).font(NudgeType.serif(22))
                Text(hint).font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                TextField("Add a note…", text: Binding(get: { draft?[keyPath: key] ?? "" }, set: { value in
                    draft?[keyPath: key] = value
                    draft?.invalidateReview()
                    stopAI()
                    suggestions = ""
                    save()
                }), axis: .vertical)
                .lineLimit(3...9).font(NudgeType.rounded(16)).padding(14).background(Theme.raised, in: .rect(cornerRadius: 14))
                .accessibilityIdentifier("prep.\(id)")
            }.padding(18)
        }
    }
    private func appendQuestion(_ text: String) {
        stopAI()
        guard !(draft?.questions.contains(text) ?? false) else { return }
        guard var value = draft else { return }
        value.questions += (value.questions.isEmpty ? "" : "\n\n") + text
        value.invalidateReview()
        draft = value
        save()
    }
    private func save() { if let draft { model.savePrep(draft) } }
    private func stopAI() { generationID = nil; aiTask?.cancel(); aiTask = nil; isGenerating = false }
    private func generateQuestions() {
        guard let draft, appointment?.status != .cancelled, appointment != nil else { return }
        stopAI()
        suggestions = ""; aiError = nil; isGenerating = true
        let id = UUID(); generationID = id
        let input = draft.brief(visit: visitLine)
        aiTask = Task {
            do {
                let result = try await model.aiRouter.prepareVisit(input: input)
                try Task.checkCancellation()
                guard generationID == id else { return }
                suggestions = CompanionEngine.parse(result).text
                isGenerating = false
            } catch {
                guard generationID == id, !Task.isCancelled else { return }
                isGenerating = false
                aiError = "Suggestions couldn't load. Your notes are safe here; you can keep preparing without AI."
            }
        }
    }
}
