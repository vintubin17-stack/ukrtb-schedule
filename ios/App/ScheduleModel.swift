import Foundation

/// Расписание в том виде, в каком его отдаёт сайт (`docs/data.json`).
/// Разбираем только то, что нужно для напоминаний.
struct ScheduleFile: Codable {
    let group: String
    let days: [String: ScheduleDay]

    enum CodingKeys: String, CodingKey {
        case group
        case days
    }
}

struct ScheduleDay: Codable {
    let date: String
    let weekday: String?
    let lessons: [Lesson]
}

struct Lesson: Codable {
    let number: Int?
    let discipline: String
    let start: String
    let end: String
    let roomLabel: String?
    let teacherShort: String?

    enum CodingKeys: String, CodingKey {
        case number
        case discipline
        case start
        case end
        case roomLabel = "room_label"
        case teacherShort = "teacher_short"
    }

    /// «МДК. Разработка приложений · ауд. 204 · Зубарев А. А.»
    var notificationBody: String {
        var parts = [discipline]
        if let room = roomLabel, !room.isEmpty {
            parts.append("ауд. \(room)")
        }
        if let teacher = teacherShort, !teacher.isEmpty {
            parts.append(teacher)
        }
        return parts.joined(separator: " · ")
    }
}
