#!/usr/bin/env python3
"""Replay a passive JSONL capture without transmitting CAN commands."""

import argparse
import json

from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import replay

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('capture', help='passive JSONL capture; never transmits')
  args = parser.parse_args()
  controller, proposals = replay(args.capture)
  for proposal in proposals:
    print(json.dumps({'dry_run': True, 't': proposal.time, 'address': hex(proposal.address), 'bus': proposal.bus, 'data': proposal.data.hex()}))
  print(json.dumps({'settled': {hex(k): v for k, v in controller.settled.items()}, 'aborted': controller.aborted}))
