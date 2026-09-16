from types import SimpleNamespace

import pytest

from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import (
  IgnitionCycleTracker,
  Proposal,
  RuntimeStartupPreferences,
)


class PolicySpy:
  def __init__(self):
    self.update_calls = []
    self.observe_calls = []
    self.result = []

  def update(self, now):
    self.update_calls.append(now)
    return self.result

  def observe(self, *args):
    self.observe_calls.append(args)


class ParamsMemory:
  def __init__(self):
    self.values = {'SubaruStartupPreferences': True, 'SubaruStartupPreferencesCycle': '10.0'}

  def get(self, key):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.get(key))

  def put(self, key, value, block=False):
    assert block
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


def car_params():
  return SimpleNamespace(
    carFingerprint='SUBARU_OUTBACK_2023', passive=False, openpilotLongitudinalControl=False, safetyConfigs=[SimpleNamespace(safetyParam=9)]
  )


def panda_state(**kwargs):
  return SimpleNamespace(**({'ignitionLine': True, 'ignitionCan': False, 'safetyModel': 'subaru', 'safetyParam': 25,
                            'safetyRxChecksInvalid': False} | kwargs))


def test_runtime_claims_cycle_once_before_safety_permission():
  params = ParamsMemory()
  cp = car_params()
  first = RuntimeStartupPreferences(params, cp, 12)
  assert first.policy.started == 10
  assert cp.safetyConfigs[0].safetyParam == 25
  assert params.get('SubaruStartupPreferencesConsumed') == '10.0'
  # A fresh card with the original config cannot reuse that token.
  cp = car_params()
  assert RuntimeStartupPreferences(params, cp, 13).policy is None
  assert cp.safetyConfigs[0].safetyParam == 9


@pytest.mark.parametrize('change', ['disabled', 'replay', 'other_car', 'passive', 'longitudinal', 'other_safety', 'multi_panda'])
def test_unsupported_modes_do_not_claim_or_enable(change):
  params, cp = ParamsMemory(), car_params()
  if change == 'disabled':
    params.values['SubaruStartupPreferences'] = False
  if change == 'other_car':
    cp.carFingerprint = 'SUBARU_ASCENT_2023'
  if change == 'passive':
    cp.passive = True
  if change == 'longitudinal':
    cp.openpilotLongitudinalControl = True
  if change == 'other_safety':
    cp.safetyConfigs[0].safetyParam = 1
  if change == 'multi_panda':
    cp.safetyConfigs.append(SimpleNamespace(safetyParam=9))
  runtime = RuntimeStartupPreferences(params, cp, 12, replay_mode=change == 'replay')
  assert runtime.policy is None
  assert params.get('SubaruStartupPreferencesConsumed') is None


@pytest.mark.parametrize('token', [None, '', 'not-a-time', 'nan', 'inf', '100.0', '-50.0'])
def test_invalid_or_old_ignition_token_cannot_arm(token):
  params = ParamsMemory()
  params.values['SubaruStartupPreferencesCycle'] = token
  assert RuntimeStartupPreferences(params, car_params(), 12).policy is None


def test_no_request_before_hardware_mode_is_stable():
  runtime = RuntimeStartupPreferences(ParamsMemory(), car_params(), 12)
  runtime.policy = PolicySpy()
  runtime.policy.result = [Proposal(25, 0x6BB, b'12345678')]
  assert runtime.update(12, True, True, [panda_state(safetyParam=9)]) == []
  assert runtime.update(14, True, True, [panda_state()]) == []
  assert runtime.update(23.9, True, True, [panda_state()]) == []
  assert runtime.policy.update_calls == []
  assert runtime.update(24, True, True, [panda_state()]) == [(0x6BB, b'12345678', 1)]
  assert runtime.policy.update_calls == [24]


@pytest.mark.parametrize(
  'can_valid,pandas_valid,pandas',
  [(False, True, [panda_state()]), (True, False, [panda_state()]), (True, True, []), (True, True, [panda_state(), panda_state()])],
)
def test_invalid_vehicle_state_resets_readiness(can_valid, pandas_valid, pandas):
  runtime = RuntimeStartupPreferences(ParamsMemory(), car_params(), 12)
  runtime.policy = PolicySpy()
  runtime.safety_ready_since = 12
  assert runtime.update(25, can_valid, pandas_valid, pandas) == []
  assert runtime.safety_ready_since is None
  assert runtime.policy.update_calls == []


def test_ignition_off_aborts_without_request():
  runtime = RuntimeStartupPreferences(ParamsMemory(), car_params(), 12)
  assert runtime.update(25, True, True, [panda_state(ignitionLine=False)]) == []
  assert runtime.policy.aborted


def test_invalid_panda_rx_checks_prevent_proposals():
  runtime = RuntimeStartupPreferences(ParamsMemory(), car_params(), 12)
  runtime.policy = PolicySpy()
  runtime.safety_ready_since = 12
  runtime.policy.stable_since = 20
  assert runtime.update(25, True, True, [panda_state(safetyRxChecksInvalid=True)]) == []
  assert runtime.policy.stable_since is None
  assert runtime.policy.update_calls == []


def test_raw_packet_timestamps_are_preserved():
  runtime = RuntimeStartupPreferences(ParamsMemory(), car_params(), 12)
  runtime.policy = PolicySpy()
  runtime.observe([(12_345_000_000, [(0x390, b'12345678', 1)])])
  assert runtime.policy.observe_calls == [(0x390, b'12345678', 1, 12.345)]


def test_manager_requires_observed_off_then_on_and_debounces():
  params, tracker = ParamsMemory(), IgnitionCycleTracker()
  tracker.update(True, 10, params)  # attach mid-ignition
  assert params.get('SubaruStartupPreferencesCycle') is None
  tracker.update(False, 11, params)
  tracker.update(True, 11.5, params)  # brief ignition glitch
  assert params.get('SubaruStartupPreferencesCycle') is None
  tracker.update(False, 12, params)
  tracker.update(True, 15, params)
  assert params.get('SubaruStartupPreferencesCycle') == '15'
  tracker.update(True, 16, params)
  assert params.get('SubaruStartupPreferencesCycle') == '15'
  tracker.update(False, 20, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


def test_unknown_panda_state_cannot_create_ignition_edge():
  params, tracker = ParamsMemory(), IgnitionCycleTracker()
  tracker.update(False, 0, params)
  tracker.update(None, 5, params)
  tracker.update(True, 10, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


BOOT_A = '11111111-1111-4111-8111-111111111111'
BOOT_B = '22222222-2222-4222-8222-222222222222'
BOOT_C = '33333333-3333-4333-8333-333333333333'


def armed_cold_params():
  params = ParamsMemory()
  params.values['SubaruStartupPreferencesColdBoot'] = True
  tracker = IgnitionCycleTracker(BOOT_A)
  tracker.update(False, 500, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  tracker.update(False, 501.99, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  tracker.update(False, 502, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') == BOOT_A
  return params


def test_cold_boot_consumes_persisted_off_permission_once():
  params = armed_cold_params()
  tracker = IgnitionCycleTracker(BOOT_B)
  tracker.update(None, 25, params)  # panda has not reported ignition yet
  assert params.get('SubaruStartupPreferencesArmedBoot') == BOOT_A
  tracker.update(True, 30, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  assert params.get('SubaruStartupPreferencesCycle') == '30'
  cp = car_params()
  runtime = RuntimeStartupPreferences(params, cp, 34)
  assert runtime.policy.started == 30
  assert cp.safetyConfigs[0].safetyParam == 25
  assert RuntimeStartupPreferences(params, car_params(), 35).policy is None
  # A further full reboot while ignition is still on has no permission left.
  params.remove('SubaruStartupPreferencesCycle')
  params.remove('SubaruStartupPreferencesConsumed')
  IgnitionCycleTracker(BOOT_C).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


@pytest.mark.parametrize('boot,now,enabled,cold_enabled', [
  (BOOT_A, 30, True, True),  # manager restart in the same kernel boot
  (BOOT_B, 120.001, True, True),  # late startup
  (BOOT_B, -1, True, True),
  (BOOT_B, 30, False, True),
  (BOOT_B, 30, True, False),  # cold feature remains opt-in until vehicle test
  (None, 30, True, True),
  ('invalid', 30, True, True),
])
def test_cold_boot_rejects_unqualified_start_and_consumes_old_permission(boot, now, enabled, cold_enabled):
  params = armed_cold_params()
  params.values['SubaruStartupPreferences'] = enabled
  params.values['SubaruStartupPreferencesColdBoot'] = cold_enabled
  IgnitionCycleTracker(boot).update(True, now, params)
  assert params.get('SubaruStartupPreferencesCycle') is None
  assert params.get('SubaruStartupPreferencesArmedBoot') is None


@pytest.mark.parametrize('saved', [None, '', 'not-a-boot-id', 'null', BOOT_B])
def test_missing_invalid_or_same_boot_permission_cannot_arm(saved):
  params = ParamsMemory()
  params.values['SubaruStartupPreferencesColdBoot'] = True
  params.values['SubaruStartupPreferencesArmedBoot'] = saved
  IgnitionCycleTracker(BOOT_B).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


def test_unknown_state_after_observed_off_invalidates_permission():
  params = ParamsMemory()
  tracker = IgnitionCycleTracker(BOOT_A)
  tracker.update(False, 10, params)
  tracker.update(False, 12, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') == BOOT_A
  tracker.update(None, 13, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  tracker.update(True, 14, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


def test_cold_permission_consumed_before_cycle_publication_failure():
  params = armed_cold_params()
  original_put = params.put

  def fail_cycle_put(key, value, block=False):
    if key == 'SubaruStartupPreferencesCycle':
      raise OSError('simulated interrupted cycle write')
    original_put(key, value, block=block)

  params.put = fail_cycle_put
  with pytest.raises(OSError):
    IgnitionCycleTracker(BOOT_B).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  params.put = original_put
  IgnitionCycleTracker(BOOT_C).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


def test_stable_off_arms_once_and_disabling_clears_permission():
  params = ParamsMemory()
  writes = []
  original_put = params.put

  def record_put(key, value, block=False):
    writes.append(key)
    original_put(key, value, block=block)

  params.put = record_put
  tracker = IgnitionCycleTracker(BOOT_A)
  for now in range(10):
    tracker.update(False, now, params)
  assert writes.count('SubaruStartupPreferencesArmedBoot') == 1
  params.values['SubaruStartupPreferences'] = False
  tracker.update(False, 10, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None


def test_new_boot_observing_off_first_still_uses_normal_ignition_edge():
  params = armed_cold_params()
  tracker = IgnitionCycleTracker(BOOT_B)
  tracker.update(False, 30, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  tracker.update(True, 33, params)
  assert params.get('SubaruStartupPreferencesCycle') == '33'
  assert params.get('SubaruStartupPreferencesArmedBoot') is None


def test_cold_boot_movement_consumes_cycle_instead_of_waiting_for_later_park():
  from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import GEAR, checksum
  params = armed_cold_params()
  IgnitionCycleTracker(BOOT_B).update(True, 30, params)
  runtime = RuntimeStartupPreferences(params, car_params(), 34)
  gear = bytearray(8)
  gear[3] = 121  # Drive
  gear[0] = checksum(GEAR, gear)
  runtime.observe([(35_000_000_000, [(GEAR, bytes(gear), 1)])])
  assert runtime.policy.aborted
  gear[3] = 4
  gear[0] = checksum(GEAR, gear)
  runtime.observe([(36_000_000_000, [(GEAR, bytes(gear), 1)])])
  assert runtime.policy.aborted
  assert runtime.update(50, True, True, [panda_state()]) == []
  assert RuntimeStartupPreferences(params, car_params(), 36).policy is None


def test_failed_persistent_permission_removal_cannot_publish_cycle():
  params = armed_cold_params()
  original_remove = params.remove

  def failed_arm_remove(key):
    if key != 'SubaruStartupPreferencesArmedBoot':
      original_remove(key)

  params.remove = failed_arm_remove
  IgnitionCycleTracker(BOOT_B).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesCycle') is None
  assert params.get('SubaruStartupPreferencesArmedBoot') == BOOT_A
