# AGENTS.md — working on ssp-i18n with a general-purpose coding agent

This repository holds the language packs (UI translations) of
[SSP](http://ssp.shillest.net/). Translation is normally automated by
[fount-CI](https://github.com/steve02081504/fount-CI) (see
`.github/workflows/sync-translations.yml` and `add-language.yml`). This file
describes the **same two jobs** so that Claude Code, Codex or any other agent
(or a human) can do them *semi-manually*: the agent does the work, a human
reviews the result before it is merged.

Everything below works on Linux/macOS/Windows. Only building `resource.dll`
needs Windows (Visual C++ `rc.exe` / `link.exe`); CI does that for you.

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
| `descript.txt` | no (fields only) | **ASCII only** outside comments. `id` = Windows LANGID (decimal). `homeurl` ends with `/languages/<folder>/`. |
| `holidays.txt`, `md5buildignore.txt` | no | Copy from english. |
| `resource.dll`, `updates.txt` | never by hand | Built/updated by CI. |
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
5. **Build** (Windows only): `pwsh ./scripts/build-resource.ps1`. Otherwise skip;
   after merge run the **rebuild resource.dll** workflow (it chains the md5 update).
6. **Commit** only the translated locales (not english, not `resource.dll` unless you
   built it on Windows). Message: `chore(i18n): sync translations from english update`.
   If english and translations are pushed together and you do *not* want
   fount-CI to run again on top, put `[i18n-manual]` in the head commit message
   (the sync job is skipped; md5/DLL rebuild still runs).
7. Hand over to a human: summarize which keys/controls were added or
   retranslated per locale and paste remaining WARN lines with a reason.

## 4. Job B — add a new language

Equivalent of `add-language.yml`. Inputs: folder name (e.g. `french`), display
name (e.g. `French`), Windows LANGID in decimal (e.g. `1036`).

1. `cp -r languages/english languages/<folder>` then delete the copied
   `resource.dll` and `updates.txt` (CI regenerates them).
2. `descript.txt`: set `name` (ASCII display name), `locale`, `id` (LANGID),
   `homeurl` → `https://raw.githubusercontent.com/ukatech/ssp-i18n/master/languages/<folder>/`.
   Keep `craftman`/`craftmanurl` unless told otherwise. ASCII only.
3. `install.txt`: `name,<display name>`, `directory,<folder>`.
4. Translate `message.txt`, all UI strings in `resource.rc`, `surfacetable.txt`.
   Work dialog by dialog; render each one with `rcview.py` as you go.
5. `md5buildignore.txt`, `holidays.txt`: keep the english copies.
6. Optional `ssp-pictures/` with localized loading images (see `chinese-simplified/`).
7. Add the locale to: README language table; `auto_release.yml` (the `for locale`
   loop, the `7z` lines, release body links and `files:`); `md5-CI-build.yml`
   (one more md5 step — the **last** step is the one without `no-push`).
   `tools/rcview.py`, `tools/i18n_check.py` and `build-resource.ps1` pick up new folders automatically.
8. Verify as in Job A step 4 (`python tools/i18n_check.py <folder>` must report no ERROR),
   build (Windows) or trigger **rebuild resource.dll** after merge.
9. Commit: `feat(i18n): add <Display name> (<folder>)`. Do not modify other locales.

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
* Terminology: reuse the existing wording of the locale (grep `message.txt` and
  `resource.rc` of that locale for the english term before inventing a new one).
  SSP-specific terms used by the existing Chinese packs: ghost = 人格, shell = 外壳/外殼,
  balloon = 对话框/對話方塊.

## 6. Prompt template

> Read AGENTS.md. Do Job A (sync translations) for all locales. Base revision: auto.
> Show me the `--changes` list first, then apply, verify with i18n_check and rcview,
> and give me a per-locale summary. Do not commit until I approve.
