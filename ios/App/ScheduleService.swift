import Foundation
import UserNotifications

/// Всё, что приложение делает само, пока пользователь его не трогает:
/// живая активность с текущей парой и напоминания за 15 минут до начала.
///
/// Данные берутся из того же файла расписания, что отдаёт сайт, и
/// обрабатываются на устройстве: ни сервер, ни push-уведомления не нужны,
/// поэтому всё работает и при бесплатной подписи через SideStore.
final class ScheduleService {

    static let shared = ScheduleService()

    private let dataURL = URL(string: "https://vintubin17-stack.github.io/ukrtb-schedule/data.json")!
    private let leadTime: TimeInterval = 15 * 60
    private let horizonDays = 7
    /// Насколько заранее показывать перемену в живой активности.
    private let breakLookahead: TimeInterval = 2 * 60 * 60
    private var isRunning = false

    private init() { }

    /// Вызывается при каждом открытии приложения.
    func refresh() {
        guard !isRunning else { return }
        isRunning = true

        UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound, .badge]) { [weak self] granted, _ in
                guard let self = self else { return }
                self.loadSchedule(notificationsAllowed: granted)
            }
    }

    private func loadSchedule(notificationsAllowed: Bool) {
        var request = URLRequest(url: dataURL)
        request.cachePolicy = .reloadRevalidatingCacheData

        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self = self else { return }
            defer { self.isRunning = false }

            if let error = error {
                NSLog("[Расписание] сеть: %@", error.localizedDescription)
                return
            }
            guard let data = data,
                  let file = try? JSONDecoder().decode(ScheduleFile.self, from: data) else {
                NSLog("[Расписание] не удалось разобрать файл расписания")
                return
            }

            self.updateLiveActivity(file)
            if notificationsAllowed {
                self.scheduleNotifications(file)
            }
        }.resume()
    }

    // MARK: - Живая активность на экране блокировки

    private func updateLiveActivity(_ file: ScheduleFile) {
        let now = Date()
        var current: (lesson: Lesson, start: Date, end: Date)?
        var upcoming: (lesson: Lesson, start: Date)?

        for (isoDate, day) in file.days {
            guard let dayStart = Self.isoDayParser.date(from: isoDate) else { continue }

            for lesson in day.lessons {
                guard let range = Self.timeRange(of: lesson, on: dayStart) else { continue }

                if range.start <= now && now < range.end {
                    // Идёт прямо сейчас: из нескольких берём начавшуюся позже.
                    if current == nil || range.start > current!.start {
                        current = (lesson, range.start, range.end)
                    }
                } else if range.start > now {
                    if upcoming == nil || range.start < upcoming!.start {
                        upcoming = (lesson, range.start)
                    }
                }
            }
        }

        if let lesson = current {
            LiveActivityController.shared.apply(
                LessonActivityAttributes.ContentState(
                    discipline: lesson.lesson.discipline,
                    room: lesson.lesson.roomLabel,
                    teacher: lesson.lesson.teacherShort,
                    start: lesson.start,
                    end: lesson.end,
                    isBreak: false),
                group: file.group)
            return
        }

        // Пары нет, но скоро начнётся — показываем перемену с отсчётом.
        if let next = upcoming, next.start.timeIntervalSince(now) <= breakLookahead {
            LiveActivityController.shared.apply(
                LessonActivityAttributes.ContentState(
                    discipline: next.lesson.discipline,
                    room: next.lesson.roomLabel,
                    teacher: next.lesson.teacherShort,
                    start: now,
                    end: next.start,
                    isBreak: true),
                group: file.group)
            return
        }

        LiveActivityController.shared.stop()
    }

    // MARK: - Напоминания за 15 минут

    private func scheduleNotifications(_ file: ScheduleFile) {
        let center = UNUserNotificationCenter.current()
        let calendar = Calendar.current
        let now = Date()

        center.removeAllPendingNotificationRequests()

        var planned = 0

        for (isoDate, day) in file.days {
            guard let dayStart = Self.isoDayParser.date(from: isoDate) else { continue }

            let offset = calendar.dateComponents([.day], from: now, to: dayStart).day ?? -1
            guard offset >= 0, offset <= horizonDays else { continue }

            for lesson in day.lessons {
                guard let range = Self.timeRange(of: lesson, on: dayStart) else { continue }

                let fireDate = range.start.addingTimeInterval(-leadTime)
                guard fireDate > now else { continue }

                let content = UNMutableNotificationContent()
                content.title = "Пара через 15 минут"
                content.body = lesson.notificationBody
                content.sound = .default
                content.threadIdentifier = "lessons"

                let trigger = UNCalendarNotificationTrigger(
                    dateMatching: calendar.dateComponents([.year, .month, .day, .hour, .minute],
                                                         from: fireDate),
                    repeats: false)

                center.add(UNNotificationRequest(
                    identifier: "lesson-\(isoDate)-\(lesson.number ?? 0)",
                    content: content,
                    trigger: trigger))
                planned += 1
            }
        }

        NSLog("[Расписание] напоминаний запланировано: %d", planned)
    }

    // MARK: - Вспомогательное

    /// Время начала и конца пары в конкретный день.
    private static func timeRange(of lesson: Lesson, on dayStart: Date) -> (start: Date, end: Date)? {
        let calendar = Calendar.current
        guard let parsedStart = timeParser.date(from: lesson.start),
              let parsedEnd = timeParser.date(from: lesson.end) else { return nil }

        let startParts = calendar.dateComponents([.hour, .minute], from: parsedStart)
        let endParts = calendar.dateComponents([.hour, .minute], from: parsedEnd)

        guard let start = calendar.date(bySettingHour: startParts.hour ?? 0,
                                        minute: startParts.minute ?? 0,
                                        second: 0,
                                        of: dayStart),
              var end = calendar.date(bySettingHour: endParts.hour ?? 0,
                                      minute: endParts.minute ?? 0,
                                      second: 0,
                                      of: dayStart) else { return nil }

        // Пара, заканчивающаяся «после полуночи», встречается редко,
        // но пусть считается корректно.
        if end <= start {
            end = end.addingTimeInterval(24 * 60 * 60)
        }
        return (start, end)
    }

    private static let timeParser: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    /// Разбор даты вида 2026-10-05 в часовом поясе устройства.
    private static let isoDayParser: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}
