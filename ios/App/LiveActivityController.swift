import ActivityKit
import Foundation

/// Запускает и обновляет живую активность с текущей парой.
///
/// Запустить активность можно только пока приложение на экране — это
/// ограничение iOS. Дальше она живёт сама: ползунок и обратный отсчёт
/// обновляет система, приложение для этого не нужно.
final class LiveActivityController {

    static let shared = LiveActivityController()

    private var activity: Activity<LessonActivityAttributes>?

    private init() { }

    /// Показать (или обновить) активность.
    func apply(_ state: LessonActivityAttributes.ContentState, group: String) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            NSLog("[Расписание] живые активности выключены в настройках iOS")
            return
        }

        let content = ActivityContent(state: state, staleDate: state.end)

        if let current = activity {
            Task { await current.update(content) }
            return
        }

        do {
            activity = try Activity.request(
                attributes: LessonActivityAttributes(group: group),
                content: content,
                pushType: nil
            )
            NSLog("[Расписание] живая активность запущена: %@", state.discipline)
        } catch {
            NSLog("[Расписание] не удалось запустить живую активность: %@",
                  error.localizedDescription)
        }
    }

    /// Убрать активность — например, когда занятия закончились.
    func stop() {
        guard let current = activity else { return }
        activity = nil
        Task { await current.end(nil, dismissalPolicy: .immediate) }
    }
}
