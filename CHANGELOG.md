# Changelog

## [Unreleased]

### Internal

- **Crash-safe writes for every persistent config file**: every `Path.write_text(...)` / `write_bytes(...)` call on user-critical files (`sources.json`, `devices.json`, `state.json`, `payload_meta.json`, `flow_runs.json`, `port_timing.json`, `pre_restore_backup.json`, the imported/exported backup JSONs, every profile `.txt` and every imported payload `.elf` / `.lua`) now goes through a small `atomic_write` helper that writes to a sibling `.tmp` file first and then `os.replace`-es it onto the target. Previously, an OOM-kill or SD-card power loss mid-write left a truncated/half-written file and the user lost their entire add-on configuration. With the atomic pattern, a reader will always see either the previous valid file or the new valid file, never a partial one. New: `app/atomic_write.py` + `tests/test_atomic_write.py`.

### Bug Fixes (continued)

- **Multi-update apply silently left the panel in a stale state**: same stale-DOM pattern — the apply button's click handler ran `renderSourcesList()` after switching versions, which detached the panel/updList/applyBtn the handler was still operating on. The remaining `refreshApplyBtn()` and `applyBtn.style.display = 'none'` calls became no-ops, so the panel disappeared abruptly. The panel is now re-rendered with the remaining updates so the post-update status stays visible.
- **Per-source "↻ Check" panel never appeared in 1.1.1-dev**: clicking ↻ Check showed only a toast — the result panel that 1.1.1 opens below the source stayed hidden. Cause: the new highlight-affected-sources feature added a `renderSourcesList()` call inside `checkSourceUpdates`, which rebuilds every `.source-item` from scratch. The `panel` reference captured before that call was then a detached DOM node, so populating it and setting `display=''` had no visible effect. The panel is now re-queried after `renderSourcesList()` runs (in both the success and error paths) before being shown.
- **Per-source "↻ Check" silently did nothing on failed requests**: when `/api/sources/releases` returned an error (e.g. 502 because a repo has no releases or because GitHub rate-limited the request), the frontend swallowed the exception and left the panel hidden — users got no visible feedback at all. The panel is now opened with the error message so the cause is visible.
- **Global "Check Updates" silently dropped broken repos**: `/api/sources/check-updates` wrapped every per-repo GitHub call in `except Exception: pass`. If one repo rate-limited or 404'd, it disappeared from the result without any signal to the user, who saw "N checked" with no way to tell which were really checked. The endpoint now collects per-repo errors and returns them under `errors[]`; the frontend logs each failed repo and shows a toast summarising how many failed.

### Internal

- **`download_payload` host whitelist**: every URL the add-on hands to `urllib.urlopen` originates from a GitHub API response (release `browser_download_url`, raw.githubusercontent.com paths). Tightening the download path to a fixed set of GitHub hosts (`github.com`, `api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`, `codeload.github.com`) is essentially free and blocks SSRF if payload metadata is ever tampered with.
- **`scan_repo_files` tree cache size cap**: the in-memory cache now evicts the oldest entry when it exceeds 100 repos, so long-running add-on instances cannot accumulate unbounded memory for users who add many repositories.
- **Parallel WebSocket broadcast**: `ConnectionManager.broadcast` now fans out via `asyncio.gather` instead of awaiting each client sequentially. A single slow dashboard tab no longer holds up status updates for the others.
- **Cleaner GitHub error handling in `/api/sources`**: three near-identical try/except blocks around `gh_get_releases` / `gh_scan_repo_files` consolidated into a single `_run_gh` helper. Behaviour is unchanged except that `/api/sources/tree` now returns HTTP 502 instead of pass-through GitHub status codes for non-404 HTTP errors (e.g. 403 rate-limit), which is consistent with the other `/api/sources/*` endpoints.
- **`payload_sender`: waited-close on errored connections**: the `OSError`/`BrokenPipeError` path called `writer.close()` without `await writer.wait_closed()`, leaving the close handshake potentially incomplete. Added the wait (mirroring the success path).
- **Replaced deprecated stdlib calls**: `datetime.utcnow()` (deprecated in 3.12, removal in 3.14) replaced with `datetime.now(timezone.utc)` in the timing-analyze ISO timestamps and the log-export filename stamp. `asyncio.get_event_loop()` calls in `/api/flow/analyze` replaced with the running loop captured once at the top of the handler (the rest of the module already used `get_running_loop`). No observable behaviour change — only future-proofing for newer Python.
- **Global "Check Updates" still missed single-payload repos with versioned filenames** when the old asset name was still present in the 3 most recent releases (e.g. ShadowMountPlus where `1.6test8-fix1` was still in the recent-3 window alongside `1.6beta10`). The asset-name match found the old release, compared the tag to current, decided "no update" — even though a newer release tag existed. Both global and per-source checks now follow the same rule for single-payload repos: trust the newest release as the successor regardless of filename match.

### UI Improvements

- **Static assets are now cache-busted on every add-on update**: HA OS / mobile browsers aggressively cached `PayloadSources.js` and the other JS/CSS files, so frontend changes were invisible until the user manually hard-reloaded — easy to overlook on iPhone Safari. The `/` endpoint now appends `?v=APP_VERSION` to every `static/js/*.js` and `static/css/*.css` URL and serves the HTML with `Cache-Control: no-cache`. Browsers re-fetch JS/CSS automatically after every version bump.
- **Multi-select for pending updates** (both per-source panel and global "⬆ Update All"):
  - Per-source panel: each update gets a checkbox, "Update Selected (N)" button at the bottom. "Select All" / "Deselect All" appears when more than one update is pending.
  - Global Update All: opens a modal grouped by repo with checkboxes, all selected by default. Pick which payloads actually receive the new version.
  - The existing single-payload-per-row import/version picker is unchanged — multi-select for new payload imports (Add Source / Check) and per-payload version dropdown still work exactly the same way.
- **Sources with available updates are now visually highlighted**: orange left-border on the source card and a `⚠ N updates` badge next to the source name. The per-source "↻ Check" panel now stays open after a check and lists each pending update with an inline "Update" button — previously the only signal was a transient toast.

### Bug Fixes

- **Update check missed repos with versioned asset names** (e.g. drakmor/ShadowMountPlus where the release asset is `ShadowMountPlus_1.6test8-fix1.zip`): both `/api/sources/check-updates` and the per-source "↻ Check" button matched releases by asset filename. When the filename embedded the version, every release had a different asset name, so the saved name never matched the newest release and no update was reported. Fallback added: when a repo has a single tracked payload and the newest release contains a single asset, that asset is treated as the successor regardless of filename. New asset names in the result use the updated filename so the follow-up switch-version call works.
- **"Check Updates" inconsistent with per-source "Check"**: the global update check ignored a newer GitHub release if its tag already existed in the local `versions[]` history (e.g. after rolling back to an older version), while the per-source Check button still reported the update. Both checks now use the same rule — an update is reported whenever the active version is not the latest GitHub release.

## [1.1.1] – 2026-04-19

### New Features

**Per-step version control in the builder**
- Each builder step now independently tracks which payload version it targets
- Version dropdown per step — select any locally available version without affecting other steps
- Versions persist across saves: the flow file stores `# ~version <filename> <tag>` annotations that survive reload, export, and Edit cycles
- Before running, the add-on automatically switches each payload to its pinned version (`_ensureBuilderVersions`)

**Selective flow update dialog**
- "Update flows" button (⚠ badge → GitHub update available) shows every saved flow and the active builder flow as checkboxes
- Each row displays the current pinned version → new version transition
- Flows already on the target version are shown as "already up-to-date" and pre-deselected
- Select all / Deselect all quick actions
- "Update selected" is disabled when nothing is checked — no accidental blanket updates

**Full flow scan in "Update flows" button**
- The "Update flows" button (in the builder-usage row) now scans ALL saved flows that use the payload, not just builder steps
- Saved flows and builder steps shown together with per-flow version transitions
- Confirming patches the `# ~version` annotation in each selected saved flow file and updates builder step metadata simultaneously

**GitHub token support**
- New `github_token` option in add-on configuration
- Raises GitHub API rate limit from 60 req/hr (unauthenticated) to 5,000 req/hr
- Clear error message when rate-limited without a token: *"GitHub API rate limit exceeded — add a GitHub token in add-on options to raise the limit."*

**Multi-version storage & smarter imports**
- Up to 5 versions stored per payload (raised from 3)
- Re-importing a payload merges versions rather than overwriting — previously downloaded versions are never lost
- Versions sorted by tier: stable → beta → alpha/test
- Update detection now checks whether the latest GitHub tag is already in the local versions list — eliminates false-positive "update available" badges

**ZIP autoload export improvements**
- Export includes all referenced ELF/LUA binaries alongside the autoload text — ready to drop on a USB stick
- Source display names shown in builder steps (advanced mode)

**UI readability improvements**
- Step font sizes bumped for readability (`.82rem`)
- Payload step rows split into name row + info row for cleaner layout
- Edit button text changed from `✏` icon to `Edit` label
- Version label removed from payload card (redundant with dropdown)
- Builder badge placement fixed for HA ingress scaling

### Bug Fixes

- **Version not persisting**: builder step version was reset after save/load because `builderGenerate()` did not write version annotations to the flow file — fixed
- **False-positive update badge**: update detection compared `latest.tag` against a single `current` field; now checks whether the tag exists in the local `versions[]` array
- **`autoload.txt` reappearing**: the default `autoload.txt` flow was bundled in the Docker image and re-installed on every restart — file deleted from image, cleanup added to `setup_storage()`
- **Duplicate run race condition**: rapid double-click could start two concurrent autoload runs (HTTP 409) — fixed with optimistic guard in `runProfile()`
- **GitHub 403 surfaced as HTTP 502**: rate-limit errors from GitHub now return a descriptive message instead of an opaque 502

### UX / Wording

- **"Profiles" renamed to "Flows"** throughout the UI — heading, placeholders, import modal, empty states
- **"Update usages" renamed to "Update flows"** for consistent language
- **Update dialog shows flow names** instead of internal step numbers ("Step 3") — grouped by flow with usage count and version transition
- Builder checkbox in the "Update flows" (GitHub version) dialog defaults to **unchecked** (safe by default)

---

## [1.1.0] – 2026-03-xx

Initial public release with autoload builder, payload management, GitHub source tracking, and Home Assistant ingress support.
