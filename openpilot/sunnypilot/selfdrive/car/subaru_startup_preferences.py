"""Application-owned ignition permission and panda-health adapter for Subaru settings."""

from pathlib import Path
from uuid import UUID

from opendbc.sunnypilot.car.subaru.startup_preferences import StartupPreferences, startup_preferences_supported
from opendbc.sunnypilot.car.subaru.values_ext import SubaruFlagsSP


def startup_preferences_enabled(params):
  return params.get_bool("SubaruEnableAVHAtStartup") or params.get_bool("SubaruDisableStartStopAtStartup")


def startup_cycle_available(params, now):
  if not startup_preferences_enabled(params):
    return False
  token = params.get("SubaruStartupPreferencesCycle")
  try:
    return 0 <= now - float(token) <= 20 and token != params.get("SubaruStartupPreferencesConsumed")
  except (ValueError, TypeError):
    return False


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
      if not startup_preferences_enabled(params):
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
                    and armed_boot != self.boot_id and 0 <= now <= 120 and startup_preferences_enabled(params))
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

  def __init__(self, params, CP, CP_SP, now, replay_mode=False):
    self.policy = None
    self.safety_ready_since = None
    self.safety_model = None
    self.safety_param = None
    if replay_mode or not startup_preferences_supported(CP) or not startup_preferences_enabled(params):
      return
    enable_avh = bool(CP_SP.flags & SubaruFlagsSP.ENABLE_AVH_AT_STARTUP)
    disable_start_stop = bool(CP_SP.flags & SubaruFlagsSP.DISABLE_START_STOP_AT_STARTUP)
    if not (enable_avh or disable_start_stop):
      return
    token = params.get('SubaruStartupPreferencesCycle')
    try:
      started = float(token)
    except (ValueError, TypeError):
      return
    if not 0 <= now - started <= 20 or token == params.get('SubaruStartupPreferencesConsumed'):
      return
    params.put('SubaruStartupPreferencesConsumed', token, block=True)
    self.policy = StartupPreferences(enable_avh, disable_start_stop)
    self.policy.set_ignition(False, started)
    self.policy.set_ignition(True, started)
    self.safety_model = str(CP.safetyConfigs[0].safetyModel)
    self.safety_param = int(CP.safetyConfigs[0].safetyParam)

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
    if str(panda.safetyModel) != self.safety_model or int(panda.safetyParam) != self.safety_param:
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
    # Observe the eligibility stability interval during the hardware wait, rather
    # than adding three seconds afterward and exhausting a cold-start cycle.
    ready = now - self.safety_ready_since >= 10
    return [(p.address, p.data, p.bus) for p in self.policy.update(now, requests_allowed=ready)]
