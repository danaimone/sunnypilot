# 2024 Outback: AVH and start-stop investigation

Status: manual control request/status transitions observed on this Outback;
automated transmission remains untested. No CAN commands transmitted or device software changed.

## Existing work and device

Reviewed Claude session `e2a2fd0b-1de1-4ba8-9352-7d911b8c301e`, titled
“Steering control software for Subaru Outback (fork 2)”, in the laptop's
`.claude/projects/-Users-danaimone-git/` directory.
The history covers migration from JacobWaller to the sunnypilot fork,
angle steering, engagement/flicker fixes, MADS button safety reception, and
later investigation of longitudinal control with an EyeSight interceptor.
The last independent review of that interceptor/UDS work did not complete.
The previously staged `/data/uds_ccheck.py` was not run in this investigation.
A Python finally block is not a guarantee of ECU restoration after process kill,
power loss, or communication failure; the historical assurance was too strong.

SSH to `comma@192.168.30.105` succeeded. Device revision: `ce9b63b54`;
opendbc: `626b9688162ef16a908b1e9c8a7420df35a6d10f`.
The device reported `IsOnroad=0` during inspection.
A recorded carParams message identifies `SUBARU_OUTBACK_2023` and
`openpilotLongitudinalControl=False`.

## Candidate signals (not yet validated on this Outback)

Byte indices below are zero based. These are research observations, not a
validated transmission recipe.

| Function | Reference implementation | Candidate |
| --- | --- | --- |
| AVH enable/disable request | Levorg VN5 AVHController | ID `0x6BB`, byte 2 masks `0x02` enable / `0x01` disable |
| AVH status | Same | ID `0x32B`, byte 5 mask `0x20` enabled; combined mask `0x22` holding |
| Start-stop button request | Levorg VN5 EngineAutoStopEliminator | ID `0x390`, byte 6 mask `0x40`; treat as a toggle request, not an unconditional OFF command |
| Start-stop feedback | Same | ID `0x174`; reference checks byte 2 mask `0x08` for readiness, byte 4 `0xC0` for disabled |

Sources inspected:

- https://github.com/kz1000a1/AVHController at `5e5b2c83de784fe22fa51f03eb5b0e18e7580b88`, `inc/subaru_levorg_vnx.h` and `src/main.c`.
- https://github.com/kz1000a1/EngineAutoStopEliminator at `a4f3dc8ebc0d00a8ee9f76223bd1f265c54f63e1`, same paths.
- https://github.com/kz1000a1/ISController (related implementation).
- https://www.autostopeliminator.com/products/2023-subaru-outback-autostop-eliminator confirms the EyeSight connector is a vehicle-network access point for its preference-restoring product.

The local DBC already names the `0x390` bit `Dashlights.STOP_START`
(`54|1@0+`) and has `Engine_Stop_Start.STOP_START_STATE` in `0x174`.
A signal name alone does not establish its command semantics on this model.

## Evidence from this car

Read `/data/media/0/realdata/00000379--e8bac48096--0/rlog.zst` using
the device's `/usr/local/venv/bin/python` and LogReader. All four candidate
IDs are present on physical receive buses 0 and 1; also visible on bus 2
during part of startup. Message visibility does not prove that transmitting
on that bus will actuate the setting.

For bus 0, the full sampled segment had:

| ID | Frames | Standard Subaru additive checksum matches |
| --- | ---: | ---: |
| `0x6BB` | 79 | 79 |
| `0x32B` | 618 | 618 |
| `0x390` | 666 | 666 |
| `0x174` | 3049 | 3049 |

Checksum checked: byte 0 equals `(address_low + address_high + sum(bytes 1..7)) & 0xFF`.
The reference start-stop implementation uses `% 365`; do not transplant that
formula. The car's observed packets validate against the standard checksum above.

The sampled segment contains no asserted candidate AVH request bits, no
asserted candidate start-stop request bit, and no candidate AVH-enabled status.
It therefore confirms visibility and framing, not the proposed bit meanings.

## Live manual capture

The user subsequently toggled the controls while a passive subscriber recorded
the existing `can` stream. On bus 0 (matching events also present on bus 1):

| Capture seconds | Observed event |
| ---: | --- |
| 55.576 | `0x390` byte 6 mask `0x40` asserted |
| 55.603 | `0x174` byte 4 changed from `0xC0` to `0x00` |
| 55.875 | Request bit cleared |
| 61.713 | Same start-stop request bit asserted again |
| 61.744 | `0x174` byte 4 returned to `0xC0` |
| 62.021 | Request bit cleared |
| 67.474 | `0x6BB` byte 2 low bits became `0x01` |
| 67.575 | `0x32B` byte 5 enabled bit cleared |
| 67.652 | AVH request bits cleared |
| 73.544 | `0x6BB` byte 2 low bits became `0x02` |
| 73.633 | `0x32B` byte 5 enabled bit set |
| 73.727 | AVH request bits cleared |

This matches the reference's button semantics: start-stop is a toggle request;
AVH has separate on/off requests. All four IDs' checksums passed in the analyzed
live snapshot. AVH holding was not tested. The `0x174` disabled interpretation
is supported by reference code and the user's requested final settings, but
the entire status field still needs broader state validation.
At about 79.4 seconds, bus 0 traffic ceased and a bus 1 AVH status cleared;
this may be shutdown and should not be treated as another manual button press
without user confirmation.

Raw capture snapshot and decoded events are saved outside the repository in
the task artifacts directory. No replay/transmit script was created.

## Remaining verification

Capture manual setting changes while stationary outdoors, engine running,
in Park with the parking brake set. Keep the current driving software running
normally and collect raw `can` messages through its existing logging; do not
take ownership of the panda or change its safety mode.

Record initial displayed settings. Leave a baseline, then toggle AVH on/off/on
with about ten seconds between changes. Separately toggle start-stop off/on/off
with similar spacing. Record action times. Compare request edges and delayed
status transitions across buses 0/1/2, including other changing bits in each frame.
Repeat across an ignition cycle before interpreting startup readiness.

Both candidate command IDs are absent from the current Subaru safety TX
allowlist. A production implementation would need narrowly scoped, tested
permission for validated messages, freshness/counter/checksum handling,
preservation of unrelated fields, correct bus routing, startup-only behavior,
bounded attempts, acknowledged state, and respect for subsequent manual changes.
Do not use unrestricted panda transmission or replay entire stale frames.

No startup automation is installed. Manual transitions are now captured; the
remaining work is ignition-cycle readiness, routing/transmission validation,
and narrowly scoped safety/controller implementation and testing.

## Local implementation and validation

The local source baseline was aligned with the deployed `ce9b63b544` and all
seven submodule revisions before this work. The following are now local,
uncommitted changes; they have not been copied into the running installation.

- `tools/car_porting/subaru_startup_preferences.py`: offline prototype and
  capture replay, with no messaging publisher or CAN transmission path.
  It requires an observed ignition-off/on transition, ten seconds of startup
  delay and three seconds of stable readiness, fresh checksummed messages with
  advancing counters, Park, zero wheel speed, no accelerator input, running
  engine and start-stop readiness. Window closes after thirty seconds.
  Each setting receives at most one proposed request. A manual request retires
  its setting, and desired-state feedback acknowledges completion. Unknown
  start-stop states do not cause a toggle. Movement abandons the entire cycle.
- `opendbc/safety/modes/subaru_startup.h` in `opendbc_repo`: experimental
  restrictions for safety parameter bit 16, only in debug builds with Subaru
  Gen2 angle steering and stock longitudinal. The default allowlist is unchanged.
  Only bus 1, eight-byte requests with fresh factory templates are admitted;
  unrelated payload bits cannot change. Requests are limited to one per setting
  per safety initialization, with a 10–30 second window, engine/gear/speed/input
  checks, counter checks and manual-override latches. Existing relay forwarding
  behavior is preserved.
- The offline prototype is **not yet integrated into the runtime**. Its ignition
  lifetime must be preserved across card restarts, and its timing must be aligned
  with panda safety initialization before activation. A process restart must
  never re-toggle start-stop in an ongoing ignition cycle.

Validation performed on the laptop:

- 17 Python prototype tests passed, including 3,200 randomized payload-preservation
  cases and captured request-vector checks.
- 605 Subaru safety tests ran successfully, 78 skipped (527 passed). Includes
  the new gate, stock steering tests with the gate enabled, and preglobal tests.
- Independently compiled without `ALLOW_DEBUG` and confirmed both new requests
  are rejected even when parameter bit 16 is supplied.
- Python lint and whitespace checks passed. The Mac test harness required
  `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk` because the
  currently selected linker could not read the default macOS 27 SDK metadata.

A second four-minute passive capture included ignition telemetry, but recorded
only ignition off, so replay produced zero proposed requests. Startup timing
remains unvalidated. A later SSH reconnect failed with agent signing failure
and too many authentication failures. No vehicle command was sent, no manager
was stopped, and no panda firmware was flashed.

Next session: restore SSH access if needed, record a confirmed restart, replay
the prototype on that capture, implement the ignition-lifetime runtime adapter,
and only then prepare a supervised parked request test through the restricted
safety mode. Do not use unrestricted CAN output as a shortcut.

## Confirmed restart and runtime integration

SSH access was restored. The second startup capture recorded ignition off,
ignition on at 22.410 seconds, Park at 22.68 seconds, engine RPM becoming nonzero
at 23.55 seconds, and start-stop readiness at 23.90 seconds. AVH remained off and
start-stop remained enabled, as expected without automation.

Offline replay proposed the start-stop request at 32.523 seconds and AVH at
35.543 seconds. These were simulations only; no requests were transmitted.

The policy now lives at
`sunnypilot/selfdrive/car/subaru_startup_preferences.py`. The tool path remains
as a replay-only command. Runtime integration is complete locally:

- Manager records a startup token only after a known ignition-off period of at
  least two seconds followed by ignition-on. Unknown panda state cannot create
  an ignition edge.
- Card claims the token synchronously before enabling safety parameter 16.
  Restarting card cannot reuse it. Restarting manager while ignition is already
  on cannot fabricate a new edge. The default persistent option
  `SubaruStartupPreferences` is false.
- Activation is restricted to `SUBARU_OUTBACK_2023`, non-passive operation,
  stock longitudinal, and a single original safety configuration with parameter 9.
- Requests go through card's existing publisher. Valid CAN state and one valid
  panda with ignition on and the exact enabled Subaru safety configuration are
  required. The adapter waits ten seconds after observing that configuration,
  aligning with the hardware's independent startup delay.
- The initial implementation deliberately skips a cold boot that never observes
  ignition off. Cold-boot support has not been validated. It also skips late
  requests if software initialization exhausts the startup window.

41 policy/runtime tests pass. Replaying the recorded startup through both the
runtime adapter and compiled safety library produced accepted requests for
simulated 3-second and 8-second safety-initialization delays. At a simulated
15-second delay only start-stop fit inside the window; AVH was correctly skipped.
These are timing simulations, not proof of delivery or ECU acceptance.

The 12 changed source/test files and SHA-256 manifest are staged separately at
`/data/outback-startup-review`. All staged hashes match the laptop. The 14 new
safety tests were also compiled and passed on the comma CPU using an isolated
library, without connecting to panda. The installed `/data/openpilot` was
verified clean at `ce9b63b544` during staging. No firmware has been flashed.

Remaining: install/build the reviewed changes while offroad, retain a rollback,
enable the option for one supervised parked restart, verify the actual requests
and acknowledged settings, and then confirm subsequent manual overrides remain
respected. Vehicle routing and actual ECU acceptance remain untested.

## First installed parked test and correction

Installed the staged files after verifying ignition off. The original source and
panda firmware are preserved at `/data/outback-startup-rollback-20260916-025108`,
with a restoration script at `/data/outback-startup-rollback.py`. Device build
passed. Normal pandad startup flashed and verified the new firmware; installed
source hashes matched all 12 local manifest entries. The first tmux restart used
the system Python and failed before manager start; restarting with
`/usr/local/venv/bin` first in PATH resolved it.

The first test used route `0000037d--ac72a423bb`. Manager recorded/claimed a real
ignition edge; card selected Subaru safety parameter 25. It proposed start-stop
at monotonic 369222.211 and AVH at 369224.940. Panda blocked both; feedback
confirmed start-stop remained enabled and AVH off. No successful setting change
was established. The supplemental recorder initially failed on a bytes field
in CarParams; normal rlog retained both proposals and status, and the recorder
was fixed to serialize bytes.

The cause was the generic safety tick's minimum expected frequency rule. The
new AVH RX declaration correctly specified the observed 1 Hz but omitted
`ignore_frequency_check`, so the periodic tick always marked safety RX invalid.
This is now declared explicitly for that one slow message. Its independent
1.5-second freshness limit and 30-millisecond transmission-template age remain
in force. Regression tests now exercise the periodic safety tick and verify
stale AVH input still blocks requests. Runtime also suppresses proposals when
panda reports `safetyRxChecksInvalid`.

42 policy/runtime tests and 607 safety tests (78 skipped) pass. Replaying the
actual recorded CAN and proposed sends in timestamp order through corrected
compiled safety accepts both; original safety parameter 9 rejects both as
expected. The option was disabled after the unsuccessful test. Correction v2
is staged separately and is being installed offroad for a second supervised
test. Actual ECU acceptance is still unproven.

The v2 normal restart unexpectedly installed a pre-existing finalized updater
overlay. This replaced the experimental checkout with clean original HEAD
`ce9b63b544`, removed the runtime module, and restored safety parameter 9 on
the following engine start. Post-launch source hashing detected the swap. The
launch log explicitly reported `Valid overlay update found, installing`.
No v2 vehicle test occurred. Ignition-off was subsequently verified, with
panda in noOutput and no invalid RX checks. Existing staged files and the
rollback outside `/data/openpilot` remain intact.

An attempt to pause updates (`DisableUpdates`), preserve/remove the launcher
marker `.overlay_init`, and reinstall v2 was rejected by automatic approval
review because changing automatic-update behavior requires explicit user
approval. No part of that attempted command ran. Approval has been requested;
until then, the device remains on the original source, while the laptop holds
the experimental changes. Thus local and deployed source are currently not
identical; that mismatch is known and must not be reported as resolved.

The user then explicitly approved pausing automatic updates, preserving the
pending-update marker, and reinstalling. Ignition-off was freshly verified.
The reinstall saved the previous DisableUpdates value in
`/data/outback-original-disable-updates.json`, enabled DisableUpdates, and moved
`.overlay_init` to `/data/outback-overlay-init-saved`. It verified v2 source
hashes after installation. A rebuild is underway before the next parked test.

## Confirmed start-stop success; bounded AVH press sequence

After the authorized updater pause, v2 rebuilt and restarted successfully;
all 12 source hashes still matched the laptop after launch. Firmware SHA-256:
`7ea73fde0ca46a976335c56c7175cdc0957227c7b2640b85296fea9a6e2cd646`.
Panda flashed and verified it through the normal launcher.

The next parked start recorded ignition on at monotonic 370224.677. Subaru
safety parameter 25 became active at 370235.971, with valid RX checks. The
start-stop request at 370248.984 was acknowledged at 370249.022 by status
0x174 byte 4 changing to 0xC0. This is the first confirmed automatic success.
The AVH request at 370249.294 was not blocked, but no AVH acknowledgement
followed. The user confirmed AVH remained off. Both safety TX rejection count
and invalid-RX status stayed zero during the active test.

A manual AVH activation under the same conditions succeeded at 370358.812,
followed by ignition-off at 370365.271. Earlier manual recordings showed AVH
frames 50 ms apart, and the reference AVHController sends two consecutive
frames separated by 50 ms. V3 therefore changes only the AVH press sequence:
at most two frames, no subsequent retries, with the second counter incrementing
by two relative to the original factory template. Runtime schedules the second
50–75 ms after the first; panda independently permits 45–80 ms, requires the
same unchanged factory template (maximum age 110 ms), and continues all parked,
engine, status, payload, freshness, and overall startup-window checks. An
acknowledgement, manual request, new template, or missed timing cancels the
follow-up. Start-stop remains exactly one toggle request per ignition cycle.

47 policy/runtime tests pass. The complete safety suite passed 611 tests
(78 skipped), followed by a passing additional second-frame payload mutation
test (21 targeted tests total). V3 is staged for installation with the same
rollback retained. AVH automatic success remains unproven until the next test.

## Confirmed automatic AVH and start-stop success

V3 built and flashed successfully; post-restart SHA-256 verification matched
all 12 installed source/test files to the laptop. Firmware SHA-256:
`a217c76c05b13c45959c0dc8c9ea05e46325f36ad3ab86a2a25b7f7bb2bfd0f6`.

On the next parked startup, panda entered Subaru safety parameter 25 at
monotonic 370799.433, with valid RX checks and a TX-block count of 1 from the
mode transition. At 370812.484, one start-stop request was proposed; status
0x174 changed to 0xC0 at 370812.512. AVH frames were proposed at 370812.745 and
370812.804 (59 ms apart); status 0x32B changed to enabled at 370812.842.
Neither settings request increased the safety TX-block count. The user also
confirmed the automation worked on the car's display.

The feature is enabled persistently. Automatic updates remain paused with the
user's explicit approval. Original source/firmware rollback and updater-state
backups remain available. V3 source archive, manifest, and success timeline
are saved with the task artifacts, outside temporary storage.

The implementation still deliberately requires an observed ignition-off state
before ignition-on. A full comma cold boot directly into an already-running
engine does not arm this feature. This limitation is not the same as verified
warm-start operation and must be disclosed rather than claimed solved.
Manual override persistence is being checked in the final parked capture.

Final manual override validation passed: AVH was manually disabled at monotonic
370846.402 and start-stop manually re-enabled at 370847.752. Both stayed as set,
with no further automatic requests, until ignition-off at 370899.332. The user
confirmed the same on the display. Final source hashes again matched all 12
manifest entries. The passive recorder was stopped; normal manager/pandad
remain running, and the working preference option remains enabled.

## Cold-boot support prepared (v4; activation disabled)

The user approved implementing persistent startup permission and chose to test
later. V4 adds a PERSISTENT string `SubaruStartupPreferencesArmedBoot` and a
separate PERSISTENT boolean `SubaruStartupPreferencesColdBoot`, default false.

Manager reads the Linux kernel boot UUID. After at least two seconds of valid
ignition-off observations, with the main preference option enabled, it saves
that boot UUID once. On the first known ignition-on state of a different
kernel boot, it may consume this permission and issue the normal volatile
startup token. This requires cold-boot opt-in and observation within the first
120 seconds of monotonic boot time. Missing/corrupt/same-boot permission,
unknown boot identity, or a late start fails closed. A same-boot manager
restart cannot use the saved cold-boot permission. Unknown ignition after a
known state invalidates the off-state permission.

The persistent permission is removed and checked absent before the cycle is
published. A crash between consumption and publication skips automation rather
than permitting another request. A card restart still cannot reuse the claimed
volatile token. Existing Park/zero-motion/fresh-input checks, manual override
cancellation, 30-second request window, one start-stop toggle, and bounded
two-frame AVH press are unchanged. The tested panda safety firmware is unchanged.

66 policy/runtime tests pass, including cross-boot consumption, same-boot
restarts, repeated reboot, missing/invalid tokens, unknown ignition, disabled
feature, late startup, publication failure, failed permission removal, movement
before activation, and normal warm-start regression cases. No real cold-boot
vehicle test has occurred. The new option must stay false until that test.

Planned supervised test: confirm stable engine-off and saved off-state
permission; enable only the cold-boot option; fully shut down the comma; start
the vehicle outdoors and remain in Park while it boots. Verify a changed kernel
boot identity, consumed permission, requests and acknowledgements, source
hashes, valid safety state, and manual override persistence. If the test cannot
complete, disable the cold-boot option and retain the proven warm-start behavior.

V4 installation is complete. The device build passed, and an isolated test using
its actual Params implementation confirmed that the off permission survives
CLEAR_ON_MANAGER_START, is consumed on a different boot identity, and cannot
be reused by a same-boot manager restart. Normal manager startup then saved a
real off-state permission for the current boot.

Final running verification: all 12 deployed source hashes match the laptop;
SubaruStartupPreferences=true; SubaruStartupPreferencesColdBoot=false;
DisableUpdates=true; saved armed boot matches the current kernel boot; panda
telemetry is valid, ignition is off, and safety mode is noOutput. Panda firmware
SHA-256 is unchanged from working V3 (`a217c76c05b13c45959c0dc8c9ea05e46325f36ad3ab86a2a25b7f7bb2bfd0f6`).
The user explicitly deferred the physical cold-boot test. No cold-start success
has been claimed and its activation remains disabled pending that test.

## Supervised cold-start test — user-observed success

Before power removal, all 12 v4 source hashes matched both laptop and device,
ignition-off telemetry was valid, and ArmedBoot matched kernel boot UUID
`a7e4d2fd-a0b1-47b0-9d41-9a2f0029edaa`. ColdBoot was enabled with a blocking
parameter write and verified true; storage was synced before unplugging.

The user performed the instructed power-off/start-engine/reconnect test and
reported both AVH-on and start-stop-off worked. The user then switched the
engine off before repeating the manual override check. Prior warm-start manual
override validation remains passed; cold-start-specific override validation
was not repeated.

Post-test log/boot/safety verification is pending: SSH reaches the device and
the server accepts the account key, but the 1Password agent failed to complete
signing. User was asked to unlock/approve. Do not represent this user-observed
success as a completed log-verified cold-start test yet. ColdBoot remains enabled
as last successfully configured; no post-test setting change has been made.


## Cold-start log verification completed

After the user unlocked 1Password, SSH verification succeeded. The new kernel
boot UUID is `63e4b3a3-b93c-43e9-95cd-2494ff33f95f`, different from the recorded
pre-shutdown UUID. Consumed startup token is `32.863955716` seconds after boot.
After the user switched the engine off, the cycle was cleared and a fresh
armed permission was saved for the new boot. ColdBoot remains enabled.
All 12 deployed v4 source hashes still match the manifest/laptop.

Route `00000381--33b85e7320`, segment 0:
- Safety parameter 25 active at 43.777 seconds after boot.
- Exactly one start-stop request at 56.800; disabled status at 56.828.
- Exactly two AVH request frames at 57.090 and 57.140; enabled status at 57.197.
- No further setting requests before ignition-off at 67.078.
- During the active parameter-25 interval, safetyTxBlocked remained 0,
  safetyRxChecksInvalid remained false, and heartbeatLost remained false.
- No permanent steering fault or ACC fault was reported. CAN became valid at
  42.504 and stayed valid until ignition-off.

There were six blocked transmissions during initialization before parameter 25;
these did not coincide with either settings request. The later offroad snapshot
reported nine blocked transmissions, outside the active recorded test interval.
Do not describe the entire boot/shutdown as having zero blocked transmissions.

Cold-start behavior is now confirmed both by the user and the recorded requests
and vehicle acknowledgements. Manual overrides passed the earlier warm-start
test; a separate cold-start override trial was not performed because the user
had already switched the engine off. No new steering-stack validation is implied.
Decoded evidence is preserved as outback-coldboot-v4-summary.json in task artifacts.
