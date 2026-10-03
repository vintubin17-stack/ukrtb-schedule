import ActivityKit
import SwiftUI
import WidgetKit

/// Живая активность: текущая пара на экране блокировки и в Dynamic Island.
///
/// Ползунок и обратный отсчёт обновляются силами системы:
/// `ProgressView(timerInterval:)` и `Text(timerInterval:)` идут сами,
/// поэтому приложение может быть закрыто.
struct LessonLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: LessonActivityAttributes.self) { context in
            LockScreenView(state: context.state, group: context.attributes.group)
                .activityBackgroundTint(Color(red: 0.01, green: 0.42, blue: 0.63))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label(kindTitle(context.state),
                          systemImage: kindSymbol(context.state))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }

                DynamicIslandExpandedRegion(.trailing) {
                    Text(timerInterval: context.state.start...context.state.end,
                         countsDown: true)
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .frame(maxWidth: 60)
                }

                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 7) {
                        Text(context.state.discipline)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)

                        ProgressView(timerInterval: context.state.start...context.state.end,
                                     countsDown: false)
                            .progressViewStyle(.linear)
                            .tint(.cyan)

                        HStack(spacing: 8) {
                            Text(context.state.room.map { "ауд. \($0)" } ?? "")
                            Spacer(minLength: 0)
                            Text(finishText(context.state))
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    }
                }
            } compactLeading: {
                Image(systemName: kindSymbol(context.state))
            } compactTrailing: {
                Text(timerInterval: context.state.start...context.state.end,
                     countsDown: true)
                    .font(.caption2.monospacedDigit())
                    .frame(maxWidth: 46)
            } minimal: {
                Image(systemName: kindSymbol(context.state))
            }
            .keylineTint(.cyan)
        }
    }

    private func kindTitle(_ state: LessonActivityAttributes.ContentState) -> String {
        state.isBreak ? "Перемена" : "Идёт пара"
    }

    private func kindSymbol(_ state: LessonActivityAttributes.ContentState) -> String {
        state.isBreak ? "cup.and.saucer.fill" : "book.closed.fill"
    }

    private func finishText(_ state: LessonActivityAttributes.ContentState) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        let time = formatter.string(from: state.end)
        return state.isBreak ? "пара в \(time)" : "до \(time)"
    }
}

/// Экран блокировки: название пары, ползунок, аудитория и время окончания.
private struct LockScreenView: View {
    let state: LessonActivityAttributes.ContentState
    let group: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Label(state.isBreak ? "Перемена" : "Идёт пара",
                      systemImage: state.isBreak ? "cup.and.saucer.fill" : "book.closed.fill")
                    .font(.caption.weight(.semibold))
                Spacer(minLength: 0)
                Text(group)
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.7))
            }

            Text(state.discipline)
                .font(.headline)
                .lineLimit(2)
                .multilineTextAlignment(.leading)

            ProgressView(timerInterval: state.start...state.end, countsDown: false)
                .progressViewStyle(.linear)
                .tint(.white)

            HStack(spacing: 8) {
                if let room = state.room, !room.isEmpty {
                    Label("ауд. \(room)", systemImage: "door.left.hand.open")
                }
                if let teacher = state.teacher, !teacher.isEmpty {
                    Text(teacher).lineLimit(1)
                }
                Spacer(minLength: 0)
                Text(remainText)
                    .monospacedDigit()
            }
            .font(.caption)
            .foregroundStyle(.white.opacity(0.85))
        }
        .padding(16)
        .foregroundStyle(.white)
    }

    private var remainText: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        let time = formatter.string(from: state.end)
        return state.isBreak ? "пара в \(time)" : "до \(time)"
    }
}
