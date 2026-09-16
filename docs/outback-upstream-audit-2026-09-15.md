# Outback upstream audit — September 15, 2026

Read-only source audit: no merge, checkout, device change, or update activation performed. Remote refs were refreshed selectively. A broad fetch was stopped after targeted checks completed; official release tips were verified directly with GitHub rather than assuming all cached refs were current.

## Current baseline

Application `ce9b63b5447a69973d912b0552eceb63afc6efe5`, opendbc `626b9688162ef16a908b1e9c8a7420df35a6d10f`, branch `gen2angle-hybrid`. July 28 MADS fix is present and published to the user's fork. Today's startup-preference implementation is uncommitted on top of this baseline, with separate source archives/manifests. The previous deployment verification matched 12 source files; this audit did not repeat SSH verification.

Automatic updates remain paused by prior user authorization. Cold-boot support remains disabled pending the deferred parked test. Warm-start AVH/start-stop behavior and manual overrides were verified earlier.

## Live upstreams

| Source | Current tip | Finding |
|---|---|---|
| d412 application, subaru-gen2angle | db9c50c858, September 11 | Rebased/force-updated; 418 commits unique to upstream and 10 unique to our application history. These are divergence counts, not 418 required fixes. |
| d412 opendbc, subaru-gen2angle | c8ec9932, September 13 | Rebased/force-updated; 169 upstream-only and 24 local-only commits. Subaru rewrite d5ed2814 dated September 11. |
| d412 application's pinned opendbc | 92bad25c, September 11 | Available from remote. Same Subaru files as c8ec9932; differences are Toyota, docs and a MADS lint suppression. |
| official sunnypilot master | a5f44653d7f43ad57fef2f546f3916ec4cbf3c56, September 14 | Newer than d412's August 17 core sync. Not fully reviewed here. |
| official sunnypilot release-mici | 6a17f75c6bcb67c85f252a1acc342d94d5b8a4d2, August 7 UTC | v2026.002.002 exists. Not a drop-in replacement for this custom Subaru port. |
| MostlyClueless94 subi-1.0 | 405511e3ca, April 13 | Unchanged from cached history; old alternative base, not the active upstream. |
| commaai opendbc master | a477f06c0f096b06d2525f87beb09f24224f2971 | Newer shared vehicle library; do not independently replace the paired custom Subaru dependency. |

## Relevant changes and migration blockers

The d412 September Subaru implementation derives MADS button state from `heartbeat_engaged_mads`, with a comment that the stock LKAS HUD desynchronizes after an ACC cycle. Our July implementation observes HUD boundary crossings and explicitly whitelists that CAN message. This is a different engagement design worth focused review and replay, not a confirmed repair for the September 10 incident.

Upstream replaces the jerk-limited steering state machine with speed-dependent low-pass filtering, changes engage/disengage logic, and lacks our existing dash-stranding guard. Behavior and fault prevention require validation before adoption.

Directly replacing our vehicle library would drop the custom lateral-acceleration clamp and its tests, the VIN-less fingerprint-cache fix, the specific ABS fingerprint `a1 20 24 17 00`, and the two-second steering-limit alert timer. Our new startup-preference safety/runtime changes would also need explicit porting.

The application migration includes a major directory move under `openpilot/`, parameter API/build changes, dependency changes, model support changes, and AGNOS 18.4 to 19.6. Relevant upstream commits include logger startup-delay fix 85d364d4de, false startup-unavailable UI fix ec86732af8, parameter cleanup-hang fix 4e9e9190a5, and AGNOS update 10502adf95. These are migration candidates, not individually tested cherry-picks.

## Claude handoff review

Reviewed session e2a2fd0b-1de1-4ba8-9352-7d911b8c301e, ending August 12. July 28 steering-button fixes were completed and deployed. Earlier low-speed-freeze approaches were superseded by later builds and should not be reintroduced as unfinished work.

The remaining longitudinal-control deliverables were a staged `/data/uds_ccheck.py` ECU communication-control experiment and a hardware interceptor plan. The requested independent review failed twice and never delivered a result. The statement that a Python finally block guarantees EyeSight restoration after every failure is incorrect: process termination or power loss can prevent it from running. Preserving AEB with an interceptor remains an unvalidated engineering goal, not an established capability of this car. Do not treat either item as a ready software update.

Claude's August 12 scan reported no permanent faults in the routes then available. That historical observation does not resolve the September 10 fault. See the separate fault report; the onset recording is missing.

## Recommended order

1. Commit/version the current application and opendbc changes together, preserve a rollback release, and verify publication before allowing normal updates again.
2. Finish the deferred parked cold-boot test before enabling that option.
3. Build an isolated migration branch from the paired d412 September application/dependency; explicitly preserve the Outback fingerprint, cache behavior, acceleration bound, necessary fault guards, and startup preferences. Re-evaluate alert tuning for the changed steering filter rather than carrying it blindly.
4. Replay engagement/button/brake transitions and run controller plus safety tests before device installation and supervised validation. No claim that the newer build fixes Thursday's fault is justified yet.
5. Keep the older longitudinal experiment parked until its design and failure handling receive a real review.

Sources: local fetched Git objects for d412, live git ls-remote and GitHub commit API for official tips, and local Claude session history. No test suites were run because no executable code changed in this audit.
