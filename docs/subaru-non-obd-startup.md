# Subaru startup preferences without an OBD connection

`SubaruNonObdFirmwareQuery` is a persistent, default-off hardware configuration
option for Subaru harness installations without the OBD connection. It is
independent of the AVH and start-stop startup opt-ins.

When enabled, uncached vehicle identification keeps OBD multiplexing off and
queries the existing Subaru camera and powertrain connections. The scan requires
an exact firmware match; it does not select a vehicle automatically on failure or
fall back to the OBD path. Normal cached identification remains available.
Other installations retain the normal diagnostic scan by default.

On the affected Outback, the first post-update log showed CAN-controller receive
errors during OBD multiplexing, followed by a latched `interruptRateCan2` fault.
Errors stopped after switching back. That fault prevented both automatic startup
requests. The new option avoids that diagnostic path; it does not suppress faults,
raise interrupt limits, or change vehicle-control permissions.

After installing, enable the option while off-road, then restart the panda while
ignition is off to clear the previously latched fault. An app process restart alone
does not necessarily clear it. Verify the next uncached engine startup identifies
the correct vehicle, remains fault-free, and acknowledges both settings. Until that
capture is checked, the real-vehicle correction is unverified.

Local checks cover recorded Outback and Crosstrek firmware, missing/unknown ECU
responses, cache handling, the unchanged default scan, and startup-request policy.
