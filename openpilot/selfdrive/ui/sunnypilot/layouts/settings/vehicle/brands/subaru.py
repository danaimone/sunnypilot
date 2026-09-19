"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp
from opendbc.car.subaru.values import CAR, SubaruFlags
from opendbc.sunnypilot.car.subaru.startup_preferences import startup_preferences_supported


class SubaruSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.has_stop_and_go = False

    self.stop_and_go_toggle = toggle_item_sp(tr("Stop and Go (Beta)"), "", param="SubaruStopAndGo", callback=self._on_toggle_changed)

    self.stop_and_go_manual_parking_brake_toggle = toggle_item_sp(tr("Stop and Go for Manual Parking Brake (Beta)"), "",
                                                                  param="SubaruStopAndGoManualParkingBrake", callback=self._on_toggle_changed)

    self.avh_startup_toggle = toggle_item_sp(tr("Enable AVH at startup"), "",
                                             param="SubaruEnableAVHAtStartup", callback=self._on_toggle_changed)
    self.start_stop_startup_toggle = toggle_item_sp(tr("Disable auto start-stop at startup"), "",
                                                    param="SubaruDisableStartStopAtStartup", callback=self._on_toggle_changed)
    self.items = [self.avh_startup_toggle, self.start_stop_startup_toggle,
                  self.stop_and_go_toggle, self.stop_and_go_manual_parking_brake_toggle]

  def _on_toggle_changed(self, _):
    self.update_settings()

  def stop_and_go_disabled_msg(self):
    if not self.has_stop_and_go:
      return tr("This feature is currently not available on this platform.")
    elif not ui_state.is_offroad():
      return tr("Enable \"Always Offroad\" in Device panel, or turn vehicle off to toggle.")
    return ""

  def update_settings(self):
    bundle = ui_state.params.get("CarPlatformBundle")
    self.has_stop_and_go = False
    platform = bundle.get("platform", "") if isinstance(bundle, dict) else ""
    if bundle:
      if isinstance(platform, str) and platform in CAR.__members__:
        self.has_stop_and_go = not (CAR[platform].config.flags & (SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID))
    elif ui_state.CP is not None:
      platform = str(ui_state.CP.carFingerprint)
      self.has_stop_and_go = not (ui_state.CP.flags & (SubaruFlags.GLOBAL_GEN2 | SubaruFlags.HYBRID))

    supported = ui_state.CP is not None and startup_preferences_supported(ui_state.CP)
    offroad = ui_state.is_offroad() and not ui_state.ignition
    settings = (
      (self.avh_startup_toggle,
       tr("Enable Auto Vehicle Hold (AVH) once at each vehicle startup. Your later button changes are respected.")),
      (self.start_stop_startup_toggle,
       tr("Disable automatic engine start-stop once at each vehicle startup. Your later button changes are respected.")),
    )
    for toggle, description in settings:
      reason = ""
      if not supported:
        reason = tr("Requires a recognized Subaru with supported angle steering. Not available in dashcam-only mode.")
      elif not offroad:
        reason = tr("Turn the vehicle off to change this setting.")
      description += " " + tr("Applies from the next startup, including after comma power-off. " +
                              "Leave the comma connected briefly after switching the vehicle off.")
      toggle.action_item.set_enabled(supported and offroad)
      toggle.set_description(f"<b>{reason}</b><br><br>{description}" if reason else description)

    disabled_msg = self.stop_and_go_disabled_msg()
    descriptions = [
      tr("Experimental feature to enable auto-resume during stop-and-go for certain supported Subaru platforms."),
      tr("Experimental feature to enable stop and go for Subaru Global models with manual handbrake. " +
         "Models with electric parking brake should keep this disabled. Thanks to martinl for this implementation!")
    ]

    for toggle, desc in zip([self.stop_and_go_toggle, self.stop_and_go_manual_parking_brake_toggle], descriptions, strict=True):
      toggle.action_item.set_enabled(self.has_stop_and_go and ui_state.is_offroad())
      toggle.set_description(f"<b>{disabled_msg}</b><br><br>{desc}" if disabled_msg else desc)
