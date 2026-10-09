import QtQuick
import Quickshell.Io

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

  signal statusReady(var data, bool fetch)
  signal actionReady(string tag, var data)
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
    if (request.isStatus) {
      for (var i = 0; i < root.queue.length; i++) {
        if (root.queue[i].isStatus && root.queue[i].fetch === request.fetch) return
      }
    }
    root.queue = root.queue.concat([request])
    root.pump()
  }

  function pump() {
    if (proc.running || root.queue.length === 0) return
    root.current = root.queue[0]
    root.queue = root.queue.slice(1)
    root.timedOut = false
    // Open the write channel before starting so the helper can read stdin.
    proc.stdinEnabled = true
    proc.command = ["python3", "-u", root.scriptPath].concat(root.globalArgs()).concat(root.current.args)
    timeoutTimer.interval = root.timeoutFor(root.current)
    proc.running = true
    timeoutTimer.restart()
  }

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
    var data
    try {
      data = JSON.parse(raw)
    } catch (error) {
      root.failed(request.tag, "Could not parse Stow Sync helper output.")
      root.finish()
      return
    }
    if (request.isStatus) {
      if (data.ok) root.statusReady(data, request.fetch)
      else root.failed(request.tag, String(data.error || "Status failed."))
    } else {
      root.actionReady(request.tag, data)
    }
    root.finish()
  }

  function afterStop() {
    // A timed-out run had its stdout suppressed; restart the queue once the
    // terminated process has actually finished.
    if (root.timedOut) {
      root.timedOut = false
      root.pump()
    }
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
