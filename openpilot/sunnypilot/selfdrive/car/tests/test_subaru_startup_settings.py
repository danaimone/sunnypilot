"""Startup settings availability and dependency behavior, without a display server."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from opendbc.car.subaru.values import SubaruFlags
from openpilot.sunnypilot.sunnylink.capabilities import CAPABILITY_FIELDS, _resolve_brand_capabilities

ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture
def settings():
  state = SimpleNamespace(params=Mock(), CP=None, ignition=False, is_offroad=lambda: True)
  values = {"CarPlatformBundle": {"platform": "SUBARU_OUTBACK_2023"}, "SubaruEnableAVHAtStartup": True}
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


def supported_cp(**overrides):
  fields = {"brand": "subaru", "carFingerprint": "SUBARU_OUTBACK_2023",
            "flags": SubaruFlags.GLOBAL_GEN2 | SubaruFlags.LKAS_ANGLE,
            "dashcamOnly": False, "passive": False, "openpilotLongitudinalControl": False,
            "safetyConfigs": [SimpleNamespace(safetyModel="subaru", safetyParam=1)]}
  fields.update(overrides)
  return SimpleNamespace(**fields)


@pytest.mark.parametrize("override,allowed", [
  ({}, True), ({"carFingerprint": "SUBARU_CROSSTREK_2026"}, True),
  ({"carFingerprint": "unknown"}, False), ({"dashcamOnly": True}, False),
  ({"passive": True}, False), ({"openpilotLongitudinalControl": True}, False),
  ({"flags": SubaruFlags.GLOBAL_GEN2}, False),
])
def test_device_and_dashboard_require_actual_support(settings, override, allowed):
  panel, state, _ = settings
  state.CP = supported_cp(**override)
  panel.update_settings()
  panel.avh_startup_toggle.action_item.set_enabled.assert_called_with(allowed)
  panel.start_stop_startup_toggle.action_item.set_enabled.assert_called_with(allowed)
  caps = dict.fromkeys(CAPABILITY_FIELDS, False)
  caps["brand"] = "subaru"
  _resolve_brand_capabilities(caps, "SUBARU_OUTBACK_2023", state.CP)
  assert caps["subaru_startup_preferences"] is allowed


def test_manual_selection_cannot_enable_unsupported_car(settings):
  panel, _, _ = settings
  panel.update_settings()
  panel.avh_startup_toggle.action_item.set_enabled.assert_called_with(False)
  caps = dict.fromkeys(CAPABILITY_FIELDS, False)
  caps["brand"] = "subaru"
  _resolve_brand_capabilities(caps, "SUBARU_OUTBACK_2023", None)
  assert not caps["subaru_startup_preferences"]


def test_ignition_blocks_even_always_offroad(settings):
  panel, state, _ = settings
  state.CP = supported_cp()
  state.ignition = True
  panel.update_settings()
  panel.avh_startup_toggle.action_item.set_enabled.assert_called_with(False)
  panel.start_stop_startup_toggle.action_item.set_enabled.assert_called_with(False)


def test_dashboard_settings_independent():
  schema = json.loads((ROOT / "openpilot/sunnypilot/sunnylink/settings_ui.json").read_text())
  items = {item["key"]: item for item in schema["vehicle_settings"]["subaru"]["items"]}
  for key in ("SubaruEnableAVHAtStartup", "SubaruDisableStartStopAtStartup"):
    assert {"type": "offroad_only"} in items[key]["enablement"]
    assert {"type": "capability", "field": "subaru_startup_preferences", "equals": True} in items[key]["enablement"]
    assert not any(rule["type"] == "param" for rule in items[key]["enablement"])
  assert "SubaruNonObdFirmwareQuery" not in items
  assert "SubaruStartupPreferencesColdBoot" not in items
