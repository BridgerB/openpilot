#!/usr/bin/env python3
import argparse
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpilot.tools.lib.logreader import LogReader
from openpilot.selfdrive.test.process_replay.process_replay import (
  replay_process, get_process_config, check_openpilot_enabled,
)
from openpilot.selfdrive.test.process_replay.compare_logs import (
  compare_logs, format_process_diff,
)
from opendbc.car.tests.car_diff import dict_diff, IGNORE_FIELDS, TOLERANCE

CARD_CFG = get_process_config("card")


def run_card(route):
  lr = list(LogReader(route))
  if not check_openpilot_enabled(lr):
    print(f"Warning: {route} never engaged")
  return replay_process(CARD_CFG, lr)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("route")
  parser.add_argument("--ref", help="Reference route or .pkl file")
  parser.add_argument("--save", help="Save to .pkl")
  args = parser.parse_args()

  print(f"Replaying: {args.route}")
  new = run_card(args.route)
  print(f"Got {len(new)} msgs: {dict(Counter(m.which() for m in new))}")

  if args.save:
    Path(args.save).write_bytes(pickle.dumps(new))
    print(f"Saved: {args.save}")
    return 0

  if not args.ref:
    print("Use --ref to compare or --save to save")
    return 0

  ref = pickle.loads(Path(args.ref).read_bytes()) if args.ref.endswith(".pkl") else run_card(args.ref)

  diffs = compare_logs(ref, new, ignore_fields=CARD_CFG.ignore, tolerance=CARD_CFG.tolerance)

  if not diffs:
    print("PASS: no diffs")
    return 0

  diff, _ = format_process_diff(diffs)
  print(f"\n{len(diffs)} diffs:")
  print(diff)

  ref_states = [m.carState for m in ref if m.which() == "carState"]
  new_states = [m.carState for m in new if m.which() == "carState"]

  by_field = defaultdict(list)
  for i, (r, n) in enumerate(zip(ref_states, new_states)):
    for d in dict_diff(r.to_dict(), n.to_dict(), ignore=IGNORE_FIELDS, tolerance=TOLERANCE):
      by_field[d[1]].append((d[1], i, d[2], i))

  for field, fd in sorted(by_field.items()):
    print(f"  {field} ({len(fd)} diffs)")

  return 1


if __name__ == "__main__":
  sys.exit(main())
