"""Startup settings availability and dependency behavior, without a display server."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from openpilot.sunnypilot.sunnylink.capabilities import CAPABILITY_FIELDS, _resolve_brand_capabilities

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings():
  state = SimpleNamespace(params=Mock(), CP=None, ignition=False, is_offroad=lambda: True)
  values = {"CarPlatformBundle": {"platform": "SUBARU_OUTBACK_2023"}, "SubaruStartupPreferences": True}
  state.params.get.side_effect = values.get
  state.params.get_bool.side_effect = lambda key: bool(values.get(key))
  def toggle(*args, **kwargs):
    return SimpleNamespace(action_item=Mock(), set_description=Mock())
  modules = {
    "openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base": SimpleNamespace(BrandSettings=object),
    "openpilot.selfdrive.ui.ui_state": SimpleNamespace(ui_state=state),
    "openpilot.system.ui.lib.multilang": SimpleNamespace(tr=lambda text: text),
    "openpilot.system.ui.sunnypilot.widgets.list_view": SimpleNamespace(toggle_item_sp=toggle),
  }
  with patch.dict("sys.modules", modules):
    spec = importlib.util.spec_from_file_location("subaru_settings_under_test",
      ROOT / "openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/subaru.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module.SubaruSettings(), state, values


@pytest.mark.parametrize("platform,allowed", [
  ("SUBARU_OUTBACK_2023", True), ("SUBARU_CROSSTREK_2026", True),
  ("SUBARU_CROSSTREK_2025", False), ("unknown", False), (None, False),
])
def test_supported_platforms(settings, platform, allowed):
  panel, _, values = settings
  values["CarPlatformBundle"] = {"platform": platform}
  panel.update_settings()
  panel.startup_toggle.action_item.set_enabled.assert_called_with(allowed)
  panel.non_obd_toggle.action_item.set_enabled.assert_called_with(allowed)


def test_ignition_blocks_even_always_offroad(settings):
  panel, state, _ = settings
  state.ignition = True
  panel.update_settings()
  for toggle in (panel.startup_toggle, panel.cold_boot_toggle, panel.non_obd_toggle):
    toggle.action_item.set_enabled.assert_called_with(False)


def test_cold_boot_depends_on_startup_not_hardware(settings):
  panel, _, values = settings
  values["SubaruStartupPreferences"] = False
  panel.update_settings()
  panel.cold_boot_toggle.action_item.set_enabled.assert_called_with(False)
  panel.non_obd_toggle.action_item.set_enabled.assert_called_with(True)
  panel.startup_toggle.action_item.set_enabled.assert_called_with(True)


def test_unknown_selection_clears_previous_availability(settings):
  panel, state, values = settings
  panel.update_settings()
  values["CarPlatformBundle"] = "malformed"
  state.CP = SimpleNamespace(carFingerprint="SUBARU_OUTBACK_2023", flags=0)
  panel.update_settings()
  panel.startup_toggle.action_item.set_enabled.assert_called_with(False)


@pytest.mark.parametrize("platform,allowed", [
  ("SUBARU_OUTBACK_2023", True), ("SUBARU_CROSSTREK_2026", True), ("unknown", False),
])
def test_dashboard_platform_matches_device(platform, allowed):
  caps = dict.fromkeys(CAPABILITY_FIELDS, False)
  caps["brand"] = "subaru"
  _resolve_brand_capabilities(caps, platform, None)
  assert caps["subaru_startup_preferences"] is allowed


def test_dashboard_settings_dependencies():
  schema = json.loads((ROOT / "openpilot/sunnypilot/sunnylink/settings_ui.json").read_text())
  items = {item["key"]: item for item in schema["vehicle_settings"]["subaru"]["items"]}
  for key in ("SubaruStartupPreferences", "SubaruStartupPreferencesColdBoot", "SubaruNonObdFirmwareQuery"):
    assert {"type": "offroad_only"} in items[key]["enablement"]
    assert {"type": "capability", "field": "subaru_startup_preferences", "equals": True} in items[key]["enablement"]
  dependency = {"type": "param", "key": "SubaruStartupPreferences", "equals": True}
  assert dependency in items["SubaruStartupPreferencesColdBoot"]["enablement"]
  assert dependency not in items["SubaruNonObdFirmwareQuery"]["enablement"]
