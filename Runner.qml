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
  // The interpreter is a property so the offscreen harness can point it at a
  // path that fails to start (B1); production keeps the default.
  property string python: "python3"

  // The payload parameter is `result`, not `data`: `data` is Item's default
  // property and a signal parameter of that name shadows it.
  signal statusReady(var result, bool fetch)
  signal actionReady(string tag, var result)
  signal failed(string tag, string message)

  readonly property bool busy: proc.running || queue.length > 0

  property var queue: []
  property var current: null
  property bool timedOut: false
  // Every dequeued request gets an increasing id. `activeId` is the id of the
  // invocation that owns the Process right now, and `settledId` the id whose
  // terminal result was already delivered, so a stop event can never settle an
  // invocation twice or a new request with an old invocation's outcome.
  property int nextRequestId: 1
  property int activeId: 0
  property int settledId: 0

  function setting(name, fallback) {
    var value = root.settings ? root.settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  // Global flags are appended after the command; the backend extracts them
  // from anywhere in argv.
  function globalArgs(request) {
    var args = []
    var configPath = String(root.setting("configPath", ""))
    var stateDir = String(root.setting("stateDir", ""))
    if (configPath !== "") args = args.concat(["--config", configPath])
    if (stateDir !== "") args = args.concat(["--state-dir", stateDir])
    // The helper keeps its own monotonic deadline and clamps every child to
    // what is left, so it answers and exits before this Runner's timeout (B4).
    // 15 s of the budget stay for that answer and its cleanup.
    var budget = Model.runnerBudgetSeconds(String((request || {}).tag || ""))
    args = args.concat(["--deadline", String(budget - 15)])
    return args
  }

  // The one budget table lives in Model.runnerBudgetSeconds; this adds the
  // 10 s grace the Runner keeps after the helper's own deadline.
  function timeoutFor(request) {
    return Model.runnerBudgetSeconds(String((request || {}).tag || "")) * 1000 + 10000
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
    var request = next.request
    request.id = root.nextRequestId
    root.nextRequestId = root.nextRequestId + 1
    root.current = request
    root.activeId = request.id
    root.queue = next.queue
    root.timedOut = false
    // Open the write channel before starting so the helper can read stdin.
    proc.stdinEnabled = true
    var argv = [root.python, "-u", root.scriptPath].concat(root.globalArgs(root.current)).concat(root.current.args)
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
    // Only the invocation that owns the Process may deliver its result.
    if (request.id !== root.activeId) return
    root.settledId = request.id
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
    // `current`, so a normal completion is advanced by `finish`, a timeout is
    // restarted here once the terminated process has finished, and a native
    // FailedToStart (which emits nothing but this stop) is settled here.
    var request = root.current
    var decision = Model.runnerSettle({
      hasCurrent: request !== null,
      timedOut: root.timedOut,
      settled: request !== null && request.id === root.settledId
    })
    if (root.timedOut) root.timedOut = false
    if (decision.settle) {
      timeoutTimer.stop()
      root.settledId = request.id
      root.current = null
      root.failed(request.tag, "The Stow Sync helper could not start.")
      root.pump()
      return
    }
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
      root.settledId = root.current.id
      root.current = null
      proc.running = false
      root.failed(tag, "Stow Sync helper timed out")
    }
  }
}
