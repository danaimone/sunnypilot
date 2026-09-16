"""Keep the brake-light display off when vehicle data is unavailable."""


def show_brake_lights(sm, enabled):
  if not enabled or not sm.all_checks(['carState', 'carStateSP']):
    return False
  state = sm['carStateSP']
  return bool(sm['carState'].canValid and state.brakeLightsAvailable and state.brakeLightsOn)
