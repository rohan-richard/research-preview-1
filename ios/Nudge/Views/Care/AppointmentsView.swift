import SwiftUI

/// Appointments — what's coming, where you are in the plan it advances, and a
/// frictionless path to the room (or the call). Telehealth join only unlocks
/// inside a sensible pre-window (APT-6).
struct AppointmentsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Appointments")
                        .font(NudgeType.serif(28))
                        .foregroundStyle(Theme.ink)
                    Text(model.isLive ? "What is coming up, and the visits in your health records." : "Everything coming up, and how to get there easily.")
                        .font(NudgeType.rounded(13))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.top, 8)

                HStack(spacing: 20) {
                    NavigationLink("Discussion guide", value: YouDestination.guide)
                    NavigationLink("Visit reports", value: CareDestination.reports)
                }
                .font(NudgeType.rounded(13, .medium))
                .foregroundStyle(Theme.inkMuted)
                .frame(minHeight: 44)

                ForEach(upcoming) { appointment in
                    NavigationLink(value: CareDestination.appointmentDetail(appointment.id)) {
                        AppointmentRow(appointment: appointment)
                    }
                    .buttonStyle(NudgeButtonStyle())
                }
                if !past.isEmpty {
                    Text("Past visits")
                        .font(NudgeType.rounded(13, .semibold)).foregroundStyle(Theme.inkMuted)
                        .padding(.top, 8)
                    ForEach(past) { appointment in
                        NavigationLink(value: CareDestination.appointmentDetail(appointment.id)) {
                            AppointmentRow(appointment: appointment)
                        }
                        .buttonStyle(NudgeButtonStyle())
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
    }

    private var upcoming: [Appointment] {
        model.appointments.filter { $0.status != .visited }.sorted { $0.date < $1.date }
    }

    private var past: [Appointment] {
        model.appointments.filter { $0.status == .visited }.sorted { $0.date > $1.date }
    }
}

/// A single upcoming visit, calm and legible — date stone, who, where, and the
/// kind/status as quiet chips.
struct AppointmentRow: View {
    let appointment: Appointment

    var body: some View {
        OrganicSurface(radius: 28) {
            HStack(alignment: .top, spacing: 14) {
                DateStone(date: appointment.date)
                VStack(alignment: .leading, spacing: 5) {
                    Text(appointment.with)
                        .font(NudgeType.serif(17))
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(appointment.location)
                        .font(NudgeType.rounded(12.5))
                        .foregroundStyle(Theme.inkMuted)
                        .lineLimit(2)
                    HStack(spacing: 6) {
                        KindChip(kind: appointment.kind)
                        StatusChip(status: appointment.status)
                        if appointment.prepReady {
                            HStack(spacing: 3) {
                                Image(systemName: "sparkles")
                                    .font(.system(size: 8.5, weight: .semibold))
                                Text("Visit prep")
                                    .font(NudgeType.rounded(10.5, .medium))
                            }
                            .foregroundStyle(Theme.warm)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Theme.warm.opacity(0.12), in: .capsule)
                        }
                    }
                    .padding(.top, 1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .light))
                    .foregroundStyle(Theme.inkMuted)
                    .padding(.top, 4)
            }
            .padding(16)
        }
    }
}

/// A small calendar "stone" — month + day, warm and tactile.
struct DateStone: View {
    let date: Date

    var body: some View {
        VStack(spacing: 1) {
            Text(date.formatted(.dateTime.month(.abbreviated)).uppercased())
                .font(NudgeType.rounded(10, .semibold))
                .foregroundStyle(Theme.warm)
            Text(date.formatted(.dateTime.day()))
                .font(NudgeType.serif(22))
                .foregroundStyle(Theme.ink)
        }
        .frame(width: 52, height: 56)
        .background(Theme.base.opacity(0.7), in: .rect(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Theme.edge.opacity(0.6), lineWidth: 0.8)
        )
    }
}

struct KindChip: View {
    let kind: AppointmentKind
    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: kind.glyph)
                .font(.system(size: 8.5, weight: .semibold))
            Text(kind.label)
                .font(NudgeType.rounded(10.5, .medium))
        }
        .foregroundStyle(Theme.sky)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Theme.sky.opacity(0.12), in: .capsule)
    }
}

struct StatusChip: View {
    let status: AppointmentStatus
    private var color: Color {
        switch status {
        case .confirmed: return Theme.life
        case .pending: return Theme.attention
        case .cancelled, .visited: return Theme.inkMuted
        }
    }
    var body: some View {
        Text(status.label)
            .font(NudgeType.rounded(10.5, .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.12), in: .capsule)
    }
}

// MARK: - Detail

/// One visit in full — when, where, the plan goal it advances, and the actions
/// that matter: confirm, reschedule, join, get there, prep.
struct AppointmentDetailView: View {
    @Environment(AppModel.self) private var model
    let appointmentID: UUID

    @State private var rescheduling = false
    @State private var newDate = Date()

    private var appointment: Appointment? { model.appointments.first { $0.id == appointmentID } }

    var body: some View {
        Group {
            if let appointment {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        hero(appointment)
                        if let hint = appointment.planGoalHint { planGoalCard(hint) }
                        actions(appointment)
                        if appointment.trip != nil {
                            NavigationLink(value: CareDestination.trip(appointment.id)) {
                                tripTeaser(appointment)
                            }
                            .buttonStyle(NudgeButtonStyle())
                        }
                        if appointment.status != .cancelled && appointment.status != .visited {
                            NavigationLink(value: CareDestination.visitPrep(appointment.id)) {
                                prepCard
                            }
                            .buttonStyle(NudgeButtonStyle())
                            .accessibilityIdentifier("appointment.prepare")
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 6)
                    .padding(.bottom, 120)
                }
                .scrollIndicators(.hidden)
                .sheet(isPresented: $rescheduling) {
                    RescheduleSheet(current: appointment.date) { picked in
                        model.rescheduleAppointment(appointment.id, to: picked)
                        rescheduling = false
                    }
                    .presentationDetents([.height(380)])
                    .presentationBackground(Theme.base)
                }
            } else {
                ContentUnavailableView("This appointment isn't available",
                                       systemImage: "calendar")
            }
        }
    }

    private func hero(_ appointment: Appointment) -> some View {
        OrganicSurface(radius: 32) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    KindChip(kind: appointment.kind)
                    StatusChip(status: appointment.status)
                }
                Text(appointment.with)
                    .font(NudgeType.serif(24))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Label(appointment.date.formatted(.dateTime.weekday(.wide).month(.wide).day().hour().minute()),
                      systemImage: "clock")
                    .font(NudgeType.rounded(13.5, .medium))
                    .foregroundStyle(Theme.inkMuted)
                Label(appointment.location, systemImage: appointment.kind.glyph)
                    .font(NudgeType.rounded(13))
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
        }
    }

    private func planGoalCard(_ hint: String) -> some View {
        OrganicSurface(radius: 26) {
            HStack(spacing: 12) {
                Image(systemName: "target")
                    .font(.system(size: 15, weight: .light))
                    .foregroundStyle(Theme.life)
                    .frame(width: 38, height: 38)
                    .background(Theme.life.opacity(0.13), in: .circle)
                VStack(alignment: .leading, spacing: 2) {
                    Kicker(text: "What this visit moves", color: Theme.life)
                    Text(hint)
                        .font(NudgeType.rounded(13.5))
                        .foregroundStyle(Theme.ink.opacity(0.88))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(15)
        }
    }

    @ViewBuilder
    private func actions(_ appointment: Appointment) -> some View {
        VStack(spacing: 11) {
            if appointment.kind == .telehealth {
                let ready = model.canJoin(appointment)
                Button {
                    Haptics.glass()
                    if let link = appointment.joinLink, let url = URL(string: link) {
                        UIApplication.shared.open(url)
                    }
                } label: {
                    primaryLabel(ready ? "Join the video visit" : "Join opens 15 min before",
                                 glyph: "video.fill", enabled: ready)
                }
                .buttonStyle(NudgeButtonStyle())
                .disabled(!ready)
            }

            if appointment.status == .pending {
                Button {
                    model.confirmAppointment(appointment.id)
                } label: {
                    primaryLabel("Confirm this time", glyph: "checkmark", enabled: true)
                }
                .buttonStyle(NudgeButtonStyle())
            }

            Button {
                Haptics.tick()
                newDate = appointment.date
                rescheduling = true
            } label: {
                secondaryLabel("Reschedule", glyph: "calendar.badge.clock")
            }
            .buttonStyle(NudgeButtonStyle())
        }
    }

    private func tripTeaser(_ appointment: Appointment) -> some View {
        OrganicSurface(radius: 28) {
            HStack(spacing: 13) {
                Image(systemName: appointment.kind == .telehealth ? "wifi" : "map")
                    .font(.system(size: 16, weight: .light))
                    .foregroundStyle(Theme.sky)
                    .frame(width: 40, height: 40)
                    .background(Theme.sky.opacity(0.13), in: .circle)
                VStack(alignment: .leading, spacing: 2) {
                    Text(appointment.kind == .telehealth ? "Get ready to connect" : "Plan the trip")
                        .font(NudgeType.serif(16.5))
                        .foregroundStyle(Theme.ink)
                    Text(appointment.trip?.routeHint ?? "Everything you need to arrive easy")
                        .font(NudgeType.rounded(12))
                        .foregroundStyle(Theme.inkMuted)
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .light))
                    .foregroundStyle(Theme.inkMuted)
            }
            .padding(15)
        }
    }

    private var prepCard: some View {
        OrganicSurface(radius: 28) {
            HStack(spacing: 13) {
                Image(systemName: "sparkles")
                    .font(.system(size: 16, weight: .light))
                    .foregroundStyle(Theme.warm)
                    .frame(width: 40, height: 40)
                    .background(Theme.warm.opacity(0.13), in: .circle)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Your visit prep is ready")
                        .font(NudgeType.serif(16.5))
                        .foregroundStyle(Theme.ink)
                    Text("What's changed, what to ask, what to bring")
                        .font(NudgeType.rounded(12))
                        .foregroundStyle(Theme.inkMuted)
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .light))
                    .foregroundStyle(Theme.inkMuted)
            }
            .padding(15)
        }
    }

    private func primaryLabel(_ text: String, glyph: String, enabled: Bool) -> some View {
        HStack(spacing: 7) {
            Image(systemName: glyph).font(.system(size: 14, weight: .semibold))
            Text(text).font(NudgeType.rounded(15, .semibold))
        }
        .foregroundStyle(Theme.base)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
        .background(enabled ? Theme.ink : Theme.inkMuted.opacity(0.5), in: .capsule)
    }

    private func secondaryLabel(_ text: String, glyph: String) -> some View {
        HStack(spacing: 7) {
            Image(systemName: glyph).font(.system(size: 13, weight: .medium))
            Text(text).font(NudgeType.rounded(14.5, .semibold))
        }
        .foregroundStyle(Theme.ink)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 13)
        .background(.ultraThinMaterial, in: .capsule)
        .overlay(Capsule().strokeBorder(Color.white.opacity(0.25), lineWidth: 0.8))
    }
}

/// A focused reschedule sheet — pick a new time, confirm in one tap.
struct RescheduleSheet: View {
    let current: Date
    let onConfirm: (Date) -> Void
    @State private var picked: Date

    init(current: Date, onConfirm: @escaping (Date) -> Void) {
        self.current = current
        self.onConfirm = onConfirm
        _picked = State(initialValue: current)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Pick a new time")
                .font(NudgeType.serif(22))
                .foregroundStyle(Theme.ink)
                .padding(.top, 8)

            DatePicker("New time", selection: $picked,
                       in: Date()..., displayedComponents: [.date, .hourAndMinute])
                .datePickerStyle(.compact)
                .labelsHidden()
                .tint(Theme.warm)

            Button {
                onConfirm(picked)
            } label: {
                Text("Confirm new time")
                    .font(NudgeType.rounded(15, .semibold))
                    .foregroundStyle(Theme.base)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(Theme.ink, in: .capsule)
            }
            .buttonStyle(NudgeButtonStyle())

            Text("We'll let the office know and update your reminders.")
                .font(NudgeType.rounded(12))
                .foregroundStyle(Theme.inkMuted)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 22)
        .padding(.top, 8)
    }
}

// MARK: - Trip / wayfinding (§4.4.3)

/// The wayfinding flow — depart-by, route, parking, and the pre-visit
/// checklist; or a readiness flow for telehealth. Surfaces a calendar conflict
/// before it bites, and offers a ride when one helps.
struct TripView: View {
    @Environment(AppModel.self) private var model
    let appointmentID: UUID

    @State private var checked: Set<String> = []

    private var appointment: Appointment? { model.appointments.first { $0.id == appointmentID } }

    var body: some View {
        Group {
            if let appointment, let trip = appointment.trip {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(trip.isVirtual ? "Get ready to connect" : "Plan your trip")
                                .font(NudgeType.serif(28))
                                .foregroundStyle(Theme.ink)
                            Text(appointment.with)
                                .font(NudgeType.rounded(13))
                                .foregroundStyle(Theme.inkMuted)
                        }
                        .padding(.top, 8)

                        if !trip.isVirtual { departCard(trip) }
                        if let conflict = trip.calendarConflict { conflictCard(conflict) }
                        if let ride = trip.rideHint { rideCard(ride) }
                        destinationCard(appointment, trip)
                        checklistCard(trip)
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 120)
                }
                .scrollIndicators(.hidden)
            } else {
                ContentUnavailableView("No trip plan for this visit",
                                       systemImage: "map")
            }
        }
    }

    private func departCard(_ trip: TripPlan) -> some View {
        OrganicSurface(radius: 30) {
            VStack(alignment: .leading, spacing: 10) {
                Kicker(text: "Leave by", color: Theme.warm)
                Text(trip.departBy.formatted(.dateTime.hour().minute()))
                    .font(NudgeType.serif(34))
                    .foregroundStyle(Theme.ink)
                Label("\(trip.travelMinutes) min · \(trip.routeHint)", systemImage: "car.fill")
                    .font(NudgeType.rounded(13))
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
        }
    }

    private func conflictCard(_ conflict: String) -> some View {
        OrganicSurface(radius: 26) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "calendar.badge.exclamationmark")
                    .font(.system(size: 15, weight: .light))
                    .foregroundStyle(Theme.attention)
                    .frame(width: 38, height: 38)
                    .background(Theme.attention.opacity(0.13), in: .circle)
                Text(conflict)
                    .font(NudgeType.rounded(13.5))
                    .foregroundStyle(Theme.ink.opacity(0.88))
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(15)
        }
    }

    private func rideCard(_ ride: String) -> some View {
        OrganicSurface(radius: 26) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "figure.wave")
                        .font(.system(size: 15, weight: .light))
                        .foregroundStyle(Theme.sky)
                        .frame(width: 38, height: 38)
                        .background(Theme.sky.opacity(0.13), in: .circle)
                    Text(ride)
                        .font(NudgeType.rounded(13.5))
                        .foregroundStyle(Theme.ink.opacity(0.88))
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }
                Button {
                    Haptics.tick()
                    if let url = URL(string: "https://m.uber.com") { UIApplication.shared.open(url) }
                } label: {
                    Text("Line up a ride")
                        .font(NudgeType.rounded(13.5, .semibold))
                        .foregroundStyle(Theme.base)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                        .background(Theme.ink, in: .capsule)
                }
                .buttonStyle(NudgeButtonStyle())
            }
            .padding(15)
        }
    }

    private func destinationCard(_ appointment: Appointment, _ trip: TripPlan) -> some View {
        OrganicSurface(radius: 28) {
            VStack(alignment: .leading, spacing: 10) {
                Kicker(text: trip.isVirtual ? "Where" : "Getting in", color: Theme.life)
                Text(trip.destinationDetail)
                    .font(NudgeType.rounded(14))
                    .foregroundStyle(Theme.ink.opacity(0.9))
                    .fixedSize(horizontal: false, vertical: true)
                if !trip.isVirtual && !trip.mapQuery.isEmpty {
                    Button {
                        Haptics.tick()
                        openMaps(trip.mapQuery)
                    } label: {
                        HStack(spacing: 7) {
                            Image(systemName: "map.fill").font(.system(size: 13, weight: .semibold))
                            Text("Open in Maps").font(NudgeType.rounded(14, .semibold))
                        }
                        .foregroundStyle(Theme.base)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(Theme.ink, in: .capsule)
                    }
                    .buttonStyle(NudgeButtonStyle())
                }
            }
            .padding(16)
        }
    }

    private func checklistCard(_ trip: TripPlan) -> some View {
        OrganicSurface(radius: 28) {
            VStack(alignment: .leading, spacing: 12) {
                Kicker(text: "Before you go", color: Theme.gold)
                ForEach(trip.checklist, id: \.self) { item in
                    Button {
                        Haptics.tick()
                        SoundEngine.shared.tick()
                        withAnimation(NudgeSpring.gentle) {
                            if checked.contains(item) { checked.remove(item) } else { checked.insert(item) }
                        }
                    } label: {
                        HStack(spacing: 11) {
                            Image(systemName: checked.contains(item) ? "checkmark.circle.fill" : "circle")
                                .font(.system(size: 18, weight: .light))
                                .foregroundStyle(checked.contains(item) ? Theme.life : Theme.inkMuted.opacity(0.6))
                            Text(item)
                                .font(NudgeType.rounded(14))
                                .foregroundStyle(checked.contains(item) ? Theme.inkMuted : Theme.ink.opacity(0.9))
                                .strikethrough(checked.contains(item), color: Theme.inkMuted)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                        }
                    }
                    .buttonStyle(NudgeButtonStyle())
                }
            }
            .padding(16)
        }
    }

    private func openMaps(_ query: String) {
        let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        if let url = URL(string: "http://maps.apple.com/?q=\(encoded)") {
            UIApplication.shared.open(url)
        }
    }
}
