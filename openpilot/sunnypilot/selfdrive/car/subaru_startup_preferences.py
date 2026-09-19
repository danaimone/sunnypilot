"""Bounded Subaru startup preference policy and runtime adapter."""

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import UUID


BUS = 1
AVH_REQUEST = 0x6BB
STOP_REQUEST = 0x390
AVH_STATUS = 0x32B
STOP_STATUS = 0x174
THROTTLE = 0x40
GEAR = 0x48
WHEELS = 0x13A
REQUIRED = (AVH_REQUEST, STOP_REQUEST, AVH_STATUS, STOP_STATUS, THROTTLE, GEAR, WHEELS)
SAFETY_FLAG = 16
STARTUP_WINDOW = 120
# Panda allows 30 ms from physical RX to TX. Host timestamps arrive later;
# reserve 20 ms for receive buffering, scheduling and transport back to panda.
MAX_HOST_TEMPLATE_AGE = 0.010


def valid_boot_id(value):
  try:
    return str(UUID(value)) == value
  except (ValueError, TypeError, AttributeError):
    return False


def read_boot_id():
  try:
    value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    return value if valid_boot_id(value) else None
  except OSError:
    return None


class IgnitionCycleTracker:
  """One startup permission, including a verified off state from an older boot."""

  def __init__(self, boot_id=None):
    self.previous = None
    self.off_since = None
    self.boot_id = boot_id if valid_boot_id(boot_id) else None
    self.first_known_state = True
    self.off_saved = False

  def update(self, ignition, now, params):
    if ignition is None:
      if not self.first_known_state:
        params.remove('SubaruStartupPreferencesArmedBoot')
      self.previous = None
      self.off_since = None
      self.off_saved = False
      params.remove('SubaruStartupPreferencesCycle')
      return
    if not ignition:
      if self.previous is not False:
        params.remove('SubaruStartupPreferencesCycle')
        params.remove('SubaruStartupPreferencesArmedBoot')
        self.off_since = now
        self.off_saved = False
      if not params.get_bool('SubaruStartupPreferences'):
        params.remove('SubaruStartupPreferencesArmedBoot')
        self.off_saved = False
      elif self.boot_id is not None and now - self.off_since >= 2 and not self.off_saved:
        params.put('SubaruStartupPreferencesArmedBoot', self.boot_id, block=True)
        self.off_saved = True
      self.previous = False
      self.first_known_state = False
      return
    if ignition != self.previous:
      armed_boot = params.get('SubaruStartupPreferencesArmedBoot')
      cold_start = (self.first_known_state and self.boot_id is not None and valid_boot_id(armed_boot)
                    and armed_boot != self.boot_id and 0 <= now <= 120 and params.get_bool('SubaruStartupPreferences')
                    and params.get_bool('SubaruStartupPreferencesColdBoot'))
      warm_start = self.previous is False and self.off_since is not None and now - self.off_since >= 2
      # Consume persistent permission before publishing the volatile cycle.
      # A crash here skips a request instead of rearming on another boot.
      params.remove('SubaruStartupPreferencesArmedBoot')
      permission_cleared = not params.get('SubaruStartupPreferencesArmedBoot')
      if (warm_start or cold_start) and permission_cleared:
        params.put('SubaruStartupPreferencesCycle', str(now), block=True)
      else:
        params.remove('SubaruStartupPreferencesCycle')
      self.off_since = None
      self.previous = ignition
    self.first_known_state = False
    self.off_saved = False


class RuntimeStartupPreferences:
  """Adapter used by card's existing publisher, disabled unless opted in.

  Claim the manager's ignition token before proposing anything. A card crash
  or restart then skips the remainder of that ignition cycle. Cold starts
  require a persisted off-state permission from a different kernel boot.
  """

  def __init__(self, params, CP, now, replay_mode=False):
    self.policy = None
    self.safety_ready_since = None
    supported = (
      str(CP.carFingerprint) in ('SUBARU_OUTBACK_2023', 'SUBARU_CROSSTREK_2026')
      and not CP.passive
      and not CP.openpilotLongitudinalControl
      and len(CP.safetyConfigs) == 1
      and int(CP.safetyConfigs[0].safetyParam) == 9
    )
    if replay_mode or not supported or not params.get_bool('SubaruStartupPreferences'):
      return
    token = params.get('SubaruStartupPreferencesCycle')
    try:
      started = float(token)
    except (ValueError, TypeError):
      return
    if not 0 <= now - started <= 20 or token == params.get('SubaruStartupPreferencesConsumed'):
      return
    params.put('SubaruStartupPreferencesConsumed', token, block=True)
    self.policy = StartupPreferences()
    self.policy.set_ignition(False, started)
    self.policy.set_ignition(True, started)
    CP.safetyConfigs[0].safetyParam |= SAFETY_FLAG

  def observe(self, can_packets):
    if self.policy is not None:
      for nanos, frames in can_packets:
        for address, data, bus in frames:
          self.policy.observe(address, data, bus, nanos / 1e9)

  def update(self, now, can_valid, pandas_valid, pandas):
    if self.policy is None:
      return []
    if not can_valid or not pandas_valid or len(pandas) != 1:
      self.safety_ready_since = None
      self.policy.stable_since = None
      return []
    panda = pandas[0]
    # A diagnostic fault can remain latched after normal CAN traffic resumes.
    # Skip this ignition cycle rather than issuing convenience requests on it.
    if panda.faults or panda.heartbeatLost:
      self.policy.aborted = True
      self.safety_ready_since = None
      return []
    if not (panda.ignitionLine or panda.ignitionCan):
      self.policy.aborted = True
      return []
    if str(panda.safetyModel) != 'subaru' or int(panda.safetyParam) != (9 | SAFETY_FLAG):
      self.safety_ready_since = None
      return []
    if self.safety_ready_since is None:
      self.safety_ready_since = now
    # Panda enforces its own 10-second window from safety initialization. Wait
    # from the first observed matching panda state so our one attempt isn't
    # consumed before that hardware gate opens.
    if panda.safetyRxChecksInvalid:
      self.policy.stable_since = None
      return []
    # Observe the parked stability interval during the hardware wait, rather
    # than adding three seconds afterward and exhausting a cold-start cycle.
    ready = now - self.safety_ready_since >= 10
    return [(p.address, p.data, p.bus) for p in self.policy.update(now, requests_allowed=ready)]


def checksum(address: int, data: bytes) -> int:
  return ((address & 0xFF) + (address >> 8) + sum(data[1:])) & 0xFF


def request_packet(address: int, original: bytes, counter_step: int = 1) -> bytes:
  """Construct one candidate pulse, preserving every unrelated payload bit."""
  if address not in (AVH_REQUEST, STOP_REQUEST) or len(original) != 8 or checksum(address, original) != original[0]:
    raise ValueError("Invalid request template")
  if counter_step != 1 and not (address == AVH_REQUEST and counter_step == 2):
    raise ValueError("Invalid request counter step")
  index, mask = (2, 0x03) if address == AVH_REQUEST else (6, 0x40)
  if original[index] & mask:
    raise ValueError("Manual request already active")
  data = bytearray(original)
  data[1] = (data[1] & 0xF0) | ((data[1] + counter_step) & 0x0F)
  data[index] |= 0x02 if address == AVH_REQUEST else 0x40
  data[0] = checksum(address, data)
  return bytes(data)


@dataclass(frozen=True)
class Proposal:
  time: float
  address: int
  data: bytes
  bus: int = BUS


class StartupPreferences:
  """One-shot proposal generator for a known parked Outback ignition cycle.

  Inputs and deadlines use one monotonic clock, in seconds. Unknown/corrupt
  state never means off. A missing acknowledgement never triggers a retry of
  the start-stop toggle. A manual request retires only its respective setting.
  """

  def __init__(self):
    self.ignition = None
    self.started = None
    self.stable_since = None
    self.frames = {}
    self.settled = {}
    self.pending = {}
    self.aborted = False
    self.last_time = None
    self.avh_followup = None
    self.avh_tx_confirmed_at = None

  def set_ignition(self, on: bool, now: float):
    if not on:
      self.started = None
      self.frames.clear()
      self.stable_since = None
      self.settled.clear()
      self.pending.clear()
      self.aborted = False
      self.avh_followup = None
      self.avh_tx_confirmed_at = None
    elif self.ignition is False:
      self.started = now
      self.frames.clear()
    self.ignition = on

  def observe(self, address: int, data: bytes, bus: int, now: float):
    if address == AVH_REQUEST and bus in (BUS + 128, BUS + 192):
      # Returned/rejected packets are panda metadata, not factory button input.
      # Anchor the follow-up to the first accepted transmission, since unequal
      # host-to-panda delays can compress two publication times below 45 ms.
      if self.avh_followup is not None and self.ignition is True:
        sent, _, template = self.avh_followup
        if data == request_packet(AVH_REQUEST, template) and now >= sent:
          if bus == BUS + 192 or now - sent > 0.025:
            self.avh_followup = None
          elif self.avh_tx_confirmed_at is None:
            self.avh_tx_confirmed_at = now
      return
    if bus != BUS or address not in REQUIRED or self.ignition is not True:
      return
    if len(data) != 8 or checksum(address, data) != data[0]:
      self.frames.pop(address, None)
      self.stable_since = None
      return
    previous = self.frames.get(address)
    if previous and now < previous[0]:
      self.aborted = True
      return
    # Replayed counters cannot keep state fresh. Any discontinuity requires a
    # new consecutive sample before using this message again.
    sequential = bool(previous and (data[1] & 15) == ((previous[1][1] + 1) & 15))
    if previous and (data[1] & 15) == (previous[1][1] & 15):
      return
    self.frames[address] = (now, data, sequential)
    if address == AVH_REQUEST and data[2] & 3:
      self.settled[address] = "manual override"
      self.pending.pop(address, None)
      self.avh_followup = None
    if address == STOP_REQUEST and data[6] & 0x40 and address not in self.pending:
      self.settled[address] = "manual override"

  def update(self, now: float, *, requests_allowed: bool = True) -> list[Proposal]:
    if self.last_time is not None and now < self.last_time:
      self.aborted = True
    self.last_time = now
    if self.ignition is not True or self.started is None or self.aborted:
      return []
    if now - self.started > STARTUP_WINDOW:
      self.aborted = True
      return []
    # Requests run at roughly 1 Hz / 10 Hz; all other inputs must be recent.
    for address in REQUIRED:
      record = self.frames.get(address)
      max_age = 1.5 if address == AVH_REQUEST else 0.3
      if record is None or not record[2] or not 0 <= now - record[0] <= max_age:
        self.stable_since = None
        return []
    data = {a: self.frames[a][1] for a in REQUIRED}
    wheel_bits = int.from_bytes(data[WHEELS], 'little')
    wheel_speeds = [(wheel_bits >> bit) & 0x1FFF for bit in (12, 25, 38, 51)]
    parked = data[GEAR][3] == 4 and not any(wheel_speeds) and data[THROTTLE][4] == 0
    driving_away = data[GEAR][3] == 121
    if not (parked or driving_away):
      self.stable_since = None
      self.avh_followup = None
      return []
    rpm = int.from_bytes(data[THROTTLE][2:4], 'little') & 0x1FFF
    if rpm < 400 or not (data[STOP_STATUS][2] & 0x08):
      self.stable_since = None
      return []
    if self.stable_since is None:
      self.stable_since = now
    if not requests_allowed or now - self.started < 10 or now - self.stable_since < 3:
      return []

    desired = {AVH_REQUEST: bool(data[AVH_STATUS][5] & 0x20), STOP_REQUEST: data[STOP_STATUS][4] == 0xC0}
    for address in tuple(self.pending):
      if desired[address]:
        self.settled[address] = "acknowledged"
        del self.pending[address]
      elif now - self.pending[address] >= 2:
        self.settled[address] = "unacknowledged; no retry"
        del self.pending[address]
    # One AVH button press consists of at most two frames, 50 ms apart. A new
    # factory template, manual action, acknowledgement, or late scheduler drops
    # the second frame; it is never retried later in the ignition cycle. Wait
    # at least 50 ms after the accepted TX receipt, while retaining the original
    # 75 ms publication deadline to bound late delivery and template age.
    if self.avh_followup is not None:
      sent, template_time, template = self.avh_followup
      age = now - sent
      if desired[AVH_REQUEST] or AVH_REQUEST not in self.pending or self.frames[AVH_REQUEST][0] != template_time or age > 0.075:
        self.avh_followup = None
      elif self.avh_tx_confirmed_at is not None and now - self.avh_tx_confirmed_at >= 0.05:
        self.avh_followup = None
        return [Proposal(now, AVH_REQUEST, request_packet(AVH_REQUEST, template, counter_step=2))]
    for address in (AVH_REQUEST, STOP_REQUEST):
      if address in self.settled or address in self.pending:
        continue
      if desired[address]:
        self.settled[address] = "already correct"
        continue
      # Only the demonstrated start-stop enabled value may trigger a toggle.
      if address == STOP_REQUEST and data[STOP_STATUS][4] != 0:
        continue
      if self.pending or now - self.frames[address][0] > MAX_HOST_TEMPLATE_AGE:
        continue
      if (data[AVH_REQUEST][2] & 3) or (data[STOP_REQUEST][6] & 0x40):
        continue
      self.pending[address] = now
      if address == AVH_REQUEST:
        self.avh_followup = (now, self.frames[address][0], data[address])
        self.avh_tx_confirmed_at = None
      return [Proposal(now, address, request_packet(address, data[address]))]
    return []


def replay(path: str):
  controller = StartupPreferences()
  proposals = []
  with open(path) as stream:
    for line in stream:
      row = json.loads(line)
      now = row.get('t')
      if now is None:
        continue
      if 'ignition' in row:
        states = row['ignition']
        if states:
          controller.set_ignition(any(s['line'] or s['can'] for s in states), now)
      for bus, address, payload in row.get('can', []):
        controller.observe(address, bytes.fromhex(payload), bus, now)
      proposals.extend(controller.update(now))
  return controller, proposals
