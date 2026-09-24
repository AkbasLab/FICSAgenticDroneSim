#!/usr/bin/env python3
"""Add JSONL logging to the baseline Llama agent.

The baseline agent prints its planning output but writes no log, so planning
latency and raw model output cannot be recorded from a run. This script patches
the agent in place to append one JSON object per planning call.

    python tools/apply_logging.py            # patch
    python tools/apply_logging.py --revert   # restore from the backup
    python tools/apply_logging.py --check    # report status, change nothing

Paths default to this repository, so it works on any machine and any clone.
Override with --target and --logdir if you keep the agent elsewhere.

Each log line carries: timestamp, drone name, model id, the instruction typed,
the model's raw output, and plan_seconds. Console output is unchanged.
"""

import argparse
import io
import json
import os
import py_compile
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGET = os.path.join(REPO, "baseline", "llama_airsim_agent.py")
DEFAULT_LOGDIR = os.path.join(REPO, "runs")

MARKER = "agent-log.jsonl"

OLD_CALL = '        response = ollama.chat('
NEW_CALL = '        _t0 = time.time()\n        response = ollama.chat('

OLD_RAW = ('        raw = response["message"]["content"]\n'
           '        print(f"  [model raw output] {raw}")')

# The agent already imports json and time at module level; this block relies on
# that, on MODEL, and on self.vehicle_name. --check verifies all three.
NEW_RAW_TEMPLATE = OLD_RAW + '''
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "drone": self.vehicle_name,
                    "model": MODEL,
                    "instruction": user_prompt,
                    "raw_output": raw,
                    "plan_seconds": round(time.time() - _t0, 2),
                }) + "\\n")
        except Exception as _e:
            print(f"  [log write failed: {_e}]")'''

LOG_PATH_DECL = '_LOG_PATH = %s\n'

PRECONDITIONS = [
    ("import json", "the log block calls json.dumps"),
    ("import time", "the log block calls time.time"),
    ("MODEL", "the log block records the model id"),
    ("self.vehicle_name", "the log block records which drone planned"),
]


def read(path):
    # The agent files carry a UTF-8 BOM; utf-8-sig strips it on read.
    return io.open(path, encoding="utf-8-sig").read()


def check(target):
    if not os.path.isfile(target):
        print("  target not found: %s" % target)
        return False
    src = read(target)
    ok = True
    if MARKER in src:
        print("  already patched")
        return True
    for needle, why in PRECONDITIONS:
        present = needle in src
        print("  %-20s %-8s (%s)" % (needle, "present" if present else "MISSING", why))
        ok = ok and present
    for name, old in [("ollama.chat call", OLD_CALL), ("raw output block", OLD_RAW)]:
        n = src.count(old)
        print("  %-20s found %d time(s)" % (name, n))
        ok = ok and n == 1
    return ok


def patch(target, logdir):
    src = read(target)
    if MARKER in src:
        print("  already patched -- nothing to do")
        return 0
    if not check(target):
        print("  ABORTED -- preconditions not met. File not modified.")
        return 1

    if not os.path.isdir(logdir):
        os.makedirs(logdir)
        print("  created %s" % logdir)

    backup = target + ".prelog.bak"
    shutil.copy2(target, backup)
    print("  backup -> %s" % backup)

    log_path = os.path.join(logdir, MARKER)
    # repr() gives a correctly escaped Python string literal on Windows paths.
    declaration = LOG_PATH_DECL % repr(log_path)

    src = src.replace(OLD_CALL, NEW_CALL, 1)
    src = src.replace(OLD_RAW, NEW_RAW_TEMPLATE, 1)

    # Put the log path beside the other module-level constants.
    anchor = "MODEL = "
    idx = src.index(anchor)
    src = src[:idx] + declaration + src[idx:]

    io.open(target, "w", encoding="utf-8", newline="\n").write(src)
    print("  patched %s" % target)
    print("  log     -> %s" % log_path)

    try:
        py_compile.compile(target, doraise=True)
        print("  syntax OK")
        return 0
    except Exception as exc:
        shutil.copy2(backup, target)
        print("  SYNTAX ERROR -- reverted from backup: %s" % exc)
        return 1


def revert(target):
    backup = target + ".prelog.bak"
    if not os.path.isfile(backup):
        print("  no backup at %s" % backup)
        return 1
    shutil.copy2(backup, target)
    print("  restored %s from backup" % target)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default=DEFAULT_TARGET, help="agent file to patch")
    ap.add_argument("--logdir", default=DEFAULT_LOGDIR, help="directory for agent-log.jsonl")
    ap.add_argument("--revert", action="store_true", help="restore the pre-patch backup")
    ap.add_argument("--check", action="store_true", help="report status only")
    args = ap.parse_args()

    print("  target: %s" % args.target)
    if args.revert:
        return revert(args.target)
    if args.check:
        return 0 if check(args.target) else 1
    return patch(args.target, args.logdir)


if __name__ == "__main__":
    sys.exit(main())
