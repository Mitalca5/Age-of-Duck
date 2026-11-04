# Fork functional audit — November 2026

Upstream inspected: `aaca491560a20e57b57fed897e1f22cf071c0f3a` (v2.0.1).
Working branch: `Mitalca5/Age-of-Duck:fix/fork-stability`.
Upstream still has ten pending pull requests and the three design discussions; no newer public bug reports or replies were present during this audit.

## Integrated corrections

The branch includes upstream v2.0.1 plus the changes proposed in upstream PRs #2, #4 and #8–15: resource-preserving Windows builds, synthetic provider fixtures, CI, game-data validation, counter targeting, reminder/session resets, background updates and autostart, editable catalog overrides, preference recovery and source launch scripts.

## Additional defects and remedies

| Area | Trigger / prior behavior | Remedy and evidence |
| --- | --- | --- |
| Game detection | `AoE2DE.exe` was recognized by native capture but ignored by the main process watcher. | Share both supported executable names; test the actual watcher with each name. |
| Guide speech | Missing/corrupt WAV or failed playback left the current instruction pending indefinitely, reserving the reminder channel. | Fall back to visual steps (3 seconds, 10 for decimal steps), release speech priority and preserve pause checks. |
| Speech generation | Missing PowerShell aborted loading; a hung synthesizer blocked instructions; complete clips waited for the whole order. | Keep the selected order, bound waiting for a missing current clip to 10 seconds, terminate failed generation, and play complete clips as they become available. |
| Speech retry | A corrupt cached file was considered complete forever. | Validate PCM duration and final frame; remove damaged files before regenerating on reselection. |
| Audio device errors | Playback exceptions could escape the timer; failed reminders could retry every tick. | Leave cues unacknowledged, recover visually and throttle failed reminder playback. |
| Provider resilience | Null/wrong-shaped batches, ladders, players, civilization or rating fields raised errors and disconnected the feed. | Validate containers and optional values; retain valid players and reject invalid profile ownership. |
| Profile lifecycle | Changing profile or stopping the game could leave the previous match visible until a network response. | Clear current match immediately, serialize profile changes against accepted responses, reject stale generations. |
| Positions/preferences | Saved malformed positions or non-boolean QAction values could crash startup or timer callbacks; infinite manual TC counts raised OverflowError. | Validate positions and recover invalid values. Negative monitor coordinates remain supported. |
| Editable data | Valid JSON arrays/scalars crashed object consumers. Partial legacy edits could erase fresh catalog fields or unit availability. | Check root type and apply only explicit edits; preserve absent fields and current availability. |
| Updater shutdown | A queued completed download could launch elevation after shutdown; suppressed completed downloads leaked their temporary file. | Ignore queued UI callbacks after close and discard unused downloads. Test GUI-thread delivery with a real Qt event loop. |
| Shutdown | Application quit did not explicitly stop the overlay's provider and process watcher. | Connect both to application shutdown; packaged startup/shutdown smoke test covers lifecycle. |
| Names | Player names containing markup were interpreted by QLabel. | Render player names as plain text. |
| Installer metadata | Static installer still advertised 2.0.0 while the app was 2.0.1. | Match application version and derive output filename/numeric version from the installer macro. |
| Windows integrity | Git's CRLF conversion changed checksum-verified JSON bytes. | Enforce LF for JSON in .gitattributes; verify both catalog hashes and recognition approval in Windows CI. |
| Fork updates | An independent build would still download upstream installers. | Point the update channel to this fork, isolate its update marker and explain when no fork release exists. |

Additional defensive fix: bound remapped queue width before resizing very wide, thin calibration selections.

## Verification

The Windows suite runs with the published image fixtures and synthetic profiles, without a game or live provider connection. It covers Qt layouts/controls, calibration, counters, provider normalization, reminder lifecycle, speech failure recovery, settings, updater threads and packaging. The current suite contains 182 tests, including 17 regressions from the performance/resource pass; the latest Actions run records the verified result.

CI also checks the actual source-data hashes, verifies calibration approval and measures queue analysis against the previous implementation. EXE generation is now opt-in: only a manual workflow dispatch with `build_package: true` builds with PyInstaller, checks bundled resources and starts the executable with isolated preferences. `--smoke-test` exits after all application controllers are constructed. The artifact contains the entire application folder and must be extracted together.

The first Windows run exposed a platform-dependent path comparison in our earlier packaging test; it was corrected to compare POSIX resource names. The integrated version then passed 146 tests and built successfully. The next expansion passed 153 tests and exposed CRLF hash changes; the branch adds the corrective Git attributes and approval check. Consult the latest Actions run for the final result.

## Remaining validation and scope

- A real Windows game session is still required: Steam/Microsoft Store, pauses, restarts, multiple monitors/DPI, custom HUD skins, live provider timing, real audio devices and UAC/install completion.
- The Windows runner is Windows Server 2025; it does not establish Windows 10/11 or in-game compatibility by itself.
- Historical vision tests referencing private/omitted screenshots cannot be run from this repository. Existing public-fixture tests remain enabled; unavailable historical tests are not claimed as passing.
- No installer has been published and the fork's Main branch is unchanged. This is a reviewable integration branch, not a claim of a bug-free release.
- Named HUD profiles and Spanish localization remain feature/design work (upstream issues #6 and #7). The speech-failure behavior discussed in #5 is implemented here.
- Keep the MIT license and original attribution. Website/Discord/donation destinations still refer to the original project; a fork release needs an explicit identity/distribution decision.

## Resource and performance pass — November 4

| Finding | Correction |
| --- | --- |
| Queue recognition copied the entire RGB screenshot and repeatedly converted the same queue to grayscale/binary. | Copy only the queue readout and its border probes; share prepared grayscale/binary images across template groups. Preserve exact results against the previous implementation on all published samples and queue fixtures. |
| Already-normalized ultrawide frames were copied again. | Return the original image when its height already matches the normalization height. |
| Unchanged guide steps rebuilt text/layout every 100 ms; hidden panels polled cursor/window styles. | Cache displayed progress, invalidate on scale changes, skip hidden input polling, and change window flags/position only when necessary. |
| Hidden companion controls checked focus periodically. | Refresh availability only when controls or volume settings are visible. |
| Peak queries from old matches remained queued and cached values grew indefinitely. | Cancel obsolete pending queries, cap outstanding work at 8 and cache at 256 entries, expire entries after 5 minutes. Keep mode-specific keys. |
| Profile clearing and peak collection could mutate shared tasks concurrently; shutdown could race submission. | Serialize clear, enrichment and pool shutdown with the existing state lock. A controlled two-thread regression covers clearing during peak processing. |
| GUI-triggered disconnect waited for a WebSocket close handshake. | Abort the transport immediately with shutdown; normal connection cleanup remains in the worker. |
| Focus could move to the companion during screenshot acquisition. | Recheck companion focus after capture before accepting the frame. |
| Quitting within the volume debounce interval lost the last adjustment. | Flush pending volume persistence on application shutdown. |
| Diagnostic files were written repeatedly to the program directory. | Store beside user preferences and write only changed content; retry failed writes. Preference write failures retain in-memory choices and log the error. |

Measured on the Windows CI runner in [run 41752414555](https://github.com/Mitalca5/Age-of-Duck/actions/runs/41752414555), using five calls per implementation and median milliseconds:

| Public 2560×1440 screenshot | Previous queue analysis | Optimized queue analysis |
| --- | ---: | ---: |
| selected-three.png | 170.222 ms | 164.440 ms |
| foundation-five.png | 160.820 ms | 148.934 ms |
| independent-four.png | 183.015 ms | 171.599 ms |

This is roughly 3–7% less time in **queue analysis**, not a measurement of total application CPU use or game FPS. Timing varies between runners. The RGB working copy for default queue-border checks shrinks by about 98%; the original screenshot and other application allocations still exist. The benchmark is diagnostic, with no fragile timing threshold in CI. The comparison implementation in `queue_reference.py` is test-only.

The first performance run passed 181 tests and skipped all four packaging steps. The final synchronization regression brings the suite to 182. No EXE was generated for this pass. The earlier packaged smoke test applies to commit `7e01ff6`, not to these later source changes.

