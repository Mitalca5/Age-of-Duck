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

The Windows suite runs with the published image fixtures and synthetic profiles, without a game or live provider connection. It covers Qt layouts/controls, calibration, counters, provider normalization, reminder lifecycle, speech failure recovery, settings, updater threads and packaging. The expanded suite contains 153 tests, including 33 new fork regressions.

CI also checks the actual source-data hashes, verifies calibration approval, builds with PyInstaller, checks bundled runtime resources and starts the resulting executable with isolated preferences. `--smoke-test` exits after all application controllers are constructed. The artifact contains the entire application folder and must be extracted together.

The first Windows run exposed a platform-dependent path comparison in our earlier packaging test; it was corrected to compare POSIX resource names. The integrated version then passed 146 tests and built successfully. The next expansion passed 153 tests and exposed CRLF hash changes; the branch adds the corrective Git attributes and approval check. Consult the latest Actions run for the final result.

## Remaining validation and scope

- A real Windows game session is still required: Steam/Microsoft Store, pauses, restarts, multiple monitors/DPI, custom HUD skins, live provider timing, real audio devices and UAC/install completion.
- The Windows runner is Windows Server 2025; it does not establish Windows 10/11 or in-game compatibility by itself.
- Historical vision tests referencing private/omitted screenshots cannot be run from this repository. Existing public-fixture tests remain enabled; unavailable historical tests are not claimed as passing.
- No installer has been published and the fork's Main branch is unchanged. This is a reviewable integration branch, not a claim of a bug-free release.
- Named HUD profiles and Spanish localization remain feature/design work (upstream issues #6 and #7). The speech-failure behavior discussed in #5 is implemented here.
- Keep the MIT license and original attribution. Website/Discord/donation destinations still refer to the original project; a fork release needs an explicit identity/distribution decision.
