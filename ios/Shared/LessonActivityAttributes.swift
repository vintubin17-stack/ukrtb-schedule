import ActivityKit
import Foundation

/// Данные живой активности (Live Activity) — то, что показывается
/// на экране блокировки и в Dynamic Island.
///
/// Этот файл включён и в приложение, и в расширение виджета: так обе части
/// используют один и тот же тип, как того требует ActivityKit.
struct LessonActivityAttributes: ActivityAttributes {

    struct ContentState: Codable, Hashable {
        /// Что идёт: название пары.
        var discipline: String
        /// Аудитория, если известна.
        var room: String?
        /// Преподаватель, если известен.
        var teacher: String?

        /// Начало и конец отрезка, который показывают ползунок и отсчёт.
        /// Для пары это её время, для перемены — от текущего момента
        /// до начала следующей пары.
        var start: Date
        var end: Date

        /// true — идёт перемена (или время до первой пары).
        var isBreak: Bool
    }

    /// Группа: не меняется, пока активность живёт.
    var group: String
}
