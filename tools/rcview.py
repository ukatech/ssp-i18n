#!/usr/bin/env python3
"""Visualize SSP language-pack resources without Windows.

Renders a dialog, menu or message.txt keys of every locale side by side in a
self-contained HTML page, flags text that will probably be clipped, and can
save a PNG screenshot (via Playwright, if available).

Usage:
    python tools/rcview.py IDD_SETUP                    # dialog -> .rcview/IDD_SETUP.html
    python tools/rcview.py IDC_SPEEDUP                  # dialog(s) containing a control, highlighted
    python tools/rcview.py IDR_SAKURA_MENU              # menu
    python tools/rcview.py SAKURA_MENU_UPDATE           # menu containing a command id
    python tools/rcview.py info.install                 # message.txt keys with this prefix
    python tools/rcview.py IDD_SETUP -l chinese-simplified --png out.png
    python tools/rcview.py --audit [-l LOCALE]          # list clipped texts in every dialog (needs Playwright)
    python tools/rcview.py --list                       # list dialog/menu IDs

The HTML page has a selector for every resource, so one file is enough to
browse the whole language pack.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sspres  # noqa: E402
import i18n_check  # noqa: E402

TEMPLATE = os.path.join(HERE, 'rcview', 'viewer.html')
DEFAULT_OUT_DIR = os.path.join(sspres.REPO_ROOT, '.rcview')


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def build_data(locale_names, initial_target, initial_locales, zoom, auto_width=True):
    locs = i18n_check.load_all(locale_names)
    src = locs[sspres.SOURCE_LOCALE]
    src_res = sspres.resources_by_name(src['rc']) if src['rc'] else {}
    out_locs = []
    for name in locale_names:
        loc = locs[name]
        rc = loc['rc'] or {'resources': []}
        dialogs, menus = {}, {}
        for r in rc['resources']:
            if r['type'].startswith('DIALOG'):
                dialogs[r['name']] = dialog_json(r, src_res.get(r['name']), src, loc)
            elif r['type'].startswith('MENU'):
                menus[r['name']] = {'line': r['line'], 'items': r['items']}
        messages = {}
        for e in loc['message.txt'] or []:
            messages.setdefault(e.key, {'value': e.value, 'line': e.line})
        out_locs.append({
            'name': name, 'display': loc['display_name'], 'bcp47': loc['bcp47'], 'langid': loc['langid'],
            'file': 'languages/%s/resource.rc' % name, 'dialogs': dialogs, 'menus': menus, 'messages': messages,
            'error': loc['rc_error'],
        })
    # numeric menu ids (decompiled scripts) -> symbolic name
    menu_alias = {}
    header = sspres.load_header_defines()
    for sym, val in header.items():
        if sym.startswith('IDR_'):
            menu_alias[str(val)] = sym
    findings = i18n_check.run_checks([n for n in locale_names if n != sspres.SOURCE_LOCALE]).items
    groups = []
    for e in src['message.txt'] or []:
        if e.key == 'charset':
            continue
        parts = e.key.split('.')
        g = '.'.join(parts[:2]) + '.' if len(parts) > 2 else parts[0] + '.'
        if g not in groups:
            groups.append(g)
    return {
        'source': sspres.SOURCE_LOCALE,
        'locales': out_locs,
        'menuAlias': menu_alias,
        'messageGroups': groups,
        'findings': findings,
        'initial': {'target': initial_target, 'locales': initial_locales, 'zoom': zoom, 'autoWidth': auto_width},
    }


def dialog_json(r, src_r, src, loc):
    if src_r is not None and src_r is not r:
        pairs, missing, extra = i18n_check.match_controls(src_r['controls'], r['controls'], src['ids'], loc['ids'])
        pk_of = {}
        src_of = {}
        for a, b in pairs:
            pk_of[id(b)] = 'c%d' % src_r['controls'].index(a)
            src_of[id(b)] = a
    else:
        pk_of = dict((id(c), 'c%d' % i) for i, c in enumerate(r['controls']))
        src_of = dict((id(c), c) for c in r['controls'])
    ctrls = []
    for i, c in enumerate(r['controls']):
        s = src_of.get(id(c))
        ctrls.append({
            'pk': pk_of.get(id(c), 'x%d' % i), 'id': c['id'], 'kind': c['kind'], 'cls': c['cls'],
            'role': sspres.control_role(c), 'text': c['text'], 'style': c['style'],
            'x': c['x'], 'y': c['y'], 'w': c['w'], 'h': c['h'], 'line': c['line'],
            'visible': sspres.control_shown(c), 'disabled': sspres.control_disabled(c),
            'translatable': sspres.is_translatable_control(c),
            'srcText': s['text'] if s is not None else None,
            'geoDiff': bool(s is not None and (s['x'], s['y'], s['w'], s['h']) != (c['x'], c['y'], c['w'], c['h'])),
        })
    return {'line': r['line'], 'x': r['x'], 'y': r['y'], 'w': r['w'], 'h': r['h'], 'style': r['style'],
            'caption': r['caption'], 'font': r['font'], 'menu': r['menu'], 'controls': ctrls}


def resolve_target(target, locs_data):
    """Map a user-supplied id to (hash, description)."""
    src = next(l for l in locs_data if l['name'] == sspres.SOURCE_LOCALE)
    everything = locs_data
    if target.startswith('msg:'):
        return target, 'messages'
    for l in [src] + everything:
        if target in l['dialogs']:
            return target, 'dialog'
        if target in l['menus']:
            return target, 'menu'
    # control id -> dialogs containing it
    hits = []
    for l in [src] + everything:
        for dn, d in l['dialogs'].items():
            if any(c['id'] == target for c in d['controls']) and dn not in hits:
                hits.append(dn)
    if hits:
        return '%s/%s' % (hits[0], target), 'control in ' + ', '.join(hits)
    # menu command id
    for l in [src] + everything:
        for mn, m in l['menus'].items():
            if _menu_has(m['items'], target):
                return '%s/%s' % (mn, target), 'menu item in ' + mn
    if any(k == target or k.startswith(target) for k in src['messages']):
        return 'msg:' + target, 'messages'
    return None, None


def _menu_has(items, ident):
    for it in items:
        if it.get('id') == ident:
            return True
        if it['kind'] == 'popup' and _menu_has(it['items'], ident):
            return True
    return False


def write_html(data, path):
    with open(TEMPLATE, encoding='utf-8') as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    html = tpl.replace('/*__DATA__*/', payload)
    d = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)


# ---------------------------------------------------------------------------
# headless browser (optional)
# ---------------------------------------------------------------------------

NODE_SCRIPT = r"""
const [html, png, mode] = process.argv.slice(2);
let pw;
try { pw = require('playwright'); } catch (e) { pw = require('playwright-core'); }
(async () => {
  const opts = {};
  if (process.env.RCVIEW_CHROMIUM) opts.executablePath = process.env.RCVIEW_CHROMIUM;
  const browser = await pw.chromium.launch(opts);
  const page = await browser.newPage({viewport: {width: 1700, height: 1000}, deviceScaleFactor: 1});
  await page.goto(html);
  await page.waitForSelector('body[data-ready="1"]', {state: 'attached'});
  let result;
  if (mode === 'audit') {
    result = await page.evaluate(() => window.auditAll());
  } else {
    result = await page.evaluate(() => window.__result);
    if (png) {
      await page.evaluate(() => { document.body.classList.add('shot'); });
      const el = await page.$(await page.evaluate(() => document.querySelector('#stage').children.length ? '#stage' : '#table'));
      await el.screenshot({path: png});
    }
  }
  process.stdout.write(JSON.stringify(result));
  await browser.close();
})().catch(e => { console.error(e.message || e); process.exit(2); });
"""


def run_browser(html, png, mode):
    """Return the page's result object. Tries Python Playwright, then Node Playwright."""
    import pathlib
    uri = pathlib.Path(os.path.abspath(html)).as_uri()
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        sync_playwright = None
    if sync_playwright is not None:
        with sync_playwright() as p:
            opts = {}
            if os.environ.get('RCVIEW_CHROMIUM'):
                opts['executable_path'] = os.environ['RCVIEW_CHROMIUM']
            browser = p.chromium.launch(**opts)
            page = browser.new_page(viewport={'width': 1700, 'height': 1000})
            page.goto(uri)
            page.wait_for_selector('body[data-ready="1"]', state='attached')
            if mode == 'audit':
                res = page.evaluate('() => window.auditAll()')
            else:
                res = page.evaluate('() => window.__result')
                if png:
                    page.evaluate("() => { document.body.classList.add('shot'); }")
                    sel = page.evaluate("() => document.querySelector('#stage').children.length ? '#stage' : '#table'")
                    page.query_selector(sel).screenshot(path=png)
            browser.close()
            return res
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Playwright not found. Install it with "pip install playwright && playwright install chromium" '
                           'or "npm i -g playwright", or open the HTML file in a browser instead.')
    env = dict(os.environ)
    npm = shutil.which('npm')
    if npm:
        try:
            root = subprocess.check_output([npm, 'root', '-g'], stderr=subprocess.DEVNULL).decode().strip()
            env['NODE_PATH'] = os.pathsep.join(filter(None, [env.get('NODE_PATH'), root]))
        except (subprocess.CalledProcessError, OSError):
            pass
    with tempfile.NamedTemporaryFile('w', suffix='.cjs', delete=False) as f:
        f.write(NODE_SCRIPT)
        script = f.name
    try:
        p = subprocess.run([node, script, uri, png or '', mode], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        os.unlink(script)
    if p.returncode != 0:
        raise RuntimeError('headless browser failed: ' + p.stderr.decode('utf-8', 'replace').strip())
    return json.loads(p.stdout.decode('utf-8') or 'null')


def issue_text(o):
    kind = o.get('kind') or 'clipped'
    s = {'clipped': 'CLIPPED ~%dpx', 'overlap': 'OVERLAP ~%dpx', 'outside': 'OUTSIDE-DIALOG ~%dpx',
         'frame': 'CROSSES-GROUPBOX ~%dpx'}.get(kind, kind.upper() + ' ~%dpx') % o['px']
    if o.get('other'):
        s += ' with ' + o['other']
    return s


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', nargs='?', help='IDD_*/IDR_* resource, IDC_*/command id, or message.txt key/prefix (msg:...)')
    ap.add_argument('-l', '--locale', action='append', help='locale(s) to show next to english (default: all)')
    ap.add_argument('-o', '--out', help='output HTML path (default: .rcview/<target>.html)')
    ap.add_argument('--png', help='also save a PNG screenshot of the rendered view (needs Playwright)')
    ap.add_argument('--audit', action='store_true', help='report clipped texts in every dialog (needs Playwright)')
    ap.add_argument('--list', action='store_true', help='list dialog and menu ids')
    ap.add_argument('--zoom', type=float, default=1.5, help='initial zoom in the HTML (default 1.5)')
    ap.add_argument('--json', action='store_true', help='print overflow/audit results as JSON')
    ap.add_argument('--no-autowidth', action='store_true',
                    help="don't emulate SSP's automatic widening of static labels")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    all_locales = sspres.list_locales()
    chosen = args.locale or [n for n in all_locales if n != sspres.SOURCE_LOCALE]
    for n in chosen:
        if n not in all_locales:
            sys.exit('unknown locale: %s (have: %s)' % (n, ', '.join(all_locales)))
    shown = [sspres.SOURCE_LOCALE] + [n for n in chosen if n != sspres.SOURCE_LOCALE]

    if args.list:
        en = sspres.load_locale(sspres.SOURCE_LOCALE)
        for r in en['rc']['resources']:
            if r['type'].startswith(('DIALOG', 'MENU')):
                extra = (' "%s"' % r['caption']) if r.get('caption') else ''
                print('%-26s %-9s line %-5d%s' % (r['name'], r['type'], r['line'], extra))
        return 0

    if not args.target and not args.audit:
        ap.error('give a target id, --audit or --list')

    data = build_data(shown, '', shown, args.zoom, not args.no_autowidth)
    if args.target:
        hash_, kind = resolve_target(args.target, data['locales'])
        if not hash_:
            sys.exit('not found: %s (try --list)' % args.target)
    else:
        hash_, kind = next(iter(data['locales'][0]['dialogs'])), 'dialog'
    data['initial']['target'] = hash_
    safe = hash_.replace('/', '__').replace(':', '_') if args.target else 'audit'
    out = args.out or os.path.join(DEFAULT_OUT_DIR, safe + '.html')
    write_html(data, out)
    print('HTML: %s  (%s: %s)' % (os.path.relpath(out), kind, hash_))

    if args.audit:
        res = run_browser(out, None, 'audit')
        res = [r for r in res if r['locale'] in chosen or args.locale is None]
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for r in res:
                print('%s languages/%s/resource.rc:%s %s/%s "%s"'
                      % (issue_text(r), r['locale'], r['line'], r['dialog'], r['id'], r['text'].replace('\n', '\\n')))
            print('%d layout issue(s)' % len(res))
        return 0

    if args.png:
        res = run_browser(out, args.png, 'view')
        print('PNG:  %s' % args.png)
        overflow = (res or {}).get('overflow') or {}
        if args.json:
            print(json.dumps(overflow, ensure_ascii=False, indent=1))
        else:
            for loc, items in overflow.items():
                for o in items:
                    print('%s %s %s "%s"' % (issue_text(o), loc, o['id'], o['text'].replace('\n', '\\n')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
