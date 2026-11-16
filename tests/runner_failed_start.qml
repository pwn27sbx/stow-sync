import QtQuick
import Quickshell

// B1 real-Process harness, run offscreen by
// tests/test_stow_sync.py::RunnerFailedStartTests through
// `qs -p tests/runner_failed_start.qml`.
//
// Stage 1 starts the helper with a python that does not exist: Quickshell
// reports NativeProcess::FailedToStart, which emits only `running false`.
// The Runner must settle that invocation exactly once (`failed`), clear it and
// keep pumping. Stage 2 restores a real python and proves the next refresh
// runs; stage 3 proves a following action runs too, all without a reload.
//
// Quickshell 0.3.2 resolves relative URLs of a `-p` file to its blackhole, so
// the Runner and the stub script paths come from the environment (the Python
// test passes absolute paths).
Item {
  id: harness

  property int stage: 0
  readonly property string runnerPath: Quickshell.env("STOW_SYNC_TEST_RUNNER")
  readonly property string stubPath: Quickshell.env("STOW_SYNC_TEST_STUB")

  function pass() {
    console.log("PASS")
    Qt.quit()
  }

  function fail(why) {
    console.log("FAIL " + why)
    Qt.quit()
  }

  Component.onCompleted: {
    if (!harness.runnerPath) return harness.fail("no runner path")
    if (!harness.stubPath) return harness.fail("no stub path")
  }

  Loader {
    id: loader
    source: harness.runnerPath ? "file://" + harness.runnerPath : ""
    onLoaded: {
      item.settingsReady = true
      item.settings = ({})
      // A python that cannot start: FailedToStart, no output, no exit event.
      item.python = "/nonexistent/python3"
      item.scriptPath = harness.stubPath
      item.refreshStatus(false)
    }
  }

  Connections {
    target: loader.item
    ignoreUnknownSignals: true

    function onFailed(tag, message) {
      if (harness.stage === 0) {
        if (String(tag) !== "status") return harness.fail("failed tag " + String(tag))
        if (String(message || "").indexOf("could not start") < 0)
          return harness.fail("failed message " + String(message))
        harness.stage = 1
        loader.item.python = "python3"
        loader.item.refreshStatus(false)
        return
      }
      harness.fail("unexpected failure " + String(tag) + ": " + String(message))
    }

    function onStatusReady(result, fetch) {
      if (harness.stage !== 1) return harness.fail("status in stage " + harness.stage)
      if (!result || result.ok !== true) return harness.fail("status payload")
      harness.stage = 2
      loader.item.runAction("version", ["version"])
    }

    function onActionReady(tag, result) {
      if (harness.stage !== 2) return harness.fail("action in stage " + harness.stage)
      if (String(tag) !== "version") return harness.fail("action tag " + String(tag))
      if (!result || result.ok !== true) return harness.fail("action payload")
      harness.pass()
    }
  }

  // Every stage must deliver within 5 s (the brief's budget); the whole run is
  // also capped by `timeout 30` in the Python test.
  Timer {
    interval: 5000
    running: true
    onTriggered: harness.fail("timer in stage " + harness.stage)
  }
}
