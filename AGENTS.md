# AGENTS.md — working on ssp-i18n with a general-purpose coding agent

This repository holds the language packs (UI translations) of
[SSP](http://ssp.shillest.net/). Translation is normally automated by
[fount-CI](https://github.com/steve02081504/fount-CI) (see
`.github/workflows/sync-translations.yml` and `add-language.yml`). This file
describes the **same jobs** so that Claude Code, Codex or any other agent
(or a human) can do them *semi-manually*: the agent does the work, the
maintainer or translator reviews it. Work is done by one person at a time,
directly on `master`/`main` (no branches or pull requests needed).

### Two modes

| | CI mode (default) | Manual mode (`[i18n-manual]`) |
| --- | --- | --- |
| How | push without the marker | the commit message of the pushed head contains `[i18n-manual]` |
| Translation sync (`sync-translations.yml`) | fount-CI | **skipped** — the agent does Job A |
| `resource.dll` | CI (`md5-CI-build.yml` builds it) | the agent (§3.1) |
| `updates.txt` (MD5 list for network update) | CI (`md5-CI-build.yml`, "md5 fix~") | **skipped** — the agent (Job C) |
| Release on tag push (`auto_release.yml`) | CI | **skipped** — the agent (Job C) |

In manual mode nothing fixes things up after you push, so every push must
leave the repository consistent: translations, `resource.dll` and
`updates.txt` all match. Network update reads straight from the `master`
branch (see `homeurl`), so a stale `updates.txt` on `master` breaks updates for
users immediately. **Rule: whenever you push to `master`/`main`, regenerate
`updates.txt` first** (`python tools/release.py updates`, after `resource.dll` is
built) so that it matches the pushed files.

> **The existing translations are not a reference implementation.** The current
> packs (especially the Chinese ones, which were converted from decompiled
> resources) still contain bugs: missing resources/keys, controls that lose
> `NOT WS_VISIBLE`, wrongly encoded `descript.txt`, clipped labels, …
> The source of truth is always `languages/english/` plus the rules in this file.
> Do not copy a pattern from another locale just because it is there; treat
> `i18n_check.py` ERRORs in existing files as bugs to fix, not as a baseline.

Everything below works on Linux/macOS/Windows. Only building `resource.dll`
needs Windows (Visual C++ `rc.exe` / `link.exe`); see §3.1 for agents without it.

---

## 1. Repository facts

| Path | Role |
| --- | --- |
| `languages/english/` | **Source of truth.** Never change it while translating. |
| `languages/<locale>/` | One complete SSP language pack per folder. |
| `shared/resource_r.h` | Resource ID header shared by every `resource.rc`. Generated upstream; do not edit. |
| `scripts/build-resource.ps1` | Builds `resource.dll` (Windows only). |
| `tools/` | Cross-platform helper tools (Python 3 stdlib only). |

Files in a locale folder:

| File | Translate? | Notes |
| --- | --- | --- |
| `message.txt` | yes | `key,value` lines. Keys must match english exactly. |
| `resource.rc` | UI strings only | Menus and dialogs. Structure must mirror english. |
| `surfacetable.txt` | yes | `id,label` lines; same ids as english. |
| `install.txt` | `name` only | `directory` must equal the folder name; `type,language`. |
| `descript.txt` | no (fields only) | **ASCII only** unless a `charset,…` line is present, and then *every* byte must be valid in that charset. Text in any other encoding (e.g. a GBK font name with no charset line) is a bug. `id` = Windows LANGID (decimal). `homeurl` must be exactly `https://raw.githubusercontent.com/ukatech/ssp-i18n/master/languages/<folder>/` (network update downloads the raw files from GitHub). |
| `holidays.txt`, `md5buildignore.txt` | no | Copy from english. |
| `resource.dll` | never by hand | Built from `resource.rc` (§3.1). |
| `updates.txt` | never by hand | MD5 list for network update. CI writes it, or `python tools/release.py updates` in manual mode. Only `updates.txt` is used (no `updates2.dau`). |
| `ssp-pictures/` | optional | Localized loading images (see `chinese-simplified/`). |

All text files are UTF-8 **without BOM**. Keep the line-ending style that the
file already uses (the Chinese `resource.rc` files use CRLF; english uses LF).

## 2. Tools

```sh
python tools/i18n_check.py                     # structural + translation lint, all locales
python tools/i18n_check.py chinese-simplified  # one locale
python tools/i18n_check.py --min-level warn    # hide info notes
python tools/i18n_check.py --changes           # english changes since the last translation sync
python tools/i18n_check.py --changes <rev>     # ... since an explicit commit

python tools/rcview.py --list                  # dialog/menu ids
python tools/rcview.py IDD_SETUP               # dialog, english + all locales side by side -> .rcview/IDD_SETUP.html
python tools/rcview.py IDC_SPEEDUP             # dialog containing that control, control highlighted
python tools/rcview.py IDR_SAKURA_MENU         # menu
python tools/rcview.py info.install            # message.txt keys with that prefix
python tools/rcview.py IDD_SETUP -l french --png /tmp/setup.png   # screenshot (needs Playwright)
python tools/rcview.py --audit -l french       # every dialog: clipped / overlapping text (needs Playwright)

python tools/release.py updates [LOCALE ...]   # regenerate updates.txt (same output as the md5 CI)
python tools/release.py verify  [LOCALE ...]   # updates.txt vs. files; exit 1 on mismatch
python tools/release.py nar --out dist         # <locale>.nar like auto_release.yml
python tools/release.py notes <tag>            # release notes body
```

* `i18n_check.py` exits with status 1 when it reports an **ERROR**. Errors must
  be fixed. **WARN** should be fixed or explained. **INFO** is for review.
* `rcview.py` writes a self-contained HTML page (open it in any browser; it has
  a selector for every dialog, menu and message group). It emulates Windows
  dialog units with local fonts **and SSP's automatic widening of static
  labels** (left-aligned labels grow to the right, right-aligned to the left,
  centred to both sides), then flags text that is still clipped, labels that
  run into another control, cross their group box or leave the dialog.
  It is an approximation: small (1–3 px) results are noise; check the final
  result in SSP on Windows when in doubt.
* `--png` / `--audit` need Playwright (`pip install playwright && playwright install chromium`,
  or a global `npm i -g playwright`). Agents that can read images should look at
  the PNG of every dialog they changed.
* `IDC_HELPFILE` controls are hidden keys SSP uses to open the help page; they are
  never shown, are not checked for layout, and their text must stay identical to english.

## 3. Job A — sync translations after an english update

Equivalent of `sync-translations.yml`.

1. **Find what changed.**
   `python tools/i18n_check.py --changes` lists, since the last commit that touched
   a translated locale: added/changed/removed `message.txt` keys (old and new
   text), added/removed resources, dialog controls whose text, geometry or style
   changed, and menu diffs. Use `git diff <rev> -- languages/english shared/resource_r.h`
   for the raw diff. If the default base looks wrong, pass a revision.
2. **Get the current gaps.** `python tools/i18n_check.py --min-level warn` shows what is
   already missing in each locale (`kv-missing`, `res-missing`, `ctl-missing`,
   `menu-missing`, …). Fix those as well; they are the same work.
3. **Apply the changes to every non-english locale** (`languages/*/` except english):
   * `message.txt`: add new keys at the same position as in english; retranslate
     changed values; delete removed keys.
   * `resource.rc`: mirror the structural change from english (new
     `MENUITEM`/`POPUP`/control/dialog, moved or resized controls, changed styles).
     Copy the english block, then translate only the quoted UI strings. Keep the
     symbolic IDs (`IDC_…`, `SAKURA_MENU_…`) exactly as in english; never use
     raw numbers. A new dialog/menu goes at the same place as in english.
   * `surfacetable.txt`, `install.txt`: align when english changed.
4. **Verify.**
   * `python tools/i18n_check.py` → no ERROR; look at new WARN/INFO lines for
     the parts you touched (`untranslated`, `placeholder`, `accel-*`, `list-fields`).
   * For each dialog/menu you touched: `python tools/rcview.py <ID> --png …`
     (or open the HTML) and look at it. `python tools/rcview.py --audit` must not
     list new problems in the dialogs you touched.
5. **Commit** only the translated locales (not english).
   Message: `chore(i18n): sync translations from english update [i18n-manual]`.
6. **Build `resource.dll` and update `updates.txt`** — Job C steps 1–3.
7. Hand over to a human: summarize which keys/controls were added or
   retranslated per locale and paste remaining WARN lines with a reason.

### 3.1 Building `resource.dll`

* **On Windows** with Visual C++ Build Tools: `pwsh ./scripts/build-resource.ps1`
  (or `-Locale <folder>`), then commit the changed `languages/*/resource.dll`.
* **Without Windows** (Linux/macOS/cloud agents): push your commits (with
  `[i18n-manual]`, and `updates.txt` regenerated for the text files), then run the
  **rebuild resource.dll** workflow (Actions → *rebuild resource.dll* → *Run workflow*,
  or `gh workflow run rebuild-dll.yml`). It commits the DLLs; because the head you
  pushed carries `[i18n-manual]`, the md5 job that normally follows is skipped.
  `git pull`, then run Job C steps 2–3 again so `updates.txt` covers the new DLLs.

## 4. Job B — add a new language

Equivalent of `add-language.yml`. Inputs: folder name (e.g. `french`), display
name (e.g. `French`), Windows LANGID in decimal (e.g. `1036`).

1. `cp -r languages/english languages/<folder>` then delete the copied
   `resource.dll` and `updates.txt` (they are regenerated in step 8).
2. `descript.txt`: set `name` (ASCII display name), `locale`, `id` (LANGID),
   `homeurl` → `https://raw.githubusercontent.com/ukatech/ssp-i18n/master/languages/<folder>/`.
   Keep `craftman`/`craftmanurl` unless told otherwise. ASCII only (do not copy the
   GBK/Big5 `menu.font.name` lines of the current Chinese packs — they are a known bug).
3. `install.txt`: `name,<display name>`, `directory,<folder>`.
4. Translate `message.txt`, all UI strings in `resource.rc`, `surfacetable.txt`.
   Work dialog by dialog; render each one with `rcview.py` as you go.
5. `md5buildignore.txt`, `holidays.txt`: keep the english copies.
6. Optional `ssp-pictures/` with localized loading images (see `chinese-simplified/`).
7. Add the locale to: README language table; `auto_release.yml` (the `for locale`
   loop, the `7z` lines, release body links and `files:`); `md5-CI-build.yml`
   (one more md5 step — the **last** step is the one without `no-push`).
   `tools/*.py` and `build-resource.ps1` pick up new folders automatically
   (add a link label to `RELEASE_LABELS` in `tools/release.py` if the install.txt
   name is not what the release notes should show).
8. Verify as in Job A step 4 (`python tools/i18n_check.py <folder>` must report no ERROR),
   then build `resource.dll` and write `updates.txt` (Job C steps 1–3).
9. Commit: `feat(i18n): add <Display name> (<folder>) [i18n-manual]`. Do not modify other locales.

## 4b. Job C — network update files and release (manual mode)

Replaces `md5-CI-build.yml` and `auto_release.yml` for `[i18n-manual]` work.

1. **Preconditions.** `python tools/i18n_check.py` reports no ERROR, and every
   locale whose `resource.rc` changed has a freshly built `resource.dll` (§3.1).
2. **Update files.** `python tools/release.py updates` rewrites `updates.txt` of every
   locale whose files changed (output is byte-identical to the md5 CI: files filtered
   by the locale's `md5buildignore.txt`, fixed date, sorted, CRLF). Then
   `python tools/release.py verify` must print `updates.txt OK`.
   Do this **last**: any later change to a shipped file (including `resource.dll`)
   makes `updates.txt` stale again.
3. **Commit and push** to `master`/`main`:
   `chore(i18n): update network update files [i18n-manual]` (it may be the same commit
   as the translation; what matters is that the pushed head carries the marker and
   `updates.txt` matches).
4. **Release — only when the human asks for it, and after they confirm the tag.**
   The tag is the SSP version the packs correspond to (normally the english
   `FILEVERSION` in `resource.rc`, e.g. `2.8.91.12`); ask if unsure.
   ```sh
   git checkout master && git pull          # head commit must contain [i18n-manual]
   python tools/release.py verify
   python tools/release.py nar --out dist
   python tools/release.py notes <tag> > dist/notes.md
   git tag <tag> && git push origin <tag>   # auto_release.yml sees the marker and does nothing
   gh release create <tag> dist/*.nar --title <tag> --notes-file dist/notes.md
   ```
   Without `gh`, give the human `dist/*.nar` and `dist/notes.md` to upload on the
   GitHub release page. Check that the release lists one `.nar` per locale.

## 5. Translation rules

These are what reviewers check; `i18n_check.py` enforces most of them.

* **Translate meaning, keep it short.** Dialog geometry is shared with english.
  Do not change coordinates or sizes to make a translation fit unless the human asks;
  SSP widens static labels automatically, but buttons, check boxes, radio buttons
  and group box captions do not grow. Prefer a shorter wording when `rcview` flags a problem.
* **Access keys (`&`).** If the english string has an `&X` access key the translation
  needs exactly one. Latin-script languages put `&` before a suitable letter of the
  translated word; CJK uses a suffix `(&X)` with the english letter, e.g.
  `"在线更新(&N)\tCtrl+U"`. `&&` is a literal ampersand.
* **Keyboard shortcuts after `\t`** in menus (`\tCtrl+U`) are copied unchanged.
* **Placeholders** must survive exactly: `%1 %2 %s %d`, `[NUM]`, `[FONT]`,
  SakuraScript tags like `\0 \1 \-`. Literal `\n` in `message.txt` is a line break;
  keep roughly the same line structure.
* **Comma-separated lists** in `message.txt` (e.g. `resource.common.yesno,Yes,No`):
  keep the same number of fields; never put an ASCII comma inside a field (use the
  language's own comma, e.g. `，` / `、`). Prose commas in english are followed by a
  space; list separators are not.
* **Trailing spaces** in `message.txt` values are significant (text is concatenated).
* **Do not translate:** `IDC_HELPFILE` texts (`config-*.htm`), placeholder captions of
  common controls (`Slider1`, `List1`, `Spin1`, `DateTimePicker1`, …), file names,
  protocol/product names (SSP, SSTP, SHIORI, SERIKO, NAR, FMO, IPMessenger, …),
  `(DUMMY:…)` strings.
* **Never change** IDs, control types, styles, `FONT`, `MENU`, or the order of controls,
  except to mirror english. Hidden controls (`NOT WS_VISIBLE`) must stay hidden:
  rc.exe adds `WS_VISIBLE` to every control unless `NOT WS_VISIBLE` is written.
* Terminology: keep wording consistent inside a locale (grep `message.txt` and
  `resource.rc` of that locale for the english term before inventing a new one),
  but fix existing wording when it is wrong rather than spreading it.
  SSP-specific terms used by the existing Chinese packs: ghost = 人格, shell = 外壳/外殼,
  balloon = 对话框/對話方塊.

## 6. Prompt template

> Read AGENTS.md. Do Job A (sync translations) for all locales. Base revision: auto.
> Show me the `--changes` list first, then apply, verify with i18n_check and rcview,
> and give me a per-locale summary. Do not commit until I approve.

> Read AGENTS.md. Manual mode: do Job A for all locales, build resource.dll (§3.1),
> then Job C steps 1–3 and push to master. Do not tag or release until I say so.
