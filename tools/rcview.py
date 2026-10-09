#!/usr/bin/env python3
"""Visualize SSP language-pack resources without Windows.

Lays out a dialog like Windows does (dialog units, the locale's dialog font,
SSP's automatic label widening), flags text that will probably be clipped or
run into another control, and shows it in a self-contained HTML page next to
english and the other locales. --png renders the dialog or menu to an image
and --audit checks every dialog. Needs Pillow (pip install pillow); no browser.

Usage:
    python tools/rcview.py IDD_SETUP                    # dialog -> .rcview/IDD_SETUP.html
    python tools/rcview.py IDC_SPEEDUP                  # dialog(s) containing a control, highlighted
    python tools/rcview.py IDR_SAKURA_MENU              # menu
    python tools/rcview.py SAKURA_MENU_UPDATE           # menu containing a command id
    python tools/rcview.py info.install                 # message.txt keys with this prefix
    python tools/rcview.py IDD_SETUP -l chinese-simplified --png out.png
    python tools/rcview.py --audit [-l LOCALE]          # list clipped/overlapping texts in every dialog
    python tools/rcview.py --list                       # list dialog/menu IDs

The HTML page has a selector for every resource, so one file is enough to
browse the whole language pack.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sspres  # noqa: E402
import i18n_check  # noqa: E402

try:
    import dlglayout  # noqa: E402
    import fontbook  # noqa: E402
    from PIL import Image  # noqa: E402,F401
except ImportError:
    sys.exit('rcview.py needs Pillow: pip install pillow')

TEMPLATE = os.path.join(HERE, 'rcview', 'viewer.html')
DEFAULT_OUT_DIR = os.path.join(sspres.REPO_ROOT, '.rcview')


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def build_data(locale_names, initial_target, initial_locales, zoom, auto_width=True, font_name=None):
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
                d = dialogs[r['name']] = dialog_json(r, src_res.get(r['name']), src, loc)
                # layout with and without SSP's label auto-width (the viewer can toggle it)
                d['layout'] = {
                    'on': dlglayout.Layout(d, loc['bcp47'], True, font_name).to_json(),
                    'off': dlglayout.Layout(d, loc['bcp47'], False, font_name).to_json(),
                }
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
    findings = i18n_check.run_checks([n for n in locale_names
                                    if not sspres.is_reference_locale(n)]).items
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
# audit / PNG
# ---------------------------------------------------------------------------


def audit(data, locale_names, auto_width=True):
    """Layout issues of every dialog in the given locales."""
    out = []
    key = 'on' if auto_width else 'off'
    for loc in data['locales']:
        if loc['name'] not in locale_names:
            continue
        for dn, d in loc['dialogs'].items():
            for o in d['layout'][key]['issues']:
                out.append(dict(o, locale=loc['name'], dialog=dn))
    return out


def _menubar(data, loc, dlg):
    if not dlg.get('menu'):
        return None
    m = loc['menus'].get(dlg['menu']) or loc['menus'].get(data['menuAlias'].get(str(dlg['menu']), ''))
    return [it.get('text') or '' for it in m['items']] if m else None


def render_png(data, hash_, path, scale=2, auto_width=True, font_name=None, show_hidden=False):
    """Render the dialog or menu named by hash_ for every locale; return {locale: issues}."""
    name, _, hl = hash_.partition('/')
    panes, overflow = [], {}
    for loc in data['locales']:
        sub = None
        if name in loc['dialogs']:
            d = loc['dialogs'][name]
            lay = dlglayout.Layout(d, loc['bcp47'], auto_width, font_name)
            overflow[loc['name']] = lay.issues
            body = dlglayout.render_dialog(lay, _menubar(data, loc, d), _pk_for(d, hl), show_hidden)
            n = len(lay.issues)
            badge = ('%d issue(s)' % n, dlglayout.BAD) if n else ('fits', dlglayout.OK)
            sub = '%s:%s  %s %dpx' % (loc['file'], d['line'], lay.font.family, lay.px)
        elif name in loc['menus']:
            m = loc['menus'][name]
            body = dlglayout.render_menu(m['items'], loc['bcp47'], hl or None)
            badge = None
            sub = '%s:%s' % (loc['file'], m['line'])
        else:
            ui = fontbook.ui_font(12)
            body = Image.new('RGBA', (260, ui.height + 8), dlglayout.PANE_BG + (255,))
            dlglayout.draw_text_box(body, (0, 4, 260, 4 + ui.height), ui, [(0, '%s is missing in this locale.' % name)],
                                    color=dlglayout.BAD)
            badge = None
        panes.append(dlglayout.pane(body, loc['display'], sub, badge))
    dlglayout.save_png(dlglayout.compose(panes), path, scale)
    return overflow


def _pk_for(d, ident):
    """Control pk for a highlight id (IDC_... or pk)."""
    if not ident:
        return None
    c = next((c for c in d['controls'] if c['id'] == ident or c['pk'] == ident), None)
    return c['pk'] if c else ident


def issue_text(o):
    return dlglayout.issue_text(o)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', nargs='?', help='IDD_*/IDR_* resource, IDC_*/command id, or message.txt key/prefix (msg:...)')
    ap.add_argument('-l', '--locale', action='append', help='locale(s) to show next to english (default: all language packs; '
                    'the reference japanese is shown only when named here)')
    ap.add_argument('-o', '--out', help='output HTML path (default: .rcview/<target>.html)')
    ap.add_argument('--png', help='also render the dialog or menu of every shown locale to a PNG file')
    ap.add_argument('--scale', type=float, default=2, help='PNG scale factor (default 2; 1 = Windows pixels)')
    ap.add_argument('--show-hidden', action='store_true', help='draw hidden controls (dashed) in the PNG')
    ap.add_argument('--audit', action='store_true', help='report clipped/overlapping texts in every dialog')
    ap.add_argument('--list', action='store_true', help='list dialog and menu ids')
    ap.add_argument('--zoom', type=float, default=1.5, help='initial zoom in the HTML (default 1.5)')
    ap.add_argument('--json', action='store_true', help='print overflow/audit results as JSON')
    ap.add_argument('--font', help='measure every locale with this font family instead of the locale default')
    ap.add_argument('--no-autowidth', action='store_true',
                    help="don't emulate SSP's automatic widening of static labels")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    all_locales = sspres.list_locales(include_unshipped=True)
    chosen = args.locale or sspres.list_translation_targets()
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
    if args.font and not fontbook.find_face(args.font):
        print('warning: font "%s" is not installed; using fallback fonts' % args.font, file=sys.stderr)

    auto_width = not args.no_autowidth
    data = build_data(shown, '', shown, args.zoom, auto_width, args.font)
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
    for loc in data['locales']:
        f = fontbook.font_for_locale(loc['bcp47'], 12, args.font)
        if not f.exact:
            print('note: %s: "%s" is not installed, measured with "%s" (results are less exact)'
                  % (loc['name'], f.requested[0], f.family), file=sys.stderr)
        if f.missing:
            print('note: %s: no installed font has %d of the characters used (e.g. %s); they are measured as '
                  'full width. Install a CJK font (e.g. Noto Sans CJK) for exact results.'
                  % (loc['name'], len(f.missing), ''.join(f.missing[:8])), file=sys.stderr)

    if args.audit:
        res = audit(data, chosen if args.locale else shown, auto_width)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for r in res:
                print('%s languages/%s/resource.rc:%s %s/%s "%s"'
                      % (issue_text(r), r['locale'], r['line'], r['dialog'], r['id'], r['text'].replace('\n', '\\n')))
            print('%d layout issue(s)' % len(res))
        return 0

    if args.png:
        if hash_.startswith('msg:'):
            sys.exit('--png renders dialogs and menus; open the HTML for message.txt keys')
        overflow = render_png(data, hash_, args.png, args.scale, auto_width, args.font, args.show_hidden)
        print('PNG:  %s' % args.png)
        if args.json:
            print(json.dumps(overflow, ensure_ascii=False, indent=1))
        else:
            for loc, items in overflow.items():
                for o in items:
                    print('%s %s %s "%s"' % (issue_text(o), loc, o['id'], o['text'].replace('\n', '\\n')))
    return 0


if __name__ == '__main__':
    sys.exit(main())


