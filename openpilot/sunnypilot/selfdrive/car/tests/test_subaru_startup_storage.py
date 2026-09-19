"""Integration test against the built Params library, using isolated storage."""
from openpilot.common.params import Params, ParamKeyFlag
from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import IgnitionCycleTracker


def test_permission_survives_shutdown_but_not_reuse(tmp_path):
  old_boot = '11111111-1111-4111-8111-111111111111'
  new_boot = '22222222-2222-4222-8222-222222222222'
  params = Params(str(tmp_path))
  params.put_bool('SubaruEnableAVHAtStartup', True, block=True)
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


def test_vanilla_upstream_dashcam_platform_never_claims_permission(tmp_path):
  from opendbc.car.subaru.interface import CarInterface
  from opendbc.car.subaru.values import CAR
  from opendbc.car.structs import CarParamsSP
  from openpilot.sunnypilot.selfdrive.car.subaru_startup_preferences import RuntimeStartupPreferences

  params = Params(str(tmp_path))
  params.put_bool('SubaruEnableAVHAtStartup', True, block=True)
  params.put('SubaruStartupPreferencesCycle', '30', block=True)
  cp = CarInterface.get_non_essential_params(CAR.SUBARU_OUTBACK_2023)
  assert cp.dashcamOnly
  original = cp.safetyConfigs[0].safetyParam
  runtime = RuntimeStartupPreferences(params, cp, CarParamsSP(), 31)
  assert runtime.policy is None
  assert cp.safetyConfigs[0].safetyParam == original
  assert params.get('SubaruStartupPreferencesConsumed') is None


def test_parameter_initialization_authorizes_only_fresh_unconsumed_cycle(tmp_path, monkeypatch):
  from openpilot.sunnypilot.selfdrive.car import interfaces

  params = Params(str(tmp_path))
  monkeypatch.delenv("REPLAY", raising=False)
  monkeypatch.setattr(interfaces.time, "monotonic", lambda: 31)

  def options():
    return {key: value for item in interfaces.initialize_params(params) for key, value in item.items()}

  assert not options()["SubaruStartupCycleAuthorized"]
  assert not bool(options()["SubaruEnableAVHAtStartup"])
  assert not bool(options()["SubaruDisableStartStopAtStartup"])
  params.put_bool("SubaruEnableAVHAtStartup", True, block=True)
  params.put("SubaruStartupPreferencesCycle", "30", block=True)
  assert options()["SubaruStartupCycleAuthorized"] is True
  assert options()["SubaruEnableAVHAtStartup"] is True
  params.put("SubaruStartupPreferencesConsumed", "30", block=True)
  assert options()["SubaruStartupCycleAuthorized"] is False
  params.remove("SubaruStartupPreferencesConsumed")
  monkeypatch.setenv("REPLAY", "1")
  assert options()["SubaruStartupCycleAuthorized"] is False
  monkeypatch.setenv("REPLAY", "")
  assert options()["SubaruStartupCycleAuthorized"] is False
  monkeypatch.delenv("REPLAY")
  monkeypatch.setattr(interfaces.time, "monotonic", lambda: 51)
  assert options()["SubaruStartupCycleAuthorized"] is False
