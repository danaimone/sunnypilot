from types import SimpleNamespace
import pytest
from opendbc.car import structs
from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.ui.sunnypilot.onroad.brake_status import show_brake_lights


@pytest.mark.parametrize('enabled,healthy,can_valid,available,on,result', [
  (True, True, True, True, True, True),
  (False, True, True, True, True, False),
  (True, False, True, True, True, False),
  (True, True, False, True, True, False),
  (True, True, True, False, True, False),
  (True, True, True, True, False, False),
])
def test_brake_display_requires_live_supported_data(enabled, healthy, can_valid, available, on, result):
  state = structs.CarStateSP()
  state.brakeLightsAvailable, state.brakeLightsOn = available, on
  message = convert_to_capnp(state)
  class Messages(dict):
    def all_checks(self, services):
      assert services == ['carState', 'carStateSP']
      return healthy
  sm = Messages(carState=SimpleNamespace(canValid=can_valid), carStateSP=message)
  assert show_brake_lights(sm, enabled) is result
