"""Integration test against the built Params library, using isolated storage."""
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import IgnitionCycleTracker


def test_permission_survives_shutdown_but_not_reuse(tmp_path):
  old_boot = '11111111-1111-4111-8111-111111111111'
  new_boot = '22222222-2222-4222-8222-222222222222'
  params = Params(str(tmp_path))
  params.put_bool('SubaruStartupPreferences', True, block=True)
  params.put_bool('SubaruStartupPreferencesColdBoot', True, block=True)
  tracker = IgnitionCycleTracker(old_boot)
  tracker.update(False, 500, params)
  tracker.update(False, 502, params)
  del params
  params = Params(str(tmp_path))
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  assert params.get('SubaruStartupPreferencesArmedBoot') == old_boot
  IgnitionCycleTracker(new_boot).update(True, 30, params)
  assert params.get('SubaruStartupPreferencesArmedBoot') is None
  assert params.get('SubaruStartupPreferencesCycle') == '30'
  params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  IgnitionCycleTracker(new_boot).update(True, 40, params)
  assert params.get('SubaruStartupPreferencesCycle') is None


def test_runtime_claim_with_upstream_car_params(tmp_path):
  from opendbc.car.subaru.interface import CarInterface
  from opendbc.car.subaru.values import CAR
  from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import RuntimeStartupPreferences

  params = Params(str(tmp_path))
  params.put_bool('SubaruStartupPreferences', True, block=True)
  params.put('SubaruStartupPreferencesCycle', '30', block=True)
  cp = CarInterface.get_non_essential_params(CAR.SUBARU_OUTBACK_2023)
  assert cp.safetyConfigs[0].safetyParam == 9
  first = RuntimeStartupPreferences(params, cp, 31)
  assert first.policy is not None
  assert cp.safetyConfigs[0].safetyParam == 25
  assert params.get('SubaruStartupPreferencesConsumed') == '30'
  fresh_cp = CarInterface.get_non_essential_params(CAR.SUBARU_OUTBACK_2023)
  restarted = RuntimeStartupPreferences(params, fresh_cp, 32)
  assert restarted.policy is None
  assert fresh_cp.safetyConfigs[0].safetyParam == 9
