# AGENTS.md — working on ssp-i18n with a general-purpose coding agent

This repository holds the language packs (UI translations) of
[SSP](http://ssp.shillest.net/). Translation is normally automated by
[fount-CI](https://github.com/steve02081504/fount-CI). This file describes the
**same jobs** so that Claude Code, Codex or any other agent (or a human) can do
them *semi-manually*: the agent does the work, the maintainer or translator
reviews it. Work is done by one person at a time, directly on `main` (no
branches or pull requests).

Contents: 1 Ground rules · 2 Repository · 3 Tools · 4 Jobs (A sync, B new language,
C update files and release, D holiday tables) · 5 Translation rules · 6 Prompt templates

---

## 1. Ground rules

### 1.1 CI mode and manual mode

| | CI mode (default) | Manual mode (`[i18n-manual]`) |
| --- | --- | --- |
| How | push without the marker | the commit message of the pushed head contains `[i18n-manual]` |
| Translation sync (`sync-translations.yml`) | fount-CI | **skipped** — the agent does Job A |
| `resource.dll` | CI (`md5-CI-build.yml` builds it) | the agent on Windows, or the manual `rebuild-dll.yml` workflow (§4.3) |
| `updates.txt` (MD5 list for network update) | CI (`md5-CI-build.yml`, "md5 fix~") | **skipped** — the agent (Job C) |
| Release on tag push (`auto_release.yml`) | CI | **skipped** — the agent (Job C) |

In manual mode nothing fixes things up after you push. Network update reads
straight from `main` (see `homeurl`), so a stale `updates.txt` on `main` breaks
updates for users immediately. **Every push to `main` must leave translations,
`resource.dll` and `updates.txt` consistent: regenerate `updates.txt` last**
(`python tools/release.py updates`, after `resource.dll` is built).

### 1.2 Two source texts, no reference implementation

* `languages/english/` and `languages/japanese/` are the **source texts, of equal
  rank** (§5.2). Neither is a translation target; a translation job never edits
  them. Both carry a `.reference-only` marker.
* The other folders are the **translated packs** (translation targets).
  `python tools/i18n_check.py` lists exactly these.
* **The existing translations are not a reference implementation.** The current
  packs (especially the Chinese ones, converted from decompiled resources) still
  contain bugs: missing resources/keys, controls that lose `NOT WS_VISIBLE`,
  wrongly encoded `descript.txt`, clipped labels, … Do not copy a pattern from
  another locale just because it is there; treat `i18n_check.py` ERRORs in
  existing files as bugs to fix, not as a baseline.

### 1.3 Platforms

Everything works on Linux/macOS/Windows except building `resource.dll`, which
needs Windows (Visual C++ `rc.exe` / `link.exe`); see §4.3 for agents without it.

---

## 2. Repository

### 2.1 Layout

| Path | Role |
| --- | --- |
| `languages/english/` | **Source text** and a shipped pack. Complete and kept in sync, so it is the **structural template** for every pack (keys, resources, controls, geometry). |
| `languages/japanese/` | **Source text**: the original Japanese wording. **Not a pack**: no `install.txt`/`surfacetable.txt`, not kept structurally in sync (own `resource_r.h`, missing files). Never built, linted, released or translated. |
| `languages/<locale>/` | One complete translated SSP language pack per folder. |
| `shared/resource_r.h` | Resource ID header shared by every `resource.rc`. Generated upstream; do not edit. |
| `scripts/build-resource.ps1` | Builds `resource.dll` (Windows only). |
| `tools/` | Cross-platform helpers (§3). Python 3; `pip install -r tools/requirements.txt` for the optional packages. |

### 2.2 Marker files

Only their existence matters; the content is a notice for humans.

| Marker | Meaning | Folders |
| --- | --- | --- |
| `.reference-only` | Source text: not a translation target, never edited by translation jobs. `i18n_check.py`, `rcview.py` and the default targets skip it. Listed in `md5buildignore.txt`, so it is not shipped. | `english`, `japanese` |
| `.not-shipped` | Never built, never in `updates.txt`, never released (`release.py`, `build-resource.ps1` skip it). `rcview.py` shows it only when named with `-l`. | `japanese` |

### 2.3 Files of a pack

| File | Translate? | Notes |
| --- | --- | --- |
| `message.txt` | yes | `key,value` lines. Keys must match english exactly. |
| `resource.rc` | UI strings only | Menus and dialogs. Structure must mirror english. |
| `surfacetable.txt` | yes | `id,label` lines; same ids as english. |
| `install.txt` | `name` only | `directory` must equal the folder name; `type,language`. |
| `descript.txt` | no (fields only) | See below. |
| `holidays.txt`, `holidays-XX.txt` | no | Holiday tables; generated (Job D, §4.4). |
| `md5buildignore.txt` | no | Copy from english. |
| `resource.dll` | never by hand | Built from `resource.rc` (§4.3). |
| `updates.txt` | never by hand | MD5 list for network update: CI, or `python tools/release.py updates` in manual mode. Only `updates.txt` is used (no `updates2.dau`). |
| `ssp-pictures/` | optional | Localized loading images `nowloading.png`, `realize.png` and their `_dark` variants, same size as english. Made with `tools/make_pictures.py`. Shipped in the `.nar` and `updates.txt`. |

`descript.txt`:
* **ASCII only** unless a `charset,…` line is present, and then *every* byte must
  be valid in that charset. Text in any other encoding (e.g. a GBK font name with
  no charset line) is a bug.
* `id` = Windows LANGID (decimal).
* `homeurl` must be exactly
  `https://raw.githubusercontent.com/ukatech/ssp-i18n/main/languages/<folder>/`
  (network update downloads the raw files from GitHub).
* `holidayname,holidays.txt` with the comment block of english that explains the
  country specific lookup.

All text files are UTF-8 **without BOM**. Keep the line-ending style that the
file already uses (the Chinese `resource.rc` files use CRLF; english uses LF).

`IDC_HELPFILE` (hidden `config-*.htm` controls) has been abolished in SSP and
removed from every `resource.rc`. Do not add it back; delete it if an old
resource file still has it.

---

## 3. Tools

```sh
python tools/i18n_check.py                     # structural + translation lint, all translated packs
python tools/i18n_check.py chinese-simplified  # one locale
python tools/i18n_check.py --min-level warn    # hide info notes
python tools/i18n_check.py --changes           # english changes since the last translation sync
python tools/i18n_check.py --changes <rev>     # ... since an explicit commit

python tools/rcview.py --list                  # dialog/menu ids
python tools/rcview.py IDD_SETUP               # dialog, english + all locales side by side -> .rcview/IDD_SETUP.html
python tools/rcview.py IDC_SPEEDUP             # dialog containing that control, control highlighted
python tools/rcview.py IDR_SAKURA_MENU         # menu
python tools/rcview.py info.install            # message.txt keys with that prefix
python tools/rcview.py IDD_SETUP -l french --png /tmp/setup.png   # render english + french to a PNG
python tools/rcview.py --audit -l french       # every dialog: clipped / overlapping text
python tools/rcview.py IDD_SETUP -l japanese   # english + the Japanese source side by side

python tools/release.py updates [LOCALE ...]   # regenerate updates.txt (same output as the md5 CI)
python tools/release.py verify  [LOCALE ...]   # updates.txt vs. files; exit 1 on mismatch
python tools/release.py nar --out dist         # <locale>.nar like auto_release.yml (updates.txt file set, no resource.rc)
python tools/release.py notes <tag>            # release notes body

python tools/make_pictures.py [LOCALE ...]     # localized ssp-pictures/ from english (texts/fonts in the script)
python tools/make_holidays.py [LOCALE ...]     # holiday tables of the translated packs (§4.4)
```

* `i18n_check.py` exits with status 1 when it reports an **ERROR**. Errors must
  be fixed. **WARN** should be fixed or explained. **INFO** is for review.
* `rcview.py` needs Pillow, no browser. It lays out dialogs like Windows (dialog
  units from the dialog font's base units, lines `tmHeight` apart) with the
  locale's dialog font (SimSun, PMingLiU, MS UI Gothic, Microsoft Sans Serif, …
  or a look-alike when that font is not installed; it prints a note then)
  **and SSP's automatic widening of static labels** (left-aligned labels grow to
  the right, right-aligned to the left, centred to both sides), then flags text
  that is still clipped, labels that run into another control, cross their group
  box or leave the dialog. `--audit` lists these for every dialog, `--png` draws
  the dialog/menu of each shown locale (`--scale 1` = Windows pixels), and the
  HTML page (selector for every dialog, menu and message group) shows the same.
  It is a quick check, not a pixel-exact one: 1–3 px results are noise and fonts
  may differ a little; check the final result in SSP on Windows when in doubt.
  Agents that can read images should look at the PNG of every dialog they changed.
* `make_pictures.py` needs Pillow; `make_holidays.py` needs the `holidays` package.
  The other tools need only the standard library.

---

## 4. Jobs

### 4.1 Job A — sync translations after a source text update

Equivalent of `sync-translations.yml`.

1. **Find what changed.** `python tools/i18n_check.py --changes` lists, since the
   last commit that touched a translated pack: added/changed/removed `message.txt`
   keys (old and new text), added/removed resources, dialog controls whose text,
   geometry or style changed, and menu diffs. If the default base looks wrong,
   pass a revision; `git diff <rev> -- languages/english shared/resource_r.h`
   gives the raw diff. `--changes` only follows english, so also look at
   `git diff <rev> -- languages/japanese`: the Japanese text may carry a change
   that english does not have yet, or the other way round (§5.2).
2. **Get the current gaps.** `python tools/i18n_check.py --min-level warn` shows
   what is already missing in each pack (`kv-missing`, `res-missing`,
   `ctl-missing`, `menu-missing`, …). Fix those as well; it is the same work.
3. **Apply the changes to every translated pack**, translating from both source
   texts (§5.2):
   * `message.txt`: add new keys at the same position as in english; retranslate
     changed values; delete removed keys.
   * `resource.rc`: mirror the structural change from english (new
     `MENUITEM`/`POPUP`/control/dialog, moved or resized controls, changed
     styles). Copy the english block, then translate only the quoted UI strings.
     Keep the symbolic IDs (`IDC_…`, `SAKURA_MENU_…`) exactly as in english; never
     use raw numbers. A new dialog/menu goes at the same place as in english.
   * `surfacetable.txt`, `install.txt`, `descript.txt` comments: align when english changed.
4. **Verify.**
   * `python tools/i18n_check.py` → no ERROR; look at new WARN/INFO lines for the
     parts you touched (`untranslated`, `placeholder`, `accel-*`, `list-fields`).
   * For each dialog/menu you touched: `python tools/rcview.py <ID> --png …` (or
     the HTML) and look at it. `python tools/rcview.py --audit` must not list new
     problems in the dialogs you touched.
5. **Commit** only the translated packs (never the source folders):
   `chore(i18n): sync translations from english update [i18n-manual]`.
6. **Build `resource.dll` and update `updates.txt`**: Job C steps 1–3.
7. **Hand over** to a human: which keys/controls were added or retranslated per
   locale, remaining WARN lines with a reason, and every discrepancy between the
   two source texts (§5.2).

### 4.2 Job B — add a new language

Equivalent of `add-language.yml`. Inputs: folder name (e.g. `french`), display
name (e.g. `French`), Windows LANGID in decimal (e.g. `1036`).

1. `cp -r languages/english languages/<folder>` (english is the structural
   template; never use `languages/japanese/`, it is not a complete pack), then
   delete the copied `.reference-only` (the new folder is a translation target),
   `resource.dll`, `updates.txt` (regenerated in step 8) and `holidays-*.txt`
   (english's country tables; step 5).
2. `descript.txt`: set `name` (ASCII display name), `locale`, `id` (LANGID),
   `homeurl` → `https://raw.githubusercontent.com/ukatech/ssp-i18n/main/languages/<folder>/`.
   Keep `craftman`/`craftmanurl` unless told otherwise. ASCII only (do not copy
   the GBK/Big5 `menu.font.name` lines of the current Chinese packs — known bug).
3. `install.txt`: `name,<display name>`, `directory,<folder>`.
4. Translate `message.txt`, all UI strings in `resource.rc`, `surfacetable.txt`,
   dialog by dialog, rendering each one with `rcview.py` as you go. Translate from
   both source texts (§5.2).
5. Holiday tables: add the countries of the language to `TABLES` in
   `tools/make_holidays.py` and run it (Job D). Until then the copied english
   `holidays.txt` (United States) stays.
6. Optional `ssp-pictures/`: add the locale to `LOCALES` in
   `tools/make_pictures.py`, run it and look at the four PNGs.
7. Add the locale to: README language table; `auto_release.yml` (the
   `for locale` loop, the `7z` lines, release body links and `files:`);
   `md5-CI-build.yml` (one more md5 step — the **last** step is the one without
   `no-push`). `tools/*.py` and `build-resource.ps1` pick up new folders
   automatically (add a link label to `RELEASE_LABELS` in `tools/release.py` if
   the install.txt name is not what the release notes should show).
8. Verify as in Job A step 4 (`python tools/i18n_check.py <folder>` must report
   no ERROR), then build `resource.dll` and write `updates.txt` (Job C steps 1–3).
9. Commit: `feat(i18n): add <Display name> (<folder>) [i18n-manual]`. Do not modify other locales.

### 4.3 Job C — network update files and release (manual mode)

Replaces `md5-CI-build.yml` and `auto_release.yml` for `[i18n-manual]` work.

1. **Preconditions.** `python tools/i18n_check.py` reports no ERROR, and every
   pack whose `resource.rc` changed has a freshly built `resource.dll`:
   * **On Windows** with Visual C++ Build Tools: `pwsh ./scripts/build-resource.ps1`
     (or `-Locale <folder>`), then commit the changed `languages/*/resource.dll`.
   * **Without Windows**: push your commits (with `[i18n-manual]` and
     `updates.txt` regenerated for the text files), then run the **rebuild
     resource.dll and updates.txt** workflow (`rebuild-dll.yml`: Actions → *Run
     workflow*, `gh workflow run rebuild-dll.yml`, or the GitHub API). On a
     Windows runner it builds every `resource.dll`, runs `tools/release.py
     updates` + `verify` and commits both as
     `chore: rebuild resource.dll and updates.txt [i18n-manual]`. It is manual
     only and independent of the other workflows. Wait until it succeeds, then
     `git pull` before any further work.
2. **Update files.** `python tools/release.py updates` rewrites `updates.txt` of
   every pack whose files changed (byte-identical to the md5 CI: files filtered
   by the pack's `md5buildignore.txt`, fixed date, sorted, CRLF). Then
   `python tools/release.py verify` must print `updates.txt OK`. Do this **last**:
   any later change to a shipped file (including `resource.dll`) makes
   `updates.txt` stale again.
3. **Commit and push** to `main`:
   `chore(i18n): update network update files [i18n-manual]` (it may be the same
   commit as the content change; what matters is that the pushed head carries the
   marker and `updates.txt` matches).
4. **Release — only when the human asks for it, and after they confirm the tag.**
   The tag is the SSP version the packs correspond to (normally the english
   `FILEVERSION` in `resource.rc`, e.g. `2.8.91.12`); ask if unsure.
   ```sh
   git checkout main && git pull            # head commit must contain [i18n-manual]
   python tools/release.py verify
   python tools/release.py nar --out dist
   python tools/release.py notes <tag> > dist/notes.md
   git tag <tag> && git push origin <tag>   # auto_release.yml sees the marker and does nothing
   gh release create <tag> dist/*.nar --title <tag> --notes-file dist/notes.md
   ```
   **Replacing the current release** (same version, when the human asks for it):
   move the tag and replace the assets instead.
   ```sh
   git tag -f <tag> && git push -f origin refs/tags/<tag>
   gh release upload <tag> dist/*.nar --clobber
   ```
   Without `gh`, give the human `dist/*.nar` and `dist/notes.md` to upload on the
   GitHub release page. Check that the release lists one `.nar` per locale, and
   that the `auto release` run for the tag skipped its build steps.

### 4.4 Job D — holiday tables

SSP marks the days of the holiday table as holidays in its calendar (Sundays
need not be listed). It first looks for a **country specific table**: the file
name of `holidayname` in `descript.txt` with `-` and the ISO 3166 country code of
the Windows region setting inserted before the extension (`holidays.txt` →
`holidays-GB.txt`). If that file does not exist, `holidays.txt` is used, so
`holidays.txt` is the table of the language's main country.

Format: header comments (`//`, ASCII), then one line per month,
`Year-Month,day day day` (no zero padding, days ascending), e.g. `2026-1,1 19`.
Holidays that fall on a Saturday or Sunday are listed too, and so are
substitute/observed days. The tables are shipped (in `updates.txt` and the `.nar`).

| Pack | `holidays.txt` | Country tables |
| --- | --- | --- |
| english | United States | AU, CA, GB, IE, NZ |
| japanese | Japan | — |
| chinese-simplified | China (mainland) | SG |
| chinese-traditional | Taiwan | HK, MO |
| korean | South Korea | — |

* **english and japanese** tables are maintained on the SSP side by the
  maintainer. Never edit or generate them.
* **Translated packs**: generated by `python tools/make_holidays.py` from the
  `holidays` package, with the corrections written in the script's docstring
  (China's State Council arrangements in `CN_BLOCKS`, a Korean election day, the
  categories used for HK and MO). The tables currently cover 2020–2030
  (`--years` to change).
* **Yearly update** (or when asked): update the package
  (`pip install -U holidays`), add the new year's block of the State Council
  arrangement to `CN_BLOCKS` (published around November; until then that year
  has statutory holidays only, and adjusted working days cannot be expressed at
  all), run the script, and **read the diff**: the package changes between
  versions, and temporary holidays or elections may be added or moved. The
  script stops if `CN_BLOCKS` does not agree with the package.
* **Adding a country**: add an entry to `TABLES` (first entry of a locale =
  `holidays.txt`) with a header comment naming exactly what is included. Prefer
  countries where the language is commonly used.
* Then Job C steps 2–3 (and step 4 if the human asks for a release).
  Commit: `feat(i18n): update holiday tables [i18n-manual]`.

---

## 5. Translation rules

These are what reviewers check; `i18n_check.py` enforces most of them.

### 5.1 Form

* **Translate meaning, keep it short.** Dialog geometry is shared with english.
  Do not change coordinates or sizes to make a translation fit unless the human
  asks; SSP widens static labels automatically, but buttons, check boxes, radio
  buttons and group box captions do not grow. Prefer a shorter wording when
  `rcview` flags a problem.
* **Access keys (`&`).** If the english string has an `&X` access key the
  translation needs exactly one. Latin-script languages put `&` before a
  suitable letter of the translated word; CJK uses a suffix `(&X)` with the
  english letter, e.g. `"在线更新(&N)\tCtrl+U"`. `&&` is a literal ampersand.
* **Keyboard shortcuts after `\t`** in menus (`\tCtrl+U`) are copied unchanged.
* **Placeholders** must survive exactly: `%1 %2 %s %d`, `[NUM]`, `[FONT]`,
  SakuraScript tags like `\0 \1 \-`. Literal `\n` in `message.txt` is a line
  break; keep roughly the same line structure.
* **Comma-separated lists** in `message.txt` (e.g. `resource.common.yesno,Yes,No`):
  keep the same number of fields; never put an ASCII comma inside a field (use
  the language's own comma, e.g. `，` / `、`). Prose commas in english are
  followed by a space; list separators are not.
* **Trailing spaces** in `message.txt` values are significant (text is concatenated).
* **Do not translate:** placeholder captions of common controls (`Slider1`,
  `List1`, `Spin1`, `DateTimePicker1`, …), file names, protocol/product names
  (SSP, SSTP, SHIORI, SERIKO, NAR, FMO, IPMessenger, …), `(DUMMY:…)` strings.
* **Never change** IDs, control types, styles, `FONT`, `MENU`, or the order of
  controls, except to mirror english. Hidden controls (`NOT WS_VISIBLE`) must
  stay hidden: rc.exe adds `WS_VISIBLE` to every control unless `NOT WS_VISIBLE`
  is written.
* **Terminology:** keep wording consistent inside a locale (grep `message.txt`
  and `resource.rc` of that locale for the english term before inventing a new
  one), but fix existing wording when it is wrong rather than spreading it.
  SSP-specific terms of the Chinese packs: ghost = 人格, shell = 外壳/外殼,
  balloon = 对话框/對話方塊.

### 5.2 The two source texts: english and japanese

Japanese is the original wording of SSP; the English text is the translation
made from it, so each can carry something the other has lost (tone, politeness,
what a term really refers to, whether a label is a noun or a verb, what a
setting actually does). Translate from both, not from one of them.

1. **Read both for every string** you translate:
   `python tools/rcview.py <key-prefix | IDD_… | IDC_…> -l japanese` shows english
   and Japanese side by side, or open `languages/japanese/message.txt` /
   `resource.rc` at the same key / control ID.
2. **Meaning from both, structure from english.** Which keys, resources and
   controls exist, their IDs, geometry, styles, placeholders and access keys are
   compared with english, because it is complete and kept in sync; the Japanese
   folder may lag behind or be ahead of it. That is a technical template, not a
   ranking of the texts: a key or control missing from japanese is not an error.
3. **Understand, do not copy.** Translate the *meaning* into the target language.
   Do not transliterate kanji, do not carry over Japanese-only conventions
   (full-width punctuation, `〜`, 「」, counters, honorific levels) and do not reuse
   Japanese word order. For Chinese packs the Japanese is not a shortcut either:
   kanji words often differ in meaning (`人格` / `外壳` / `对话框`, §5.1).
4. **When the two disagree in meaning, do not silently pick one.** Choose a
   wording that fits both if one exists; otherwise ask the maintainer, and list
   every real discrepancy in the hand-over so the source text can be fixed.
5. **Never change either source folder** in a translation job, add japanese to
   `updates.txt`, release it or give it an `install.txt`. Source text changes are
   made by the maintainer only.

---

## 6. Prompt templates

> Read AGENTS.md. Do Job A (sync translations) for all locales. Base revision: auto.
> Translate from both source texts, english and japanese, of equal rank (§5.2).
> Show me the `--changes` list first, then apply, verify with i18n_check and rcview,
> and give me a per-locale summary. Do not commit until I approve.

> Read AGENTS.md. Manual mode: do Job A for all locales, build resource.dll,
> then Job C steps 1–3 and push to main. Do not tag or release until I say so.

> Read AGENTS.md. Do Job D for <year>: update the holidays package, add the
> State Council arrangement for <year> to CN_BLOCKS, regenerate, show me the diff.
