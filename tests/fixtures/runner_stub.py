import json
import sys

# Stand-in for scripts/stow_sync.py in the offscreen Runner harness: one JSON
# line and exit, so the Runner's normal output path is exercised without the
# real helper, HOME or config.
print(json.dumps({"ok": True, "stub_args": sys.argv[1:]}))
