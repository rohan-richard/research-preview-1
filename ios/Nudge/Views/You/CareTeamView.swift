import SwiftUI

struct CareTeamView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Care team").font(NudgeType.serif(28)).foregroundStyle(Theme.ink)
                ForEach(model.careTeam) { member in
                    OrganicSurface {
                        HStack(spacing: 13) {
                            Image(systemName: "person.crop.circle").font(.system(size: 30)).foregroundStyle(Theme.life)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(member.name).font(NudgeType.serif(18))
                                Text("\(member.role) · \(member.org)").font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                            }
                            Spacer()
                            Button { model.callOffice() } label: { Image(systemName: "phone").frame(width: 44, height: 44) }
                                .accessibilityLabel("Call \(member.name)")
                        }.padding(16)
                    }
                }
                Text("Visits").font(NudgeType.serif(22))
                ForEach(model.appointments.sorted { $0.date > $1.date }) { appointment in
                    OrganicSurface {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(appointment.with).font(NudgeType.serif(18))
                            Text("\(appointment.date.formatted(date: .abbreviated, time: .shortened)) · \(appointment.location)")
                                .font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
                            if appointment.status != .cancelled && appointment.status != .visited {
                                NavigationLink(value: YouDestination.visitPrep(appointment.id)) {
                                    Label("Prepare for this visit", systemImage: "square.and.pencil").frame(minHeight: 44)
                                }
                            }
                        }.padding(18)
                    }
                }
                NavigationLink(value: YouDestination.guide) { Label("Discussion guide", systemImage: "text.book.closed").frame(minHeight: 44) }
            }.padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 170)
        }.scrollIndicators(.hidden).foregroundStyle(Theme.ink)
    }
}
