#!/usr/bin/env python3
"""Consistency checker for SSP language packs (cross-platform, stdlib only).

Compares every locale under ``languages/`` with the source locale
(``languages/english/``) and reports structural drift and likely translation
mistakes. It does not need rc.exe, so it runs on Linux/macOS as well.

Usage:
    python tools/i18n_check.py                       # check all locales
    python tools/i18n_check.py chinese-simplified    # check one locale
    python tools/i18n_check.py --min-level warn      # hide info-level notes
    python tools/i18n_check.py --json                # machine readable output
    python tools/i18n_check.py --changes [REV]       # what changed in english since REV

Exit status: 1 when any error is reported (or any warning with --strict).
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sspres  # noqa: E402

LEVELS = ('info', 'warn', 'error')

REQUIRED_FILES = ('descript.txt', 'message.txt', 'resource.rc', 'surfacetable.txt',
                  'install.txt', 'holidays.txt', 'md5buildignore.txt')

WELL_KNOWN_IDS = {'IDOK': 1, 'IDCANCEL': 2, 'IDABORT': 3, 'IDRETRY': 4, 'IDIGNORE': 5,
                  'IDYES': 6, 'IDNO': 7, 'IDCLOSE': 8, 'IDHELP': 9, 'IDC_STATIC': -1}

# %1 %2 %s %d %ld, [NUM] [FONT], \0 \1 \- (SakuraScript scope / tags)
PLACEHOLDER_RE = re.compile(r'%(?:\d+|l?[sdux])|\[[A-Z_]+\]|\\[0-9\-]')
ACCEL_RE = re.compile(r'&([^&])')
LETTER_RE = re.compile(r'[A-Za-z]{2,}')
LIST_SEP_RE = re.compile(r',(?!\s)')


class Report(object):
    def __init__(self):
        self.items = []

    def add(self, level, locale, file, line, code, msg):
        self.items.append({'level': level, 'locale': locale, 'file': file,
                           'line': line, 'code': code, 'message': msg})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def placeholders(s):
    return sorted(PLACEHOLDER_RE.findall(s or ''))


def accel_count(s):
    return len(ACCEL_RE.findall((s or '').replace('&&', '')))


def menu_shortcut(s):
    return s.split('\t', 1)[1] if s and '\t' in s else None


def looks_untranslated(en_text, loc_text, loc):
    """Identical text containing words, in a non-English locale."""
    if loc.get('bcp47', 'en').startswith('en'):
        return False
    if not en_text or en_text != loc_text or en_text.startswith('(DUMMY'):
        return False
    stripped = re.sub(r'&|\\t.*|\t.*|%\w+|\[[A-Z_]+\]|https?://\S+|\S+\.(htm|html|exe|txt)\b', ' ', en_text)
    # Words that are commonly kept as-is (product / protocol names, keys).
    stripped = re.sub(r'\b(SSP|SSTP|SHIORI|SERIKO|MAYUNA|NAR|URL|HTTP|HTTPS|SNTP|POP|IMAP|FMO|OK|ON|OFF|'
                      r'IPMessenger|Git|Subversion|TortoiseSVN|TortoiseGit|Ctrl|Shift|Alt|Del|Win\d*|'
                      r'OS|UAC|API|ID|PNG|PNA|RSS|DPI|AI|TTS|IP|DNS|SSL|TLS|Unicode|UTF-8|Twitch|YouTube|OBS)\b',
                      ' ', stripped)
    return bool(LETTER_RE.search(stripped))


def resolve_id(sym, defines):
    if sym is None:
        return None
    if sym not in WELL_KNOWN_IDS and sym not in defines:
        try:
            v = int(sym, 0)
        except (TypeError, ValueError):
            return sym
        return v & 0xFFFF if v < 0 or v > 0xFFFF else v
    v = WELL_KNOWN_IDS.get(sym, defines.get(sym))
    return v & 0xFFFF if v < 0 else v


def load_all(names):
    header = sspres.load_header_defines()
    out = {}
    for n in names:
        loc = sspres.load_locale(n)
        loc['bcp47'] = sspres.bcp47_for(loc)
        defines = dict(header)
        if loc['rc']:
            defines.update(loc['rc']['defines'])
        loc['ids'] = defines
        out[n] = loc
    return out


# ---------------------------------------------------------------------------
# file-level checks
# ---------------------------------------------------------------------------


def check_files(rep, en, loc):
    name = loc['name']
    for f in REQUIRED_FILES:
        if not os.path.exists(os.path.join(loc['dir'], f)):
            rep.add('error', name, f, None, 'file-missing', 'required file is missing')
    for fname, tf in sorted(loc['files'].items()):
        if tf.decode_error and fname != 'descript.txt':  # descript.txt: see check_descript
            rep.add('error', name, fname, None, 'encoding', 'not valid UTF-8: %s' % tf.decode_error)
        if tf.bom:
            rep.add('warn', name, fname, None, 'bom', 'UTF-8 BOM present (english files have none)')
        if tf.crlf_lines and tf.lf_lines:
            rep.add('info', name, fname, None, 'mixed-eol',
                    'mixed line endings (%d CRLF / %d LF); keep the style of surrounding lines' % (tf.crlf_lines, tf.lf_lines))
    a = os.path.join(en['dir'], 'md5buildignore.txt')
    b = os.path.join(loc['dir'], 'md5buildignore.txt')
    if os.path.exists(a) and os.path.exists(b):
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            if fa.read().replace(b'\r\n', b'\n') != fb.read().replace(b'\r\n', b'\n'):
                rep.add('warn', name, 'md5buildignore.txt', None, 'md5ignore', 'differs from english/md5buildignore.txt')


# charset names seen in SSP files -> Python codecs
CHARSET_CODECS = {'utf-8': 'utf-8', 'utf8': 'utf-8', 'shift_jis': 'cp932', 'sjis': 'cp932', 'cp932': 'cp932',
                  'gb2312': 'gbk', 'gbk': 'gbk', 'gb18030': 'gb18030', 'big5': 'cp950', 'euc-kr': 'cp949',
                  'ks_c_5601-1987': 'cp949', 'ascii': 'ascii', 'us-ascii': 'ascii', 'iso-8859-1': 'latin-1'}


def check_descript_encoding(rep, name, raw):
    """descript.txt: with a charset line every byte must be valid in that
    charset; without one the file is ASCII (comments may be UTF-8)."""
    F = 'descript.txt'
    m = re.search(rb'^charset,[ \t]*([A-Za-z0-9_.\-]+)', raw, re.M)
    if m:
        cs = m.group(1).decode('ascii')
        codec = CHARSET_CODECS.get(cs.lower(), cs)
        try:
            raw.decode(codec)
        except LookupError:
            rep.add('error', name, F, None, 'descript-charset', 'unknown charset "%s"' % cs)
        except UnicodeDecodeError as e:
            line = raw.count(b'\n', 0, e.start) + 1
            rep.add('error', name, F, line, 'encoding',
                    'contains bytes that are not valid %s (declared by charset): %s' % (cs, e.reason))
        return
    for no, bline in enumerate(raw.split(b'\n'), 1):
        if all(b < 128 for b in bline):
            continue
        if bline.strip().startswith(b'//'):
            try:
                bline.decode('utf-8')
                continue
            except UnicodeDecodeError:
                pass
        try:
            shown = bline.decode('utf-8').strip()
        except UnicodeDecodeError:
            shown = repr(bline.strip())
        rep.add('error', name, F, no, 'encoding',
                'non-ASCII text without a charset line: descript.txt must be ASCII '
                '(or declare charset and use only that encoding): %s' % shown)


def check_descript(rep, loc):
    name = loc['name']
    entries = loc['descript.txt'] or []
    tf = loc['files'].get('descript.txt')
    if tf:
        check_descript_encoding(rep, name, tf.raw)
    d = sspres.kv_dict(entries)
    for key in ('name', 'locale', 'id', 'dllname', 'messagename', 'holidayname', 'homeurl'):
        if key not in d:
            rep.add('error', name, 'descript.txt', None, 'descript-field', 'missing field "%s"' % key)
    if 'id' in d and not d['id'].value.strip().isdigit():
        rep.add('error', name, 'descript.txt', d['id'].line, 'descript-id', 'id must be a decimal LANGID')
    if 'homeurl' in d:
        want = sspres.HOMEURL_FMT % name
        got = d['homeurl'].value.strip()
        if got == sspres.LEGACY_HOMEURL_FMT % name:
            rep.add('warn', name, 'descript.txt', d['homeurl'].line, 'descript-homeurl',
                    'homeurl uses the old "master" branch (works through GitHub\'s redirect); should be "%s"' % want)
        elif got != want:
            rep.add('error', name, 'descript.txt', d['homeurl'].line, 'descript-homeurl',
                    'homeurl must be "%s"' % want)
    if 'dllname' in d and d['dllname'].value.strip() != 'resource.dll':
        rep.add('warn', name, 'descript.txt', d['dllname'].line, 'descript-dll', 'dllname is not resource.dll')


def check_install(rep, loc):
    name = loc['name']
    d = sspres.kv_dict(loc['install.txt'] or [])
    if 'type' in d and d['type'].value.strip() != 'language':
        rep.add('error', name, 'install.txt', d['type'].line, 'install-type', 'type must be "language"')
    if 'directory' not in d or d['directory'].value.strip() != name:
        rep.add('error', name, 'install.txt', d['directory'].line if 'directory' in d else None,
                'install-directory', 'directory must be "%s"' % name)
    if 'name' not in d:
        rep.add('error', name, 'install.txt', None, 'install-name', 'missing "name"')


# ---------------------------------------------------------------------------
# key,value comparisons
# ---------------------------------------------------------------------------


def check_kv(rep, en, loc, fname, list_fields=True):
    name = loc['name']
    en_entries = en[fname] or []
    loc_entries = loc[fname]
    if loc_entries is None:
        return
    en_d = sspres.kv_dict(en_entries)
    loc_d = sspres.kv_dict(loc_entries)
    seen = set()
    for e in loc_entries:
        if e.key in seen:
            rep.add('warn', name, fname, e.line, 'kv-duplicate', 'duplicate key "%s"' % e.key)
        seen.add(e.key)
    for e in en_entries:
        if e.key not in loc_d:
            rep.add('error', name, fname, None, 'kv-missing',
                    'missing key "%s" (english line %d): %s' % (e.key, e.line, e.value))
    for e in loc_entries:
        if e.key not in en_d:
            rep.add('warn', name, fname, e.line, 'kv-extra', 'key "%s" does not exist in english' % e.key)
            continue
        src = en_d[e.key]
        if e.key == 'charset':
            if e.value.strip().upper() != 'UTF-8':
                rep.add('error', name, fname, e.line, 'charset', 'charset must be UTF-8')
            continue
        if placeholders(src.value) != placeholders(e.value):
            rep.add('warn', name, fname, e.line, 'placeholder',
                    '"%s": placeholders differ (english %s, here %s)'
                    % (e.key, placeholders(src.value), placeholders(e.value)))
        # A comma not followed by a space separates list fields
        # (e.g. "resource.common.yesno,Yes,No"); ", " in english is prose.
        en_sep = len(LIST_SEP_RE.findall(src.value))
        if list_fields and en_sep and en_sep != e.value.count(','):
            rep.add('error' if e.key.startswith('resource.') else 'warn', name, fname, e.line, 'list-fields',
                    '"%s": english has %d comma-separated fields, here %d (inside a field use a '
                    'full-width comma or other punctuation)' % (e.key, en_sep + 1, e.value.count(',') + 1))
        elif list_fields and not en_sep and LIST_SEP_RE.search(e.value):
            rep.add('info', name, fname, e.line, 'list-fields',
                    '"%s": contains "," without a following space; english is a single field' % e.key)
        if src.value.count('\\n') != e.value.count('\\n'):
            rep.add('info', name, fname, e.line, 'newline-count',
                    '"%s": \\n count differs (english %d, here %d)' % (e.key, src.value.count('\\n'), e.value.count('\\n')))
        if looks_untranslated(src.value, e.value, loc):
            rep.add('info', name, fname, e.line, 'untranslated', '"%s" is identical to english' % e.key)
        if src.value.endswith(' ') != e.value.endswith(' ') and fname == 'message.txt':
            rep.add('info', name, fname, e.line, 'trailing-space',
                    '"%s": trailing space differs from english (it is concatenated with other text)' % e.key)


# ---------------------------------------------------------------------------
# resource.rc comparisons
# ---------------------------------------------------------------------------


def check_rc(rep, en, loc):
    name = loc['name']
    F = 'resource.rc'
    if loc['rc_error']:
        rep.add('error', name, F, None, 'rc-parse', loc['rc_error'])
        return
    if not loc['rc'] or not en['rc']:
        return
    en_res = sspres.resources_by_name(en['rc'])
    loc_res = sspres.resources_by_name(loc['rc'])
    for rname, r in en_res.items():
        if r['type'] not in ('MENU', 'DIALOG', 'DIALOGEX', 'MENUEX'):
            continue
        if rname not in loc_res:
            rep.add('error', name, F, None, 'res-missing',
                    '%s %s is missing (english line %d)' % (r['type'], rname, r['line']))
    for rname, r in loc_res.items():
        if r['type'] in ('VERSIONINFO',):
            continue
        if rname not in en_res:
            lvl = 'warn' if r['type'] in ('MENU', 'DIALOG', 'DIALOGEX') else 'info'
            rep.add(lvl, name, F, r['line'], 'res-extra', '%s %s does not exist in english' % (r['type'], rname))
            continue
        e = en_res[rname]
        if e['type'].rstrip('EX') != r['type'].rstrip('EX'):
            rep.add('error', name, F, r['line'], 'res-type', '%s is %s in english but %s here' % (rname, e['type'], r['type']))
            continue
        if r['type'].startswith('DIALOG'):
            check_dialog(rep, en, loc, e, r)
        elif r['type'].startswith('MENU'):
            check_menu(rep, en, loc, rname, e['items'], r['items'])
    st_en = dict((s['id'], s) for s in en['rc']['stringtable'])
    st_loc = dict((s['id'], s) for s in loc['rc']['stringtable'])
    for k, s in st_en.items():
        if k not in st_loc:
            rep.add('error', name, F, None, 'string-missing', 'STRINGTABLE %s missing' % k)
    for k, s in st_loc.items():
        if k in st_en and placeholders(st_en[k]['text']) != placeholders(s['text']):
            rep.add('warn', name, F, s['line'], 'placeholder', 'STRINGTABLE %s: placeholders differ' % k)


def _geo(c):
    return (c['x'], c['y'], c['w'], c['h'])


def match_controls(en_ctrls, loc_ctrls, en_ids, loc_ids):
    """Pair up controls of the same dialog. Returns (pairs, missing, extra)."""
    def key(c, ids):
        return resolve_id(c['id'], ids)

    pairs, missing = [], []
    pool = {}
    for c in loc_ctrls:
        pool.setdefault(key(c, loc_ids), []).append(c)
    statics_en = []
    for c in en_ctrls:
        k = key(c, en_ids)
        if k == 0xFFFF:
            statics_en.append(c)
            continue
        cand = pool.get(k)
        if cand:
            pairs.append((c, cand.pop(0)))
        else:
            missing.append(c)
    # IDC_STATIC: exact geometry first, then nearest of the same role.
    statics_loc = pool.get(0xFFFF, [])
    rest = []
    for c in statics_en:
        hit = next((s for s in statics_loc if _geo(s) == _geo(c)
                    and sspres.control_role(s) == sspres.control_role(c)), None)
        if hit:
            statics_loc.remove(hit)
            pairs.append((c, hit))
        else:
            rest.append(c)
    for c in rest:
        same = [s for s in statics_loc if sspres.control_role(s) == sspres.control_role(c)]
        if not same:
            missing.append(c)
            continue
        best = min(same, key=lambda s: abs(s['x'] - c['x']) + abs(s['y'] - c['y']))
        if abs(best['x'] - c['x']) + abs(best['y'] - c['y']) > 40:
            missing.append(c)
            continue
        statics_loc.remove(best)
        pairs.append((c, best))
    extra = [c for lst in pool.values() for c in lst]
    return pairs, missing, extra


def describe(c):
    t = c.get('text')
    return '%s %s%s' % (c['kind'], c['id'], (' "%s"' % t.replace('\n', '\\n')) if t else '')


def check_dialog(rep, en, loc, e, r):
    name = loc['name']
    F = 'resource.rc'
    dn = e['name']
    if (e['w'], e['h']) != (r['w'], r['h']):
        rep.add('warn', name, F, r['line'], 'dlg-size',
                '%s: size %dx%d differs from english %dx%d' % (dn, r['w'], r['h'], e['w'], e['h']))
    if (e['font'] or {}).get('size') != (r['font'] or {}).get('size') or \
            (e['font'] or {}).get('name') != (r['font'] or {}).get('name'):
        rep.add('warn', name, F, r['line'], 'dlg-font', '%s: FONT differs from english (%s vs %s)' % (dn, r['font'], e['font']))
    if resolve_id(e.get('menu'), en['ids']) != resolve_id(r.get('menu'), loc['ids']):
        rep.add('error', name, F, r['line'], 'dlg-menu', '%s: MENU %s differs from english %s' % (dn, r.get('menu'), e.get('menu')))
    if e.get('caption') and looks_untranslated(e['caption'], r.get('caption'), loc):
        rep.add('info', name, F, r.get('caption_line', r['line']), 'untranslated', '%s: CAPTION is identical to english' % dn)
    if (e.get('caption') is None) != (r.get('caption') is None):
        rep.add('warn', name, F, r['line'], 'dlg-caption', '%s: CAPTION present in only one of english/here' % dn)

    pairs, missing, extra = match_controls(e['controls'], r['controls'], en['ids'], loc['ids'])
    for c in missing:
        rep.add('error', name, F, r['line'], 'ctl-missing', '%s: missing control %s (english line %d)' % (dn, describe(c), c['line']))
    for c in extra:
        rep.add('warn', name, F, c['line'], 'ctl-extra', '%s: control %s does not exist in english' % (dn, describe(c)))
    for ec, lc in pairs:
        where = '%s/%s' % (dn, ec['id'] if ec['id'] != 'IDC_STATIC' else 'IDC_STATIC "%s"' % (ec.get('text') or ''))
        line = lc['line']
        er, lr = sspres.control_role(ec), sspres.control_role(lc)
        if er != lr:
            rep.add('error', name, F, line, 'ctl-role', '%s: control type %s differs from english %s' % (where, lr, er))
        if _geo(ec) != _geo(lc):
            rep.add('warn', name, F, line, 'ctl-geometry',
                    '%s: position/size %s differs from english %s' % (where, _geo(lc), _geo(ec)))
        if ec['id'] not in sspres.HIDDEN_KEY_IDS and sspres.control_visible(ec) != sspres.control_visible(lc):
            rep.add('error', name, F, line, 'ctl-visibility',
                    '%s: %s here but %s in english (rc.exe adds WS_VISIBLE unless "NOT WS_VISIBLE" is given)'
                    % (where, 'visible' if sspres.control_visible(lc) else 'hidden',
                       'visible' if sspres.control_visible(ec) else 'hidden'))
        if sspres.control_disabled(ec) != sspres.control_disabled(lc):
            rep.add('warn', name, F, line, 'ctl-disabled', '%s: WS_DISABLED differs from english' % where)
        if sspres.significant_style(ec) != sspres.significant_style(lc):
            rep.add('info', name, F, line, 'ctl-style', '%s: style %s differs from english %s'
                    % (where, sspres.significant_style(lc), sspres.significant_style(ec)))
        if ec['id'] == 'IDC_HELPFILE' and ec.get('text') != lc.get('text'):
            rep.add('error', name, F, line, 'helpfile', '%s: help file name must stay "%s"' % (where, ec.get('text')))
        if not sspres.is_translatable_control(ec):
            continue
        et, lt = ec.get('text') or '', lc.get('text') or ''
        if placeholders(et) != placeholders(lt):
            rep.add('warn', name, F, line, 'placeholder', '%s: placeholders differ (english %s, here %s)'
                    % (where, placeholders(et), placeholders(lt)))
        check_accel(rep, loc, F, line, where, et, lt)
        if looks_untranslated(et, lt, loc):
            rep.add('info', name, F, line, 'untranslated', '%s: "%s" is identical to english' % (where, et))
        if et and not lt.strip():
            rep.add('warn', name, F, line, 'empty-text', '%s: text is empty but english has "%s"' % (where, et))


def check_accel(rep, loc, F, line, where, et, lt):
    name = loc['name']
    ea, la = accel_count(et), accel_count(lt)
    if ea and not la:
        rep.add('warn', name, F, line, 'accel-missing', '%s: english has an "&" access key, translation has none' % where)
    elif not ea and la:
        rep.add('info', name, F, line, 'accel-extra', '%s: translation adds an "&" access key english does not have' % where)
    if la > 1:
        rep.add('warn', name, F, line, 'accel-multiple', '%s: more than one "&" access key' % where)


def _menu_sig(items, ids):
    sig = []
    for it in items:
        if it['kind'] == 'separator':
            sig.append(('sep',))
        elif it['kind'] == 'popup':
            sig.append(('popup',))
        else:
            sig.append(('item', resolve_id(it['id'], ids)))
    return sig


def check_menu(rep, en, loc, path, en_items, loc_items):
    name = loc['name']
    F = 'resource.rc'
    es, ls = _menu_sig(en_items, en['ids']), _menu_sig(loc_items, loc['ids'])
    sm = difflib.SequenceMatcher(a=es, b=ls, autojunk=False)
    anchor_line = loc_items[0]['line'] if loc_items else None
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for a, b in zip(en_items[i1:i2], loc_items[j1:j2]):
                if a['kind'] == 'popup':
                    check_menu_text(rep, loc, path, a, b)
                    check_menu(rep, en, loc, '%s > %s' % (path, a['text']), a['items'], b['items'])
                elif a['kind'] == 'item':
                    check_menu_text(rep, loc, path, a, b)
            continue
        if tag == 'replace' and (i2 - i1) == (j2 - j1) and all(
                es[i][0] == ls[j][0] == 'popup' for i, j in zip(range(i1, i2), range(j1, j2))):
            continue  # unreachable: popups compare equal
        for a in en_items[i1:i2]:
            rep.add('error', name, F, loc_items[j1]['line'] if j1 < len(loc_items) else anchor_line, 'menu-missing',
                    '%s: missing %s (english line %d)' % (path, _menu_desc(a), a['line']))
        for b in loc_items[j1:j2]:
            rep.add('warn', name, F, b['line'], 'menu-extra', '%s: %s does not exist in english at this position' % (path, _menu_desc(b)))


def _menu_desc(it):
    if it['kind'] == 'separator':
        return 'SEPARATOR'
    if it['kind'] == 'popup':
        return 'POPUP "%s"' % it['text']
    return 'MENUITEM "%s" %s' % (it['text'].replace('\t', '\\t'), it['id'])


def check_menu_text(rep, loc, path, a, b):
    name = loc['name']
    F = 'resource.rc'
    where = '%s > %s' % (path, a.get('id') or a['text'])
    if menu_shortcut(a['text']) != menu_shortcut(b['text']):
        rep.add('warn', name, F, b['line'], 'menu-shortcut', '%s: shortcut after \\t should stay "%s" (here "%s")'
                % (where, menu_shortcut(a['text']), menu_shortcut(b['text'])))
    if placeholders(a['text']) != placeholders(b['text']):
        rep.add('warn', name, F, b['line'], 'placeholder', '%s: placeholders differ' % where)
    if a['text']:
        check_accel(rep, loc, F, b['line'], where, a['text'], b['text'])
    if a['text'] and looks_untranslated(a['text'], b['text'], loc):
        rep.add('info', name, F, b['line'], 'untranslated', '%s: "%s" is identical to english' % (where, a['text'].replace('\t', '\\t')))


# ---------------------------------------------------------------------------
# english change listing (--changes)
# ---------------------------------------------------------------------------


def git(*args):
    return subprocess.check_output(('git',) + args, cwd=sspres.REPO_ROOT).decode('utf-8', 'replace')


def default_base_rev():
    """Last commit that touched a translated (non-english) locale's text files."""
    paths = []
    for n in sspres.list_translation_targets():
        for f in sspres.TRANSLATABLE_FILES:
            paths.append('languages/%s/%s' % (n, f))
    rev = git('log', '-1', '--format=%H', '--', *paths).strip()
    return rev or None


def load_english_at(rev):
    overrides = {}
    for f in sspres.TRANSLATABLE_FILES + ('descript.txt',):
        try:
            overrides[f] = git('show', '%s:languages/%s/%s' % (rev, sspres.SOURCE_LOCALE, f))
        except subprocess.CalledProcessError:
            overrides[f] = None
    return sspres.load_locale(sspres.SOURCE_LOCALE, overrides)


def list_changes(rev, out):
    old = load_english_at(rev)
    new = sspres.load_locale(sspres.SOURCE_LOCALE)
    header = sspres.load_header_defines()
    lines = []
    w = lines.append
    w('English changes since %s (%s)' % (rev[:12], git('log', '-1', '--format=%s', rev).strip()))
    w('Commits: ' + ', '.join(git('log', '--format=%h', '%s..HEAD' % rev, '--', 'languages/%s' % sspres.SOURCE_LOCALE,
                                  'shared/resource_r.h').split()) or 'Commits: (none, working tree only)')
    for fname in ('message.txt', 'surfacetable.txt', 'install.txt'):
        o = sspres.kv_dict(old[fname] or [])
        n = sspres.kv_dict(new[fname] or [])
        for k, e in n.items():
            if k not in o:
                w('[%s] ADDED   %s (line %d): %s' % (fname, k, e.line, e.value))
            elif o[k].value != e.value:
                w('[%s] CHANGED %s (line %d)\n    old: %s\n    new: %s' % (fname, k, e.line, o[k].value, e.value))
        for k in o:
            if k not in n:
                w('[%s] REMOVED %s' % (fname, k))
    if old['rc'] and new['rc']:
        old_ids = dict(header); old_ids.update(old['rc']['defines'])
        new_ids = dict(header); new_ids.update(new['rc']['defines'])
        o = sspres.resources_by_name(old['rc'])
        n = sspres.resources_by_name(new['rc'])
        for k, r in n.items():
            if k not in o:
                w('[resource.rc] ADDED   %s %s (line %d)' % (r['type'], k, r['line']))
                continue
            a = o[k]
            if r['type'].startswith('DIALOG'):
                if (a['x'], a['y'], a['w'], a['h']) != (r['x'], r['y'], r['w'], r['h']):
                    w('[resource.rc] CHANGED %s geometry %s -> %s (line %d)' % (k, (a['x'], a['y'], a['w'], a['h']),
                                                                              (r['x'], r['y'], r['w'], r['h']), r['line']))
                if a.get('caption') != r.get('caption'):
                    w('[resource.rc] CHANGED %s CAPTION "%s" -> "%s"' % (k, a.get('caption'), r.get('caption')))
                for key in ('style', 'exstyle', 'font', 'menu'):
                    if a.get(key) != r.get(key):
                        w('[resource.rc] CHANGED %s %s %s -> %s' % (k, key.upper(), a.get(key), r.get(key)))
                pairs, missing, extra = match_controls(a['controls'], r['controls'], old_ids, new_ids)
                for c in extra:
                    w('[resource.rc] ADDED   %s: %s @%s (line %d)' % (k, describe(c), _geo(c), c['line']))
                for c in missing:
                    w('[resource.rc] REMOVED %s: %s' % (k, describe(c)))
                for x, y in pairs:
                    diffs = []
                    if x.get('text') != y.get('text'):
                        diffs.append('text "%s" -> "%s"' % (x.get('text'), y.get('text')))
                    if _geo(x) != _geo(y):
                        diffs.append('geometry %s -> %s' % (_geo(x), _geo(y)))
                    if (sspres.control_role(x) != sspres.control_role(y)
                            or sspres.significant_style(x) != sspres.significant_style(y)
                            or sspres.control_visible(x) != sspres.control_visible(y)
                            or sspres.control_disabled(x) != sspres.control_disabled(y)):
                        diffs.append('type/style %s %s -> %s %s' % (sspres.control_role(x), x['style'],
                                                                  sspres.control_role(y), y['style']))
                    if x['id'] != y['id']:
                        diffs.append('id %s -> %s' % (x['id'], y['id']))
                    if diffs:
                        w('[resource.rc] CHANGED %s/%s (line %d): %s' % (k, y['id'], y['line'], '; '.join(diffs)))
            elif r['type'].startswith('MENU'):
                fo, fn = flatten_menu(a['items']), flatten_menu(r['items'])
                if fo != fn:
                    for l in difflib.unified_diff([_flat_str(x) for x in fo], [_flat_str(x) for x in fn], lineterm='', n=1):
                        if l.startswith(('---', '+++')):
                            continue
                        w('[resource.rc] %s %s' % (k, l))
        for k, r in o.items():
            if k not in n:
                w('[resource.rc] REMOVED %s %s' % (r['type'], k))
    if len(lines) == 2:
        w('(no english text/structure changes)')
    out.write('\n'.join(lines) + '\n')


def flatten_menu(items, prefix=''):
    out = []
    for it in items:
        if it['kind'] == 'popup':
            out.append((prefix, 'POPUP', it['text'], it['line']))
            out.extend(flatten_menu(it['items'], prefix + '  '))
        elif it['kind'] == 'separator':
            out.append((prefix, 'SEPARATOR', '', it['line']))
        else:
            out.append((prefix, it['id'], it['text'], it['line']))
    return [x[:3] + (x[3],) for x in out]


def _flat_str(x):
    return '%s%s "%s"' % (x[0], x[1], x[2].replace('\t', '\\t')) if x[1] != 'SEPARATOR' else '%sSEPARATOR' % x[0]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def check_updates(rep, loc):
    """updates.txt must describe the files that are shipped (tools/release.py)."""
    import release
    d = loc['dir']
    path = os.path.join(d, release.UPDATES)
    if not os.path.exists(path):
        rep.add('error', loc['name'], release.UPDATES, None, 'updates', 'missing (run: python tools/release.py updates %s)' % loc['name'])
        return
    with open(path, 'rb') as f:
        current = f.read()
    expected = release.render_updates([release.file_entry(d, r) for r in release.collect_files(d)])
    if current != expected:
        rep.add('warn', loc['name'], release.UPDATES, None, 'updates-stale',
                'does not match the files (run: python tools/release.py updates %s before releasing)' % loc['name'])


def run_checks(targets):
    names = sorted(set([sspres.SOURCE_LOCALE] + targets))
    locs = load_all(names)
    en = locs[sspres.SOURCE_LOCALE]
    rep = Report()
    if en['rc_error']:
        rep.add('error', en['name'], 'resource.rc', None, 'rc-parse', en['rc_error'])
    check_descript(rep, en)
    check_install(rep, en)
    check_updates(rep, en)
    for n in targets:
        if n == sspres.SOURCE_LOCALE:
            continue
        loc = locs[n]
        check_files(rep, en, loc)
        check_descript(rep, loc)
        check_install(rep, loc)
        check_updates(rep, loc)
        check_kv(rep, en, loc, 'message.txt')
        check_kv(rep, en, loc, 'surfacetable.txt', list_fields=False)
        check_rc(rep, en, loc)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('locales', nargs='*', help='locale folder names (default: every non-english locale)')
    ap.add_argument('--min-level', choices=LEVELS, default='info', help='hide findings below this level')
    ap.add_argument('--code', action='append', help='only show findings with this code (repeatable)')
    ap.add_argument('--json', action='store_true', help='print JSON')
    ap.add_argument('--strict', action='store_true', help='exit 1 on warnings too')
    ap.add_argument('--changes', nargs='?', const='auto', metavar='REV',
                    help='list english changes since REV (default: last commit touching a translated locale)')
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    if args.changes:
        rev = default_base_rev() if args.changes == 'auto' else args.changes
        if not rev:
            sys.exit('cannot determine base revision; pass one explicitly')
        rev = git('rev-parse', rev).strip()
        list_changes(rev, sys.stdout)
        return 0

    all_locales = sspres.list_locales()
    targets = args.locales or sspres.list_translation_targets()
    for t in targets:
        if t not in all_locales:
            sys.exit('unknown locale: %s (have: %s)' % (t, ', '.join(all_locales)))
    rep = run_checks(targets)
    min_idx = LEVELS.index(args.min_level)
    items = [i for i in rep.items if LEVELS.index(i['level']) >= min_idx and (not args.code or i['code'] in args.code)]
    if args.json:
        json.dump(items, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write('\n')
    else:
        for i in items:
            loc = 'languages/%s/%s' % (i['locale'], i['file'])
            if i['line']:
                loc += ':%d' % i['line']
            print('%-5s %s [%s] %s' % (i['level'].upper(), loc, i['code'], i['message']))
        counts = dict((lv, sum(1 for i in rep.items if i['level'] == lv)) for lv in LEVELS)
        print('\n%d error(s), %d warning(s), %d info' % (counts['error'], counts['warn'], counts['info']))
    errors = any(i['level'] == 'error' for i in rep.items)
    warns = any(i['level'] == 'warn' for i in rep.items)
    return 1 if errors or (args.strict and warns) else 0


if __name__ == '__main__':
    sys.exit(main())
