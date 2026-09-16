# EyeSight fault investigation — September 10, 2026

## Finding

The retained recordings confirm a latched vehicle-reported steering and
EyeSight/cruise fault on the southbound drive to Vancouver, Washington. The
fault cleared after an engine ignition cycle at approximately 11:28 a.m. PDT.
The original trigger cannot be established: the beginning of the incident
has rotated off the device and the route is unavailable in the signed-in
comma Connect history.

## Verified timeline (PDT)

- Approximately **11:19:07**: the earliest retained minute of route
  `00000358--952384d28d` (segment 111) already has `steerFaultPermanent=true`
  and `accFaulted=true`. The software displays
  **“LKAS Fault: Restart the car to engage”** and assistance is inactive.
- The same fault state persists through the remaining retained route minutes,
  segments 111–119. CAN remains valid in the recorded carState samples; no
  CAN timeout, panda heartbeat loss, buffer overflow, or invalid safety RX
  checks appears in this retained interval.
- **11:28:02.905**: ignition switches off near the end of segment 119.
- **11:28:11.024**: ignition is on in the next route,
  `00000359--2f48d617e1`. Panda uptime advances from 7232 to 7240 seconds;
  the comma/panda did not reboot during this recovery.
- By the next valid carState samples, both vehicle fault flags are clear.
  They stay clear through the remainder of the 38-minute route into Vancouver
  (ending around **12:05:56**). Brief startup/shutdown CAN-invalid samples at
  zero speed are separate from the latched fault.
- The device health flag `interruptRateCan2` exists both during the failed
  route and after recovery. Its presence alone does not identify this fault's
  cause. A transient event before the retained interval cannot be excluded.

The user's estimate of onset around 11 a.m. falls in the missing portion of
route 00000358. Fault onset is only bounded as occurring before 11:19:07;
the logs do not justify assigning an exact onset time.

## What the fault flags mean in this checkout

The deployed version recorded on Thursday was clean top-level commit
`ce9b63b5447a69973d912b0552eceb63afc6efe5`, branch `gen2angle-hybrid`,
version `2026.002.000`, Subaru safety parameter 9, stock longitudinal control.
The current AVH/start-stop changes were not installed on this drive.

In `opendbc_repo/opendbc/car/subaru/carstate.py`, `steerFaultPermanent` comes
from the vehicle's Steering_Torque.Steer_Error_1 bit. With stock longitudinal,
`accFaulted` comes from ES_Distance.Cruise_Fault. Thus these are vehicle fault
indications, not solely a warning invented by the comma interface. The word
“permanent” in the software field does not, by itself, prove damaged hardware.

The Subaru fork already contains protections against LKAS dashboard/engagement
state flicker and against sending a forged cruise-cancel frame while braking.
Those identify protocol interactions worth examining in an onset recording;
they are not evidence that either caused this event. No steering, CAN safety,
or preference code was changed during this investigation.

## Cloud and preservation

The device identity was not authorized to list route files (HTTP 403). After
explicit user approval, the user signed into comma Connect. A direct lookup
of the known route reported that the route did not exist, and filtering the
signed-in device history to September 10–11 returned no routes.

Comma documents 3-day retention for free Connect access and 1-year retention
with a subscription: https://comma.ai/connect . The missing route is
consistent with that retention limit, although the history view does not
establish whether a particular missing file expired or never uploaded.

Retained Thursday qlogs were saved locally in `outback-thursday-qlogs.tar.gz`,
with extracted fault transitions in `outback-thursday-fault-scan.jsonl`.
All retained outbound segments 111–119 of route 00000358 and all 38 segments
of route 00000359 were scanned. Later local routes 0000035a and 0000035b were
also scanned; the return-trip scan was stopped after its beginning because
it is outside the reported outbound incident.

## Next evidence needed

A stored Subaru diagnostic trouble code from EyeSight and/or the steering ECU
could narrow the trigger. No diagnostic commands were sent and no codes were
cleared. Otherwise, a fresh incident recording including the seconds before
onset is needed to distinguish a command/counter/state-sequence problem from
a transient vehicle or connection fault. Preserve that route promptly if it
recurs; the current retained tail alone cannot establish causation.

The user confirmed the observed 11:28 ignition cycle was their attempt to clear
the EyeSight fault. This corroborates the recovery timeline but does not add
evidence identifying the earlier trigger.
