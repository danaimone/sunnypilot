# Outback September platform integration

Prepared September 15–16, 2026 on `codex/outback-september-integration`.
This candidate is not installed on the comma and is not yet validated for driving.
The installed `gen2angle-hybrid` build remains the rollback/reference build.

## Scope and decision

Application base: d412 `db9c50c85856442404ec1f517566e2a549032be9` (September 11),
which incorporates the August 17 sunnypilot core sync and requires AGNOS 19.6.
Paired opendbc base: `92bad25c0a18494fb99551d515f224cbdc1a0488`.
This deliberately follows the paired Subaru upstream rather than mixing in the
newer official master or independently updating every submodule.

The September angle-controller rewrite is deferred. Its bundled Subaru safety
tests could not even import: `TestSubaruLongitudinalSafetyBase` was removed but
concrete tests still inherited from it. Its controller replaces the deployed
jerk-limited planner, removes the existing dash-stranding guard, and its safety
hook uses the host MADS heartbeat as the button state. This audit does not prove
that rewrite unsafe or prove it fixes the September 10 EyeSight fault. It needs
separate engagement/driver-override analysis and replay before adoption.

This candidate preserves the deployed Subaru controller and lateral extension,
physical HUD-edge MADS safety handling with its RX allowlist and regression test,
Outback steering ratio/calibration, two-second alert timer, ABS fingerprint,
VIN-less firmware cache, lateral-acceleration clamp, and bounded AVH/start-stop
startup feature. The newer platform's Subaru longitudinal-disable remains in
place; obsolete positive longitudinal-transmit tests are replaced by a test
that unsupported longitudinal flags cannot enable brake/RPM/UDS transmissions.
No factory-AEB-preserving longitudinal capability is claimed.

The startup runtime is ported into the new `openpilot/` source directory layout.
Its policy and safety request payload implementation are unchanged from the
successfully cold-start-tested v4. The new ctypes Params implementation gets an
actual-storage integration test covering saved off-state permission, boot
transition, one-use consumption, manager restart, real upstream CarParams, and
card restart. Production/release safety builds still do not enable this debug
startup feature. A device build must retain the intended development build mode.

## Validation completed

- Subaru, preglobal, Hyundai, Tesla and Rivian safety suites: 2,837 tests run,
  323 skipped, no failures (2,514 executed successfully).
- Release-safety tests: 2 passed.
- Startup policy/runtime: 66 passed.
- New real-storage/CarParams integration: 2 passed.
- Acceleration-clamp controller tests: 2 passed.
- 1,500 synthetic controller steps matched the deployed branch exactly in
  vehicle parameters, requested angle, dash guard state and steering CAN bytes.
  Scenarios include standstill, low/high speed, target changes, lateral-state
  flicker, driver torque override and cruise disengagement. This is a regression
  comparison, not a substitute for recorded-drive or vehicle validation.
- Comparison using 1,792 recorded controller input samples from three Thursday
  qlog segments also matched the deployed controller exactly: faulted segment
  358/111, recovery segment 359/0, and onward driving segment 359/15. Qlogs are
  sampled; this is not a full-rate process/safety replay or a diagnosis of onset.
- Recorded cold start `00000381--33b85e7320`: all three actual startup request
  frames accepted in offline safety replay with parameter 25, all three rejected
  with the feature-disabled parameter 9. Replay feeds the recorded CAN traffic
  and safety tick through the newly compiled safety library.
- Full minimal desktop build passed, including driving/monitoring model compilation,
  messaging/native libraries and signed debug panda firmware. Messaging and card
  imports passed. This is a macOS build plus cross-compiled firmware, not an
  AGNOS device build.
- Startup Python lint and Git whitespace checks passed.

## Build environment

Isolated checkout: `/private/tmp/outback-september-integration`.
Isolated Python 3.12 environment: `/private/tmp/outback-september-env`.
An SDK 26.5 compiler wrapper is used because the laptop's default SDK 27 linker
stubs are incompatible with the available compiler. This is local build setup,
not a change to application source. Cython/setuptools, vendored comma native
packages, ARM cross-compiler, and ordinary Python build dependencies were installed
only in this temporary environment. Upstream LFS model data was downloaded from
the repository's configured LFS service and materialized for the build.

## Before deployment

1. Review the saved paired commits and build/test report before installation.
2. Preserve the installed v4 source/firmware and updater-state rollback archives.
3. Review and authorize the AGNOS 18.4 to 19.6 device migration with sufficient
   power, Wi-Fi and time for the OS update and hardware-specific rebuild. A
   desktop build does not validate the comma's camera/GPU paths or its OS update.
4. Verify source hashes, firmware, retained preference parameters and startup
   behavior on the device while parked, then perform supervised driving checks.
5. Keep automatic updates paused until this custom branch has a verified release.

The missing onset of the September 10 fault remains unresolved; this platform
migration is not represented as a diagnosed repair for that incident.

Vehicle-library candidate commit: `e3e2cb02` (paired by the application gitlink).
The application commit containing this report is the candidate application version.

The macOS SDK also needed to be supplied to SCons default construction environments
for panda tests, which create an independent environment. The runner used for this
is retained with the build evidence; no upstream source changes were needed for
this laptop-specific workaround.
