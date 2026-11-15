import AppKit
import WebKit

final class NancyApp: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var companion: Process?
    private var chatWindow: NSWindow?
    private var statusMenuItem: NSMenuItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureMenu()
        startCompanion()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopCompanion()
    }

    private func configureMenu() {
        statusItem.button?.image = NSImage(
            systemSymbolName: "waveform.circle.fill",
            accessibilityDescription: "Nancy"
        )
        statusItem.button?.title = " Nancy"
        statusItem.button?.toolTip = "Nancy"

        let menu = NSMenu()
        statusMenuItem = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)
        menu.addItem(.separator())
        menu.addItem(item("Open Nancy", #selector(openChat), "n"))
        menu.addItem(item("Restart Listener", #selector(restartCompanion), "r"))
        menu.addItem(item("Stop Listener", #selector(stopCompanionAction), "s"))
        menu.addItem(.separator())
        menu.addItem(item("Open Logs", #selector(openLogs), "l"))
        menu.addItem(item("Quit Nancy", #selector(quit), "q"))
        statusItem.menu = menu
    }

    private func item(_ title: String, _ action: Selector, _ key: String) -> NSMenuItem {
        let value = NSMenuItem(title: title, action: action, keyEquivalent: key)
        value.target = self
        return value
    }

    private var companionDirectory: URL? {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "NancyCompanionPath") as? String,
              !path.isEmpty else { return nil }
        return URL(fileURLWithPath: path, isDirectory: true)
    }

    private var logsDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Nancy", isDirectory: true)
    }

    private func updateStatus(_ text: String, running: Bool) {
        statusMenuItem.title = text
        statusItem.button?.image = NSImage(
            systemSymbolName: running ? "waveform.circle.fill" : "waveform.circle",
            accessibilityDescription: text
        )
    }

    private func startCompanion() {
        guard companion?.isRunning != true else { return }
        guard let directory = companionDirectory else {
            updateStatus("Companion path missing", running: false)
            return
        }
        let script = directory.appendingPathComponent("run-companion.sh")
        guard FileManager.default.isExecutableFile(atPath: script.path) else {
            updateStatus("Companion not installed", running: false)
            return
        }

        try? FileManager.default.createDirectory(
            at: logsDirectory, withIntermediateDirectories: true
        )
        let outputURL = logsDirectory.appendingPathComponent("companion.log")
        let errorURL = logsDirectory.appendingPathComponent("companion-error.log")
        FileManager.default.createFile(atPath: outputURL.path, contents: nil)
        FileManager.default.createFile(atPath: errorURL.path, contents: nil)

        do {
            let output = try FileHandle(forWritingTo: outputURL)
            let error = try FileHandle(forWritingTo: errorURL)
            output.seekToEndOfFile()
            error.seekToEndOfFile()

            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [script.path]
            process.currentDirectoryURL = directory
            process.standardOutput = output
            process.standardError = error
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONUNBUFFERED"] = "1"
            process.environment = environment
            process.terminationHandler = { [weak self] finished in
                output.closeFile()
                error.closeFile()
                DispatchQueue.main.async {
                    guard let self else { return }
                    if self.companion === finished { self.companion = nil }
                    self.updateStatus(
                        "Listener stopped (\(finished.terminationStatus))",
                        running: false
                    )
                }
            }
            try process.run()
            companion = process
            updateStatus("Listening", running: true)
        } catch {
            updateStatus("Could not start listener", running: false)
        }
    }

    private func stopCompanion() {
        guard let process = companion, process.isRunning else { return }
        process.terminate()
        companion = nil
        updateStatus("Listener stopped", running: false)
    }

    @objc private func restartCompanion() {
        stopCompanion()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.startCompanion()
        }
    }

    @objc private func stopCompanionAction() {
        stopCompanion()
    }

    @objc private func openChat() {
        if chatWindow == nil {
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = .default()
            let webView = WKWebView(frame: .zero, configuration: configuration)
            webView.load(URLRequest(url: URL(string: "https://voice-api.builtforyou.live")!))
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 860, height: 720),
                styleMask: [.titled, .closable, .miniaturizable, .resizable],
                backing: .buffered,
                defer: false
            )
            window.title = "Nancy"
            window.contentView = webView
            window.center()
            window.isReleasedWhenClosed = false
            chatWindow = window
        }
        chatWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc private func openLogs() {
        try? FileManager.default.createDirectory(
            at: logsDirectory, withIntermediateDirectories: true
        )
        NSWorkspace.shared.open(logsDirectory)
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}

@main
struct NancyMain {
    static func main() {
        let application = NSApplication.shared
        let delegate = NancyApp()
        application.delegate = delegate
        application.run()
    }
}
