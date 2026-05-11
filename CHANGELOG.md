# Changelog

## [Unreleased]

### Bug Fixes (continued)

- **Per-source "↻ Check" silently did nothing on failed requests**: when `/api/sources/releases` returned an error (e.g. 502 because a repo has no releases or because GitHub rate-limited the request), the frontend swallowed the exception and left the panel hidden — users got no visible feedback at all. The panel is now opened with the error message so the cause is visible.
- **Global "Check Updates" still missed single-payload repos with versioned filenames** when the old asset name was still present in the 3 most recent releases (e.g. ShadowMountPlus where `1.6test8-fix1` was still in the recent-3 window alongside `1.6beta10`). The asset-name match found the old release, compared the tag to current, decided "no update" — even though a newer release tag existed. Both global and per-source checks now follow the same rule for single-payload repos: trust the newest release as the successor regardless of filename match.

### UI Improvements

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
