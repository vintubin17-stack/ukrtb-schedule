import Foundation
import UserNotifications

/// Напоминания о парах — единственная вещь, которую сайт дать не может.
///
/// Всё считается на устройстве: приложение забирает файл расписания и ставит
/// локальные уведомления за 15 минут до начала каждой пары на неделю вперёд.
/// Ни сервер, ни push-уведомления, ни платный аккаунт разработчика не нужны —
/// поэтому это работает и при бесплатной подписи через SideStore.
///
/// Ограничение честное: напоминания обновляются, когда приложение открывают.
/// Если не открывать неделю, расписание на следующие дни уже не напомнит.
final class LessonNotifications {

    static let shared = LessonNotifications()

    /// Файл расписания на сайте.
    private let dataURL = URL(string: "https://vintubin17-stack.github.io/ukrtb-schedule/data.json")!

    /// За сколько до начала пары напоминать.
    private let leadTime: TimeInterval = 15 * 60

    /// На сколько дней вперёд расставлять напоминания.
    private let horizonDays = 7

    private let identifierPrefix = "lesson-"
    private var isRunning = false

    private init() {}

    /// Просит разрешение (система спросит один раз) и пересобирает расписание
    /// напоминаний. Вызывается при каждом открытии приложения.
    func refresh() {
        guard !isRunning else { return }
        isRunning = true

        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound, .badge]) { [weak self] granted, _ in
            guard let self = self else { return }
            guard granted else {
                self.isRunning = false
                NSLog("[Расписание] напоминания выключены пользователем")
                return
            }
            self.loadSchedule()
        }
    }

    private func loadSchedule() {
        var request = URLRequest(url: dataURL)
        request.cachePolicy = .reloadRevalidatingCacheData

        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self = self else { return }
            defer { self.isRunning = false }

            if let error = error {
                NSLog("[Расписание] не удалось получить расписание: %@", error.localizedDescription)
                return
            }
            guard let data = data,
                  let file = try? JSONDecoder().decode(ScheduleFile.self, from: data) else {
                NSLog("[Расписание] не удалось разобрать файл расписания")
                return
            }
            self.schedule(file)
        }.resume()
    }

    private func schedule(_ file: ScheduleFile) {
        let center = UNUserNotificationCenter.current()
        let calendar = Calendar.current
        let now = Date()

        let timeParser = DateFormatter()
        timeParser.locale = Locale(identifier: "en_US_POSIX")
        timeParser.dateFormat = "HH:mm"

        // Сначала убираем прошлые напоминания, чтобы не дублировались.
        center.removeAllPendingNotificationRequests()

        var planned = 0

        for (isoDate, day) in file.days {
            guard let dayStart = Self.isoDayParser.date(from: isoDate) else { continue }

            let offset = calendar.dateComponents([.day], from: now, to: dayStart).day ?? -1
            guard offset >= 0, offset <= horizonDays else { continue }

            for lesson in day.lessons {
                guard let parsedTime = timeParser.date(from: lesson.start) else { continue }
                let parts = calendar.dateComponents([.hour, .minute], from: parsedTime)
                guard let lessonStart = calendar.date(bySettingHour: parts.hour ?? 0,
                                                     minute: parts.minute ?? 0,
                                                     second: 0,
                                                     of: dayStart) else { continue }

                let fireDate = lessonStart.addingTimeInterval(-leadTime)
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

                let identifier = "\(identifierPrefix)\(isoDate)-\(lesson.number ?? 0)"
                center.add(UNNotificationRequest(identifier: identifier,
                                                 content: content,
                                                 trigger: trigger))
                planned += 1
            }
        }

        NSLog("[Расписание] напоминаний запланировано: %d", planned)
    }

    /// Разбор даты вида 2026-10-05 в текущем часовом поясе устройства.
    private static let isoDayParser: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}
