import AppKit
import ApplicationServices
import Darwin
import WebKit

private enum NancyState: String {
    case idle, listening, processing, speaking
}

private final class OrbView: NSView {
    var state: NancyState = .listening { didSet { needsDisplay = true } }
    private var phase: CGFloat = 0
    private var timer: Timer?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) {
            [weak self] _ in
            guard let self else { return }
            self.phase += 0.075
            self.needsDisplay = true
        }
    }

    required init?(coder: NSCoder) { nil }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let pulse = (sin(phase) + 1) / 2
        let color: NSColor
        switch state {
        case .listening: color = .systemCyan
        case .processing: color = .systemPurple
        case .speaking: color = .systemGreen
        case .idle: color = .clear
        }
        let center = NSPoint(x: bounds.midX, y: bounds.midY)
        let haloRadius = 27 + pulse * 7
        color.withAlphaComponent(0.10 + pulse * 0.10).setFill()
        NSBezierPath(ovalIn: NSRect(
            x: center.x - haloRadius, y: center.y - haloRadius,
            width: haloRadius * 2, height: haloRadius * 2
        )).fill()
        let radius = 17 + pulse * 2
        let orb = NSBezierPath(ovalIn: NSRect(
            x: center.x - radius, y: center.y - radius,
            width: radius * 2, height: radius * 2
        ))
        color.setFill()
        orb.fill()
        NSColor.white.withAlphaComponent(0.72).setFill()
        NSBezierPath(ovalIn: NSRect(
            x: center.x - 7, y: center.y + 3,
            width: 9, height: 6
        )).fill()
    }
}

final class NancyApp: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var companion: Process?
    private var chatWindow: NSWindow?
    private var statusMenuItem: NSMenuItem!
    private var hotkeyMenu: NSMenu!
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var lastModifierTap: TimeInterval = 0
    private var outputBuffer = ""
    private var currentState: NancyState = .idle
    private let orbView = OrbView(frame: NSRect(x: 0, y: 0, width: 88, height: 88))
    private lazy var orbPanel: NSPanel = makeOrbPanel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureMenu()
        configureHotkeyMonitor()
        startCompanion()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopCompanion()
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
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
        let hotkeyItem = NSMenuItem(title: "Keyboard Trigger", action: nil, keyEquivalent: "")
        hotkeyMenu = NSMenu()
        hotkeyItem.submenu = hotkeyMenu
        menu.addItem(hotkeyItem)
        rebuildHotkeyMenu()
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

    private var hotkeyChoice: String {
        get { UserDefaults.standard.string(forKey: "NancyHotkey") ?? "rightOption" }
        set { UserDefaults.standard.set(newValue, forKey: "NancyHotkey") }
    }

    private func rebuildHotkeyMenu() {
        hotkeyMenu.removeAllItems()
        for (title, value) in [
            ("Double-tap Right Option", "rightOption"),
            ("Double-tap Left Option", "leftOption"),
            ("Disabled", "disabled"),
        ] {
            let menuItem = NSMenuItem(
                title: title, action: #selector(selectHotkey(_:)), keyEquivalent: ""
            )
            menuItem.target = self
            menuItem.representedObject = value
            menuItem.state = hotkeyChoice == value ? .on : .off
            hotkeyMenu.addItem(menuItem)
        }
    }

    @objc private func selectHotkey(_ sender: NSMenuItem) {
        guard let value = sender.representedObject as? String else { return }
        hotkeyChoice = value
        rebuildHotkeyMenu()
    }

    private func configureHotkeyMonitor() {
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true
        ] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) {
            [weak self] event in self?.handleModifier(event)
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) {
            [weak self] event in
            self?.handleModifier(event)
            return event
        }
    }

    private func handleModifier(_ event: NSEvent) {
        let expectedCode: UInt16
        switch hotkeyChoice {
        case "rightOption": expectedCode = 61
        case "leftOption": expectedCode = 58
        default: return
        }
        guard event.keyCode == expectedCode, event.modifierFlags.contains(.option) else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastModifierTap < 0.45 {
            lastModifierTap = 0
            triggerCompanion()
        } else {
            lastModifierTap = now
        }
    }

    private func triggerCompanion() {
        guard currentState == .idle else { return }
        guard let companion, companion.isRunning else {
            startCompanion()
            return
        }
        kill(companion.processIdentifier, SIGUSR1)
    }

    private func makeOrbPanel() -> NSPanel {
        let screenFrame = NSScreen.main?.visibleFrame ?? .zero
        let size = NSSize(width: 88, height: 88)
        let frame = NSRect(
            x: screenFrame.midX - size.width / 2,
            y: screenFrame.minY + 54,
            width: size.width,
            height: size.height
        )
        let panel = NSPanel(
            contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.level = .floating
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = orbView
        return panel
    }

    private func applyState(_ state: NancyState) {
        currentState = state
        orbView.state = state
        if state == .idle {
            orbPanel.orderOut(nil)
        } else {
            orbPanel.orderFrontRegardless()
        }
        let title = state.rawValue.capitalized
        updateStatus(title, running: true)
    }

    private func consumeOutput(_ text: String) {
        outputBuffer += text
        while let newline = outputBuffer.firstIndex(of: "\n") {
            let line = String(outputBuffer[..<newline])
            outputBuffer.removeSubrange(...newline)
            if line.hasPrefix("NANCY_STATE:"),
               let state = NancyState(rawValue: String(line.dropFirst(12))) {
                applyState(state)
            }
        }
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
            let outputPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = error
            outputPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else {
                    handle.readabilityHandler = nil
                    return
                }
                output.write(data)
                if let text = String(data: data, encoding: .utf8) {
                    DispatchQueue.main.async { self?.consumeOutput(text) }
                }
            }
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONUNBUFFERED"] = "1"
            process.environment = environment
            process.terminationHandler = { [weak self] finished in
                outputPipe.fileHandleForReading.readabilityHandler = nil
                output.closeFile()
                error.closeFile()
                DispatchQueue.main.async {
                    guard let self else { return }
                    if self.companion === finished { self.companion = nil }
                    self.applyState(.idle)
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
        applyState(.idle)
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
