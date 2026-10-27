# Stability validation implementation plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans. Preserve the approved operating flow and use independent file ownership.

**Goal:** Validate large history, connection recovery, interrupted storage, and eight-hour Windows EXE operation; fix only reproduced defects.

**Architecture:** Retain Python/PySide6, the current coordinator and SQLite store. Use synthetic data and local SSH servers in isolated data directories. Existing history selection, preview, report formats and saved records remain compatible; bound reads and move slow exports off the GUI if measurement demonstrates blocking.

**Tech Stack:** Python 3.12, PySide6 6.8.3, Paramiko 5.0.0, SQLite, pytest, PyInstaller, Windows PowerShell.

**Spec:** The user approved the four-point stability proposal with “진행해” on 2026-10-27. This document records implementation choices within that approval; normal operator input order remains unchanged. Progress/results remain in the app and local reports, with no automatic history deletion or credential export.

## Global constraints

- Work directly in the canonical existing checkout on `fix/stability-validation`, preserving settings/history/known_hosts and previous releases.
- No live network devices, new dependencies, Figma, or Windows security/display/power setting changes.
- No CLI/parser semantic changes without official Aruba documentation review.
- Product fixes require a reproduced failing regression first. Test evidence must distinguish simulation from field proof.
- Eight-hour elapsed-time evidence cannot be substituted with accelerated rounds; interruptions are reported as incomplete.

## Review focus

- Large history while monitoring continues: bounded preview work and responsive export, with complete results.
- Disconnect/reconnect plus stop/restart: no late saved result, orphan session, or false disconnect event.
- Process death during database commits: acknowledged records survive, no partial poll/event transaction, no silent reset.
- Disk full and corrupted database: actionable errors, existing files preserved, recovery possible.
- Long-lived frozen process: native resources and GUI heartbeat remain stable, normal close records every session end.

## Tasks

- [x] Establish clean baseline at `7df804c`; record tests before product edits.
- [x] Large history: measure 10,000 sessions and 100,000–1,000,000 polls. Own `storage.py`, history-related `ui.py` code, dedicated tests/benchmark script. Preserve selection/report output. Add failing bounded-read and responsiveness regressions before fixes. Compare before/after measurements.
- [x] Storage faults: own `tests/test_storage_faults.py` and subprocess helpers. Exercise actual SQLite FULL, process termination, DB corruption and reopen/integrity checks; coordinate any required product fix with the storage owner.
- [x] Connection recovery: own dedicated integration tests and local SSH fixture. Repeat TCP disconnect, silent response and server restart through coordinator/pool/Paramiko. Confirm isolation, cooldown recovery and stop/close. Report any product fix before touching SSH/pool/UI lifecycle files.
- [x] Soak validation: add a bounded, synthetic-only diagnostic run compatible with the frozen EXE, if necessary, with tests for invalid arguments, time completion and early failure. Add an external resource sampler with isolated reports. Short rehearsal must pass before the eight-hour run.
- [x] Run full tests, Ruff, independent review and Windows EXE build; visually verify meaningful history/UI changes.
- [ ] Run eight-hour frozen-EXE soak at the normal collection cadence with 10 synthetic targets. Record wall time, samples, heartbeat, private bytes/handles/threads, DB integrity and clean shutdown. If continuation is needed, retain exact process/run identity and arrange a follow-up on this thread.
- [ ] Deliver verified artifacts and evidence; do not claim long-soak/field success before observed completion.

## Progress

- 2026-10-27: clean checkout `7df804c`; approved proposal; baseline started. Prior v0.3.7 evidence and release remain intact.
- Baseline 575 passed in 76.43s. Large-history RED/GREEN and 100k/1m before-after comparison complete; unchanged report hashes. Storage faults 9 passed, connection recovery 7 passed with 60 recovery/20 restart rounds.
- Independent review P1/P2 in soak monitor resolved with three failing regressions. Final full suite 673 passed in 233.83s; Ruff and whitespace checks passed. Version 0.3.8 prepared; native EXE/rehearsal/eight-hour evidence still pending.
- Windows build rerun 673 passed in 235.04s; extracted ZIP passed ten frozen runs and 275 observations. Native 100k preview/CSV export/scroll during export/HTML cancellation/clean exit passed. Exact implementation-head CI 40488529393 passed (Linux 667 + 6 platform skips; Windows 673 twice; six source/frozen smoke reports).
- Native 60s rehearsal passed in 61.563s, 60 persisted observations, 62 resource samples, no unclosed sessions. Actual 8h run started 2026-10-27 19:42:43 KST, due no earlier than 2026-10-28 03:42:43 KST; run_id `20cba3f9675747ecb590d26ee270e875`. Thirty-minute thread follow-up configured. Eight-hour result and final delivery remain pending.
- First follow-up found that run interrupted after 592.734s: app and sampler absent, exec session lost, final result absent. All 590 persisted observations were OK, integrity/FKs passed, but all ten sessions lacked an end time. Exact termination cause remains unknown; no eight-hour qualification. Original evidence preserved. Detached launch was blocked by automatic approval review, so a foreground launcher for the user's own PowerShell terminal is prepared in local `artifacts/start-v038-soak.ps1`. Previous ETA is invalid; draft PR/release remain pending and the idle follow-up is being removed.
- User explicitly requested direct continuation with Computer Use. Terminal UI automation is prohibited by that skill, so a transparent command-tool request for a bounded separate process was submitted and accepted. Retry started 2026-10-27 20:28:38 KST in a new folder, run_id `a1f5dcac8a904c1d9f75e223cc4dfb69`, due no earlier than 2026-10-28 04:28:38 KST. Independent read-only check at 20:30:32 KST confirmed process chain, run/build/hash identities, and 120 OK observations. Fifteen-minute follow-up recreated; first check must verify continued collection beyond 600s. Eight-hour result remains pending.
- Retry 2 failed after 188.390s with sampler PermissionError and owned-child cleanup; previous ETA invalid. Native Windows read/replace sharing conflicts and duplicate-version stat/content race reproduced, then fixed with bounded permission retries, a nonblocking fixed app publication deadline, content-version progress validation and sanitized error stages. Targeted sampler 71 and app soak 19 passed; full build and replacement EXE validation pending. Original 300s traced rehearsal passed without the intermittent exception, so the original failure site is not claimed as identified.
- Full rebuild stopped before EXE generation: 694 passed, 1 recovery-fixture setup error. Preserved SQLite showed KNOWN_HOSTS_INVALID, not command timeout. A native Windows sharing-lock regression reproduced unlocked preflight reads racing the key writer; preflight now uses the existing cancellable/deadline-bound trust lock and checks cancellation again before network access. Six failed-setup/teardown cleanup regressions were RED then GREEN. Original failed evidence remains preserved; integrated rebuild and new EXE qualification pending for build `0.3.8-506867ece370`.
- Integrated Windows 11 rebuild passed 708 tests in 251.40s, Ruff, dependency checks and both frozen smokes. Fresh extracted candidate passed ten Python-free child-PATH runs with 275 observations, 245 source hashes and six third-party source hashes. Actual frozen native progress-file reader lock for 1.594s recovered without heartbeat stall (max 1.141s). Final eight-hour qualification, CI for the new implementation and documentation refresh inside the final release archive remain pending.
- New native 90s rehearsal passed in 91.594s, 92 resource samples, 90 observations and no open sessions. Third eight-hour run started 2026-10-27 21:04:16 KST, run_id `49c3795e3c7a401bb070234d4d05d5ba`, due no earlier than 2026-10-28 05:04:18 KST. Implementation `5f25a053f40edd1427e10b56996b018b29bb4e6f`, build `0.3.8-506867ece370`; fifteen-minute thread follow-up active. No long-run pass claimed.
