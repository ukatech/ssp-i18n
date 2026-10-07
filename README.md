# ssp-i18n

[SSP](http://ssp.shillest.net/) multilingual resource monorepo. `languages/english/` is the source locale; other locales are maintained by CI or contributors.

## Language packs

| Directory                        | Language            | LANGID |
| -------------------------------- | ------------------- | ------ |
| `languages/english/`             | English             | 1033   |
| `languages/chinese-simplified/`  | Simplified Chinese  | 2052   |
| `languages/chinese-traditional/` | Traditional Chinese | 1028   |

Each locale directory is a complete SSP language pack. Drag it into SSP or package it as a `.nar` for distribution.

## Directory layout

```
ssp-i18n/
├── shared/
│   └── resource_r.h          # Global resource ID header (shared by all locale resource.rc files)
├── languages/
│   ├── english/
│   ├── chinese-simplified/
│   └── chinese-traditional/
├── scripts/
│   ├── build-resource.ps1    # Build resource.dll for all or a single locale
│   └── convert-legacy-rc.ps1 # One-time legacy RC conversion tool (used for zh-CN/zh-TW migration)
├── tools/                    # Cross-platform helpers (Python 3, stdlib only)
│   ├── i18n_check.py         # Lint locales against english; list english changes since last sync
│   ├── rcview.py             # Render dialogs/menus/messages side by side as HTML/PNG, detect clipped text
│   └── sspres.py             # resource.rc / key,value parsers used by both
├── AGENTS.md                 # Semi-manual translation procedure for coding agents (Claude Code etc.)
└── .github/workflows/
```

## Local build

Requires the Visual C++ toolchain (`rc.exe`, `link.exe`). On Windows, install [Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

```powershell
# Build all locales
pwsh ./scripts/build-resource.ps1

# Build a single locale
pwsh ./scripts/build-resource.ps1 -Locale chinese-simplified
```

The script reads the `id` field from each locale's `descript.txt` as the LCID, and injects the `shared/` directory via `/i` to resolve `#include "resource_r.h"`.

## Checking and previewing translations (any OS)

```sh
python tools/i18n_check.py                 # report missing/extra keys, controls, menu items, placeholder and access-key problems
python tools/i18n_check.py --changes       # english changes since the last translation sync
python tools/rcview.py IDD_SETUP           # open .rcview/IDD_SETUP.html: english and translations side by side
python tools/rcview.py --audit             # list clipped/overlapping texts in every dialog (needs Playwright)
```

`rcview` emulates Windows dialog units and SSP's automatic widening of static labels, so it shows which
translated texts will still be cut off or run into other controls. See [AGENTS.md](AGENTS.md) for details.

## CI workflows

| Workflow                | Trigger                                                 | Description                                                                                                              |
| ----------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `sync-translations.yml` | Push to `languages/english/**` or `shared/resource_r.h` | [fount-CI](https://github.com/steve02081504/fount-CI) syncs English changes to other locales and rebuilds `resource.dll` (skipped when the head commit message contains `[i18n-manual]`) |
| `add-language.yml`      | Manual `workflow_dispatch`                              | Uses fount-CI to add a new language based on `languages/english/`                                                        |
| `rebuild-dll.yml`       | Manual `workflow_dispatch`                              | Rebuilds `resource.dll` for all locales and commits it (then the md5 update runs)                                        |
| `md5-CI-build.yml`      | Any push                                                | Updates the `updates.txt` MD5 manifest for each locale                                                                   |
| `auto_release.yml`      | Tag push                                                | Packages `english.nar`, `chinese-simplified.nar`, `chinese-traditional.nar` and publishes a Release                      |

### fount-CI secrets

Configure these in the repository Settings → Secrets:

| Secret            | Description                    |
| ----------------- | ------------------------------ |
| `OPENAI_BASE_URL` | OpenAI-compatible API base URL |
| `OPENAI_API_KEY`  | API key                        |
| `OPENAI_MODEL`    | Model name                     |

`sync-translations` checks out with `fetch-depth: 7` so the agent can diff the previous commit's `languages/english/` changes.

## Contributing

1. **Edit English resources**: Edit `languages/english/` directly (`message.txt`, `resource.rc`, etc.). CI will sync other locales on push.
2. **Edit translations**: You can edit a locale directly, but changes may be overwritten on the next `languages/english/` update. Review sync results after English changes.
3. **Add a new language**: Manually run **add new language** in Actions, providing the folder name, display name, and LANGID.
   - Both jobs can also be done semi-manually with a coding agent such as Claude Code by following [AGENTS.md](AGENTS.md), with a human reviewing the result.
4. **Update `resource_r.h`**: Generated by upstream SSP's `make_resource_rc.py` from `sakura.rc` / `resource.h`, placed in `shared/`. After updating, rebuild `languages/english/resource.rc` and push.

## Release

Push a version tag (e.g. `2.7.76.6`) to trigger `auto_release`. Download the corresponding `.nar` packages from GitHub Releases.
