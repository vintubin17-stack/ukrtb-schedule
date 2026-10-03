import SwiftUI

/// Главный экран: расписание и состояние загрузки.
///
/// Приложение показывает ту же страницу, что открывается в браузере,
/// но как обычное приложение: со своей иконкой, без адресной строки,
/// с работой без сети (страница кладёт данные в кэш) и pull-to-refresh.
struct ContentView: View {
    /// Опубликованное расписание.
    private let scheduleURL = URL(string: "https://vintubin17-stack.github.io/ukrtb-schedule/")!

    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var reloadToken = 0

    var body: some View {
        ZStack {
            WebView(url: scheduleURL,
                    reloadToken: reloadToken,
                    isLoading: $isLoading,
                    errorMessage: $errorMessage)
                .ignoresSafeArea(edges: .bottom)
                .onAppear {
                    // Напоминания о парах и живая активность с текущей парой.
                    ScheduleService.shared.refresh()
                }

            if isLoading && errorMessage == nil {
                ProgressView()
                    .controlSize(.large)
                    .padding(24)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }

            if let message = errorMessage {
                VStack(spacing: 14) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.system(size: 44))
                        .foregroundStyle(.secondary)

                    Text("Нет связи")
                        .font(.title3.weight(.semibold))

                    Text(message)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)

                    Button("Повторить") {
                        errorMessage = nil
                        isLoading = true
                        reloadToken += 1
                    }
                    .buttonStyle(.borderedProminent)
                    .padding(.top, 4)
                }
                .padding(28)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
                .padding(32)
            }
        }
    }
}

#Preview {
    ContentView()
}
