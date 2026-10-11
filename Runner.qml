import QtQuick
import Quickshell.Io
import "Model.js" as Model

// FIFO process queue for the Stow Sync helper. Non-visual: the panel owns the
// step-by-step flow and receives results through the three signals below.
//
// One Process is reused. A request carries its own args, stdin payload and
// timeout; identical pending status calls are deduped so a burst of refreshes
// collapses into a single run.
Item {
  id: root

  property string scriptPath: ""
  property var settings: ({})
  // Set true only by BarWidget.injectPanel(); nothing starts before then, so a
  // request never runs the helper with the default (real) config (README 11a fix).
  property bool settingsReady: false

  // The payload parameter is `result`, not `data`: `data` is Item's default
  // property and a signal parameter of that name shadows it.
  signal statusReady(var result, bool fetch)
  signal actionReady(string tag, var result)
  signal failed(string tag, string message)

  readonly property bool busy: proc.running || queue.length > 0

  property var queue: []
  property var current: null
  property bool timedOut: false

  function setting(name, fallback) {
    var value = root.settings ? root.settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  // Global flags are appended after the command; the backend extracts them
  // from anywhere in argv.
  function globalArgs() {
    var args = []
    var configPath = String(root.setting("configPath", ""))
    var stateDir = String(root.setting("stateDir", ""))
    if (configPath !== "") args = args.concat(["--config", configPath])
    if (stateDir !== "") args = args.concat(["--state-dir", stateDir])
    return args
  }

  // Backend timeout plus a 10 s grace window.
  function timeoutFor(request) {
    var seconds = 20
    if (request.isStatus) seconds = request.fetch ? 120 : 20
    else if (request.tag === "push" || request.tag === "pull") seconds = 300
    else if (request.tag === "commit") seconds = 30
    else if (request.tag === "setup-prereqs") seconds = 60
    else if (request.tag === "setup-repos") seconds = 70
    else if (request.tag === "setup-connect") seconds = 600
    else if (request.tag === "setup-clone") seconds = 900
    else if (request.tag === "setup-plan") seconds = 120
    else if (request.tag === "setup-apply") seconds = 1800
    else if (request.tag === "setup-undo") seconds = 300
    else if (request.tag === "setup-backups") seconds = 30
    return seconds * 1000 + 10000
  }

  function refreshStatus(fetch) {
    enqueue({
      isStatus: true,
      fetch: !!fetch,
      tag: fetch ? "status-fetch" : "status",
      args: fetch ? ["status", "--fetch"] : ["status"],
      stdin: ""
    })
  }

  function runAction(tag, args, stdinData) {
    enqueue({
      isStatus: false,
      fetch: false,
      tag: String(tag),
      args: args || [],
      stdin: stdinData === undefined || stdinData === null ? "" : String(stdinData)
    })
  }

  function enqueue(request) {
    root.queue = Model.enqueue(root.queue, request)
    root.pump()
  }

  function pump() {
    // Never start before settings are injected: queue everything until then.
    if (!Model.runnerMayStart(root.settingsReady, root.queue.length > 0)) return
    // `current` is set for the whole life of a run and cleared in `finish`
    // (or the timeout); guarding on it too stops a stop event from starting
    // the next request before the current one has been handled.
    if (proc.running || root.current !== null) return
    var next = Model.nextRequest(root.queue)
    if (!next.request) return
    root.current = next.request
    root.queue = next.queue
    root.timedOut = false
    // Open the write channel before starting so the helper can read stdin.
    proc.stdinEnabled = true
    var argv = ["python3", "-u", root.scriptPath].concat(root.globalArgs()).concat(root.current.args)
    // The panel's own apply/undo is the real (non-test) path: opt in explicitly
    // so the backend's real-HOME guard allows it (README 10.0).
    if (root.current.tag === "setup-apply" || root.current.tag === "setup-undo")
      argv = ["env", "STOW_SYNC_ALLOW_REAL_SETUP=1"].concat(argv)
    proc.command = argv
    timeoutTimer.interval = root.timeoutFor(root.current)
    proc.running = true
    timeoutTimer.restart()
  }

  onSettingsReadyChanged: if (root.settingsReady) root.pump()

  function finish() {
    timeoutTimer.stop()
    root.current = null
    root.pump()
  }

  function handle(text) {
    var request = root.current
    if (!request) return
    var raw = String(text || "").trim()
    if (raw.length > 5 * 1024 * 1024) {
      root.failed(request.tag, "Stow Sync response exceeded the buffer limit.")
      root.finish()
      return
    }
    if (raw === "") {
      root.failed(request.tag, "The Stow Sync helper returned no output.")
      root.finish()
      return
    }
    var result
    try {
      result = JSON.parse(raw)
    } catch (error) {
      root.failed(request.tag, "Could not parse Stow Sync helper output.")
      root.finish()
      return
    }
    if (request.isStatus) {
      if (result.ok) root.statusReady(result, request.fetch)
      else root.failed(request.tag, String(result.error || "Status failed."))
    } else {
      root.actionReady(request.tag, result)
    }
    root.finish()
  }

  function afterStop() {
    // The process has actually stopped. `pump` no-ops while a run is still in
    // `current`, so a normal completion is advanced by `finish` and a timeout
    // is restarted here once the terminated process has finished.
    if (root.timedOut) root.timedOut = false
    root.pump()
  }

  Process {
    id: proc
    stdinEnabled: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (!root.timedOut) root.handle(text)
    }
    stderr: StdioCollector { waitForEnd: true }
    onStarted: {
      if (root.current && root.current.stdin !== "") proc.write(String(root.current.stdin) + "\n")
      // Closing the write channel sends EOF, which the helper's stdin read
      // needs before it can answer.
      proc.stdinEnabled = false
    }
    onRunningChanged: if (!running) root.afterStop()
  }

  Timer {
    id: timeoutTimer
    repeat: false
    onTriggered: {
      if (!proc.running || !root.current) return
      var tag = root.current.tag
      root.timedOut = true
      root.current = null
      proc.running = false
      root.failed(tag, "Stow Sync helper timed out")
    }
  }
}
