import SwiftUI

/// What the chat server needs to know before Rumi can chat. Health records and the phone fill in what they can.
struct AboutYouSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var form = AboutYouForm()
    @State private var allowChat = false
    @State private var filledFromRecords = false
    @State private var saving = false
    @State private var error: String? = nil

    private let genders = ["Female", "Male", "Non-binary", "Prefer not to say"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(filledFromRecords
                         ? "We filled in what your health records say. Check it and add the rest."
                         : "Rumi needs a few things about you before it can chat. You can change them later in Settings.")
                        .font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                }
                Section("You") {
                    TextField("First name", text: $form.firstName).textContentType(.givenName).accessibilityIdentifier("about.firstName")
                    TextField("Last name", text: $form.lastName).textContentType(.familyName)
                    TextField("What should Rumi call you?", text: $form.preferredName).textContentType(.nickname)
                    DatePicker("Date of birth", selection: $form.dateOfBirth, in: ...Date.now, displayedComponents: .date)
                    Picker("Gender", selection: $form.gender) {
                        Text("Choose").tag("")
                        ForEach(genders, id: \.self) { Text($0).tag($0) }
                    }.accessibilityIdentifier("about.gender")
                    TextField("City and state", text: $form.location).textContentType(.addressCityAndState).accessibilityIdentifier("about.location")
                }
                Section("Why Rumi") {
                    TextField("What do you do for work?", text: $form.profession).accessibilityIdentifier("about.profession")
                    TextField("What would you like help with?", text: $form.reason, axis: .vertical).lineLimit(2...4).accessibilityIdentifier("about.reason")
                }
                Section {
                    Toggle("Chat with Rumi's AI", isOn: $allowChat).accessibilityIdentifier("about.allowChat")
                } footer: {
                    Text("Rumi's AI reads what you write or say and answers you. You can turn this off in the Privacy Center.")
                }
                if let error {
                    Text(error).font(NudgeType.rounded(13)).foregroundStyle(Theme.attention).accessibilityIdentifier("about.error")
                }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle("About you").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Later") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(saving || !form.isComplete || !allowChat)
                        .accessibilityIdentifier("about.save")
                }
            }
            .task { await prefill() }
        }
    }

    private func prefill() async {
        if let saved: AboutYouProfile = try? await model.api.send(.get, "/v1/me/profile") { form.merge(saved) }
        if let patient: AboutYouProfile = try? await model.api.send(.get, "/v1/ehr/patient") {
            filledFromRecords = form.merge(patient)
        }
        if form.firstName.isEmpty { form.firstName = model.api.user?.displayName.components(separatedBy: " ").first ?? "" }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await model.completeAboutYou(form)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

nonisolated struct AboutYouProfile: Decodable {
    var firstName: String? = nil
    var lastName: String? = nil
    var preferredName: String? = nil
    var dateOfBirth: String? = nil
    var gender: String? = nil
    var location: String? = nil
    var profession: String? = nil
    var reason: String? = nil
}

struct AboutYouForm {
    var firstName = ""
    var lastName = ""
    var preferredName = ""
    var dateOfBirth = Calendar.current.date(byAdding: .year, value: -40, to: .now) ?? .now
    var hasDateOfBirth = false
    var gender = ""
    var location = ""
    var profession = ""
    var reason = ""

    var isComplete: Bool {
        [firstName, gender, location, profession, reason].allSatisfy { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    /// Fills only empty fields, so the patient's own answers win. True when anything was filled.
    @discardableResult
    mutating func merge(_ profile: AboutYouProfile) -> Bool {
        var filled = false
        func take(_ field: inout String, _ value: String?) {
            guard field.isEmpty, let value, !value.isEmpty else { return }
            field = value
            filled = true
        }
        take(&firstName, profile.firstName)
        take(&lastName, profile.lastName)
        take(&preferredName, profile.preferredName)
        take(&gender, profile.gender.map { $0.prefix(1).uppercased() + $0.dropFirst() })
        take(&location, profile.location)
        take(&profession, profile.profession)
        take(&reason, profile.reason)
        if !hasDateOfBirth, let text = profile.dateOfBirth, let date = LiveFormat.date(text) {
            dateOfBirth = date
            hasDateOfBirth = true
            filled = true
        }
        return filled
    }

    var body: [String: Any] {
        var body: [String: Any] = [
            "first_name": firstName.trimmingCharacters(in: .whitespaces),
            "date_of_birth": LiveFormat.day(dateOfBirth),
            "gender": gender,
            "location": location.trimmingCharacters(in: .whitespaces),
            "timezone": TimeZone.current.identifier,
            "profession": profession.trimmingCharacters(in: .whitespaces),
            "reason": reason.trimmingCharacters(in: .whitespaces),
        ]
        if !lastName.isEmpty { body["last_name"] = lastName }
        if !preferredName.isEmpty { body["preferred_name"] = preferredName }
        return body
    }
}
