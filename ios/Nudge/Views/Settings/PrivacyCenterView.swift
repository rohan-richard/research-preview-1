import SwiftUI

/// Radical transparency, made touchable. What the companion remembers is not
/// a database list — it's a constellation of big words you can hold. Tap a
/// realm and its memories cascade in as glass chips; pop any of them and
/// it's actually gone; teach it something new from the same breath.
struct PrivacyCenterView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL

    @State private var realm: MemoryRealm = .health
    @State private var exported = false
    @State private var confirmingDelete = false
    @State private var exporting = false
    @State private var dataError: String? = nil
    @State private var newMemory = ""
    @FocusState private var addFocused: Bool

    var body: some View {
        ZStack {
            LivingGradientView()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Privacy Center")
                            .font(NudgeType.display(32))
                            .foregroundStyle(Theme.ink)
                        Text("This is your brain. Take it anywhere.")
                            .font(NudgeType.rounded(13.5))
                            .foregroundStyle(Theme.inkMuted)
                    }
                    .padding(.top, 8)

                    constellation

                    memoryChips

                    addRow

                    // The four lenses personalization actually uses.
                    lensesCard

                    // Consent ledger
                    sectionCard("Consent ledger") {
                        VStack(spacing: 4) {
                            ForEach(model.consents) { consent in
                                consentRow(consent)
                            }
                        }
                    }

                    // Sources with freshness
                    sectionCard("Connected sources") {
                        VStack(spacing: 9) {
                            ForEach(model.sources) { source in
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(source.name)
                                            .font(NudgeType.rounded(13.5, .medium))
                                            .foregroundStyle(Theme.ink)
                                        Text(source.railLabel)
                                            .font(NudgeType.rounded(11))
                                            .foregroundStyle(Theme.inkMuted)
                                    }
                                    Spacer()
                                    FreshnessChip(date: source.lastSync)
                                }
                                .padding(.vertical, 4)
                            }
                            ForEach(model.profile.connectedSystems, id: \.self) { system in
                                HStack {
                                    Text(system)
                                        .font(NudgeType.rounded(13.5, .medium))
                                        .foregroundStyle(Theme.ink)
                                    Spacer()
                                    FreshnessChip(date: .now)
                                }
                                .padding(.vertical, 4)
                            }
                        }
                    }

                    // Data rights
                    sectionCard("Your data, your rules") {
                        VStack(spacing: 11) {
                            if exported {
                                Label("Export ready. It opened in your browser and includes everything Rumi keeps about you.", systemImage: "checkmark")
                                    .font(NudgeType.rounded(13, .medium))
                                    .foregroundStyle(Theme.life)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .accessibilityIdentifier("privacy.exported")
                            } else {
                                Button {
                                    Task { await export() }
                                } label: {
                                    Text(exporting ? "Preparing your export…" : "Export everything")
                                        .font(NudgeType.rounded(14.5, .semibold))
                                        .foregroundStyle(Theme.ink)
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 13)
                                        .capsuleGlass()
                                }
                                .buttonStyle(NudgeButtonStyle())
                                .disabled(exporting)
                                .accessibilityIdentifier("privacy.export")
                            }
                            if let dataError {
                                Text(dataError).font(NudgeType.rounded(12.5)).foregroundStyle(Theme.attention)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .accessibilityIdentifier("privacy.error")
                            }

                            Button {
                                confirmingDelete = true
                            } label: {
                                Text("Delete my account & data")
                                    .font(NudgeType.rounded(14.5, .medium))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                            .buttonStyle(NudgeButtonStyle())
                            .confirmationDialog(
                                "This erases everything — your story, your garden, what I've learned. It cannot be undone.",
                                isPresented: $confirmingDelete,
                                titleVisibility: .visible
                            ) {
                                Button("Delete everything", role: .destructive) {
                                    Task { await deleteEverything() }
                                }
                                Button("Keep my story", role: .cancel) {}
                            }
                        }
                    }
                }
                .padding(.horizontal, 22)
                .padding(.bottom, 50)
            }
            .scrollIndicators(.hidden)
        }
        .toolbarBackground(.hidden, for: .navigationBar)
    }

    // MARK: The constellation — realms as big words you can hold

    enum MemoryRealm: String, CaseIterable {
        case health = "Health"
        case rhythms = "Rhythms"
        case life = "Life"
        case care = "Care"

        var accent: Color {
            switch self {
            case .health: return Theme.life
            case .rhythms: return Theme.gold
            case .life: return Theme.rose
            case .care: return Theme.sky
            }
        }

        /// Routes a remembered line into its realm.
        static func realm(for text: String) -> MemoryRealm {
            let lower = text.lowercased()
            if ["a1c", "bp", "blood", "med", "dose", "symptom", "pain", "nausea", "kidney", "spicy", "food", "diet", "intoleran"].contains(where: lower.contains) {
                return .health
            }
            if ["evening", "morning", "time", "shift", "week", "rhythm", "after 7", "schedule", "sleep"].contains(where: lower.contains) {
                return .rhythms
            }
            if ["dr.", "doctor", "visit", "clinic", "team", "appointment", "program", "enrolled", "nurse"].contains(where: lower.contains) {
                return .care
            }
            return .life
        }
    }

    private func items(in realm: MemoryRealm) -> [MemoryItem] {
        model.memory.filter { MemoryRealm.realm(for: $0.text) == realm }
    }

    private var constellation: some View {
        VStack(alignment: .leading, spacing: 2) {
            Kicker(text: "What I remember about you")
            FlowingWords(
                realms: MemoryRealm.allCases.map { ($0, items(in: $0).count) },
                selected: realm
            ) { chosen in
                Haptics.tick()
                SoundEngine.shared.tick()
                withAnimation(NudgeSpring.delight) { realm = chosen }
            }
        }
    }

    /// The chips of the chosen realm — glass, poppable, actually deletable.
    private var memoryChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            let chips = items(in: realm)
            if chips.isEmpty {
                Text("Nothing held here yet — tell me below and I'll carry it.")
                    .font(NudgeType.rounded(13))
                    .foregroundStyle(Theme.inkMuted)
                    .padding(.vertical, 8)
            }
            ForEach(chips) { item in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(realm.accent.opacity(0.8))
                        .frame(width: 6, height: 6)
                        .padding(.top, 7)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.text)
                            .font(NudgeType.rounded(13.5))
                            .foregroundStyle(Theme.ink)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(item.learnedFrom)
                            .font(NudgeType.rounded(10.5))
                            .foregroundStyle(Theme.inkMuted)
                    }
                    Spacer()
                    Button {
                        Haptics.tick()
                        SoundEngine.shared.tick()
                        withAnimation(NudgeSpring.ui) { model.deleteMemory(item.id) }
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Theme.inkMuted.opacity(0.8))
                            .frame(width: 24, height: 24)
                            .background(.ultraThinMaterial, in: .circle)
                    }
                    .buttonStyle(NudgeButtonStyle())
                    .accessibilityLabel("Forget this")
                }
                .padding(.horizontal, 13)
                .padding(.vertical, 10)
                .background(.ultraThinMaterial, in: .rect(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .strokeBorder(realm.accent.opacity(0.3), lineWidth: 0.8)
                )
                .transition(.scale(scale: 0.85).combined(with: .opacity))
            }
        }
        .animation(NudgeSpring.ui, value: realm)
        .animation(NudgeSpring.ui, value: model.memory)
    }

    private var addRow: some View {
        HStack(spacing: 9) {
            TextField("Tell me something to remember…", text: $newMemory)
                .font(NudgeType.rounded(13.5))
                .focused($addFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(Theme.surface.opacity(0.92), in: .capsule)
                .overlay(Capsule().strokeBorder(Theme.edge.opacity(0.55), lineWidth: 0.8))
                .onSubmit(addMemory)

            Button(action: addMemory) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Theme.base)
                    .frame(width: 38, height: 38)
                    .background(Theme.ink.opacity(newMemory.isEmpty ? 0.35 : 1), in: .circle)
            }
            .buttonStyle(NudgeButtonStyle())
            .disabled(newMemory.isEmpty)
            .accessibilityLabel("Remember it")
        }
    }

    private func addMemory() {
        let text = newMemory.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        withAnimation(NudgeSpring.delight) {
            model.addMemoryNote(text, from: "You told me directly")
            realm = MemoryRealm.realm(for: text)
        }
        newMemory = ""
    }

    // MARK: Lenses

    private struct Lens: Identifiable {
        let id = UUID()
        let glyph: String
        let title: String
        let value: String
        let accent: Color
    }

    private var lenses: [Lens] {
        [
            Lens(glyph: "clock", title: "Best time", value: "Evenings, after 7", accent: Theme.gold),
            Lens(glyph: "bubble", title: "Tone", value: model.tonePreference, accent: Theme.sky),
            Lens(glyph: "heart", title: "The why", value: "Family-first framing", accent: Theme.rose),
            Lens(glyph: "metronome", title: "Rhythm", value: "Games & shift weeks", accent: Theme.life),
        ]
    }

    private var lensesCard: some View {
        OrganicSurface(radius: 32) {
            VStack(alignment: .leading, spacing: 12) {
                Kicker(text: "What personalization actually uses")
                Text("Four lenses. That's the whole machine — and every one is yours to turn off.")
                    .font(NudgeType.rounded(12.5))
                    .foregroundStyle(Theme.inkMuted)

                LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
                          spacing: 10) {
                    ForEach(lenses) { lens in
                        VStack(alignment: .leading, spacing: 6) {
                            Image(systemName: lens.glyph)
                                .font(.system(size: 14, weight: .light))
                                .foregroundStyle(lens.accent)
                                .frame(width: 30, height: 30)
                                .background(lens.accent.opacity(0.14), in: .circle)
                            Text(lens.title)
                                .font(NudgeType.rounded(11.5, .semibold))
                                .foregroundStyle(Theme.inkMuted)
                            Text(lens.value)
                                .font(NudgeType.serif(14))
                                .foregroundStyle(Theme.ink)
                                .lineLimit(2)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(
                            LinearGradient(colors: [lens.accent.opacity(0.1), lens.accent.opacity(0.02)],
                                           startPoint: .topLeading, endPoint: .bottomTrailing),
                            in: .rect(cornerRadius: 20, style: .continuous)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 20, style: .continuous)
                                .strokeBorder(lens.accent.opacity(0.25), lineWidth: 0.9)
                        )
                    }
                }

                Toggle(isOn: Binding(
                    get: { model.epsilonConsent },
                    set: { model.epsilonConsent = $0 }
                )) {
                    Text("Use my everyday rhythms for kinder timing")
                        .font(NudgeType.rounded(13.5))
                        .foregroundStyle(Theme.ink)
                }
                .tint(Theme.life)
                .padding(.top, 4)

                Text("Nothing here is used to advertise to you. Ever.")
                    .font(NudgeType.rounded(11.5))
                    .foregroundStyle(Theme.inkMuted)
            }
            .padding(17)
        }
    }

    private func consentRow(_ consent: ConsentEntry) -> some View {
        Toggle(isOn: bindingFor(consent)) {
            VStack(alignment: .leading, spacing: 2) {
                Text(consent.source)
                    .font(NudgeType.rounded(13.5, .medium))
                    .foregroundStyle(Theme.ink)
                Text(consent.scope)
                    .font(NudgeType.rounded(11))
                    .foregroundStyle(Theme.inkMuted)
            }
        }
        .tint(Theme.life)
        .padding(.vertical, 6)
    }

    private func bindingFor(_ consent: ConsentEntry) -> Binding<Bool> {
        Binding(
            get: { model.consents.first(where: { $0.id == consent.id })?.granted ?? false },
            set: { newValue in
                if let index = model.consents.firstIndex(where: { $0.id == consent.id }) {
                    model.consents[index].granted = newValue
                    if consent.source.contains("Epsilon") {
                        model.epsilonConsent = newValue
                    }
                    if let scope = consent.apiScope, model.isLive {
                        Task {
                            do {
                                try await model.setConsentLive(scope, granted: newValue)
                                dataError = nil
                            } catch {
                                if let index = model.consents.firstIndex(where: { $0.id == consent.id }) { model.consents[index].granted = !newValue }
                                dataError = "That change was not saved. \(error.localizedDescription)"
                            }
                        }
                    }
                }
            }
        )
    }

    private func export() async {
        guard model.isLive else {
            withAnimation(NudgeSpring.ui) { exported = true }
            return
        }
        exporting = true
        defer { exporting = false }
        do {
            let link = try await model.requestExport()
            openURL(link)
            dataError = nil
            withAnimation(NudgeSpring.ui) { exported = true }
        } catch {
            dataError = error.localizedDescription
        }
    }

    private func deleteEverything() async {
        guard model.isLive else {
            PersistenceService.wipe()
            return
        }
        do {
            try await model.deleteAccount()
            dataError = nil
        } catch {
            dataError = "Your account was not deleted. \(error.localizedDescription)"
        }
    }

    private func sectionCard(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        OrganicSurface(radius: 30) {
            VStack(alignment: .leading, spacing: 12) {
                Kicker(text: title)
                content()
            }
            .padding(17)
        }
    }
}

/// Big serif realm-words drifting in a loose spatial cluster — the selected
/// one swells; counts ride as superscripts. The reference made data feel
/// like a place, not a table.
private struct FlowingWords: View {
    let realms: [(PrivacyCenterView.MemoryRealm, Int)]
    let selected: PrivacyCenterView.MemoryRealm
    var onSelect: (PrivacyCenterView.MemoryRealm) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: -6) {
            row(words: Array(realms.prefix(2)), indentFirst: false)
            row(words: Array(realms.dropFirst(2)), indentFirst: true)
        }
        .padding(.vertical, 6)
    }

    private func row(words: [(PrivacyCenterView.MemoryRealm, Int)], indentFirst: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 22) {
            if indentFirst { Spacer().frame(width: 26) }
            ForEach(words, id: \.0) { realm, count in
                wordButton(realm: realm, count: count)
            }
            Spacer()
        }
    }

    private func wordButton(realm: PrivacyCenterView.MemoryRealm, count: Int) -> some View {
        let active = realm == selected
        return Button {
            onSelect(realm)
        } label: {
            HStack(alignment: .top, spacing: 3) {
                Text(realm.rawValue)
                    .font(NudgeType.display(active ? 40 : 26))
                    .foregroundStyle(active ? Theme.ink : Theme.inkMuted.opacity(0.75))
                Text("\(count)")
                    .font(NudgeType.number(13, .semibold))
                    .foregroundStyle(realm.accent)
                    .padding(.top, active ? 6 : 3)
            }
            .shadow(color: active ? realm.accent.opacity(0.35) : .clear, radius: 14)
        }
        .buttonStyle(NudgeButtonStyle())
        .animation(NudgeSpring.delight, value: selected)
        .accessibilityLabel("\(realm.rawValue), \(count) memories")
        .accessibilityAddTraits(active ? .isSelected : [])
    }
}
