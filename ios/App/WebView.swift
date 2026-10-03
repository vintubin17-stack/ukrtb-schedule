import SwiftUI
import WebKit

/// Обёртка над WKWebView: показывает страницу и сообщает SwiftUI
/// о ходе загрузки и об ошибке.
struct WebView: UIViewRepresentable {
    let url: URL
    let reloadToken: Int
    @Binding var isLoading: Bool
    @Binding var errorMessage: String?

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.websiteDataStore = .default()
        // Страница сообщает выбранную тему — по ней подстраиваем оформление
        // окна, чтобы строка состояния читалась на тёмном фоне.
        configuration.userContentController.add(context.coordinator, name: "theme")

        // Запрет масштабирования. В обычном Safari этот метатег игнорируется
        // ради доступности, но WKWebView его уважает — поэтому внутри
        // приложения «щипок» и двойной тап страницу больше не приближают.
        // Скрипт на случай, если страница откроется из старого кэша.
        let noZoom = WKUserScript(
            source: """
            (function () {
                var meta = document.querySelector('meta[name="viewport"]');
                if (!meta) {
                    meta = document.createElement('meta');
                    meta.setAttribute('name', 'viewport');
                    document.head.appendChild(meta);
                }
                meta.setAttribute('content',
                    'width=device-width, initial-scale=1, maximum-scale=1, ' +
                    'user-scalable=no, viewport-fit=cover');
                document.documentElement.classList.add('no-zoom');
            })();
            """,
            injectionTime: .atDocumentEnd,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(noZoom)

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .always
        webView.isOpaque = false
        webView.backgroundColor = .clear

        // Сам масштаб прокрутки: даже если страница попросит иначе,
        // приблизить её жестом не получится.
        webView.scrollView.minimumZoomScale = 1
        webView.scrollView.maximumZoomScale = 1
        webView.scrollView.bouncesZoom = false
        webView.scrollView.pinchGestureRecognizer?.isEnabled = false

        let refreshControl = UIRefreshControl()
        refreshControl.tintColor = .secondaryLabel
        refreshControl.addTarget(context.coordinator,
                                 action: #selector(Coordinator.handleRefresh(_:)),
                                 for: .valueChanged)
        webView.scrollView.refreshControl = refreshControl

        context.coordinator.webView = webView
        webView.load(URLRequest(url: url))
        return webView
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController
            .removeScriptMessageHandler(forName: "theme")
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        // Повторная загрузка по кнопке «Повторить».
        guard context.coordinator.lastReloadToken != reloadToken else { return }
        context.coordinator.lastReloadToken = reloadToken
        webView.load(URLRequest(url: url))
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private let parent: WebView
        weak var webView: WKWebView?
        var lastReloadToken: Int

        init(_ parent: WebView) {
            self.parent = parent
            self.lastReloadToken = parent.reloadToken
        }

        @objc func handleRefresh(_ sender: UIRefreshControl) {
            webView?.reload()
        }

        /// Страница сообщает, какая тема выбрана: светлая или тёмная.
        /// Переключаем оформление окна за ней, иначе на тёмной теме
        /// строка состояния останется с тёмным текстом.
        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.name == "theme", let value = message.body as? String else { return }
            let style: UIUserInterfaceStyle = (value == "dark") ? .dark : .light
            DispatchQueue.main.async { [weak self] in
                self?.webView?.window?.overrideUserInterfaceStyle = style
            }
        }

        /// Внутренние переходы — в приложении, внешние ссылки — в Safari.
        /// Так ссылка «Подключиться» на пару открывает Zoom/Max в браузере,
        /// а не запирает пользователя внутри обёртки.
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard navigationAction.navigationType == .linkActivated,
                  let url = navigationAction.request.url,
                  let host = url.host else {
                decisionHandler(.allow)
                return
            }

            if Self.internalHosts.contains(where: { host.hasSuffix($0) }) {
                decisionHandler(.allow)
                return
            }

            UIApplication.shared.open(url)
            decisionHandler(.cancel)
        }

        private static let internalHosts = ["vintubin17-stack.github.io"]

        func webView(_ webView: WKWebView,
                     didStartProvisionalNavigation navigation: WKNavigation!) {
            parent.isLoading = true
            parent.errorMessage = nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            webView.scrollView.refreshControl?.endRefreshing()
        }

        func webView(_ webView: WKWebView,
                     didFail navigation: WKNavigation!,
                     withError error: Error) {
            handle(error)
        }

        func webView(_ webView: WKWebView,
                     didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            handle(error)
        }

        private func handle(_ error: Error) {
            parent.isLoading = false
            webView?.scrollView.refreshControl?.endRefreshing()

            // Отменённая загрузка (например, пользователь ушёл назад) — не ошибка.
            let nsError = error as NSError
            if nsError.code == NSURLErrorCancelled { return }

            parent.errorMessage = "Не удалось загрузить расписание. "
                + "Проверьте подключение к интернету и попробуйте ещё раз."
        }
    }
}
