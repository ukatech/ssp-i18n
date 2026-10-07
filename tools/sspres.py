"""Parsers for the SSP language-pack resources in this repository.

Pure Python standard library; works on any OS (no rc.exe needed).

* ``parse_rc(text)``     -> parsed resource script (menus, dialogs, string tables, ...)
* ``parse_kv(text)``     -> ``key,value`` files (message.txt, surfacetable.txt, install.txt, descript.txt)
* ``load_locale(dir)``   -> everything above for one ``languages/<locale>/`` folder

Only the subset of the RC language that SSP's ``resource.rc`` actually uses is
understood, but unknown top-level resources are skipped gracefully.
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_ROOT = os.path.join(REPO_ROOT, 'languages')
SOURCE_LOCALE = 'english'

# Network-update URL of a locale (descript.txt "homeurl"): files are served raw from GitHub.
HOMEURL_FMT = 'https://raw.githubusercontent.com/ukatech/ssp-i18n/master/languages/%s/'

# Files that carry translatable text (relative to a locale folder).
TRANSLATABLE_FILES = ('message.txt', 'resource.rc', 'surfacetable.txt', 'install.txt')

# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


class TextFile(object):
    """Decoded text plus the facts about its encoding we want to lint."""

    def __init__(self, path, data):
        self.path = path
        self.raw = data
        self.bom = data.startswith(b'\xef\xbb\xbf')
        if self.bom:
            data = data[3:]
        self.decode_error = None
        try:
            self.text = data.decode('utf-8')
        except UnicodeDecodeError as e:
            self.decode_error = str(e)
            self.text = data.decode('utf-8', errors='replace')
        crlf = data.count(b'\r\n')
        lf = data.count(b'\n') - crlf
        self.crlf_lines = crlf
        self.lf_lines = lf


def read_text(path):
    with open(path, 'rb') as f:
        return TextFile(path, f.read())


# ---------------------------------------------------------------------------
# key,value files
# ---------------------------------------------------------------------------


class KvEntry(object):
    __slots__ = ('key', 'value', 'line')

    def __init__(self, key, value, line):
        self.key = key
        self.value = value
        self.line = line

    def to_json(self):
        return {'key': self.key, 'value': self.value, 'line': self.line}


def parse_kv(text):
    """Parse ``key,value`` lines. ``//`` comments and blank lines are ignored.

    Returns a list of KvEntry in file order (duplicates are kept).
    """
    out = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip('\r')
        s = line.strip()
        if not s or s.startswith('//'):
            continue
        if ',' in line:
            k, v = line.split(',', 1)
        else:
            k, v = line, ''
        out.append(KvEntry(k.strip(), v, no))
    return out


def kv_dict(entries):
    d = {}
    for e in entries:
        d.setdefault(e.key, e)
    return d


# ---------------------------------------------------------------------------
# Resource script tokenizer
# ---------------------------------------------------------------------------


class Tok(object):
    __slots__ = ('kind', 'value', 'line')

    def __init__(self, kind, value, line):
        self.kind = kind    # 'str' | 'num' | 'id' | 'op'
        self.value = value
        self.line = line

    def __repr__(self):
        return 'Tok(%s,%r,%d)' % (self.kind, self.value, self.line)


_RC_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', '\\': '\\', '"': '"', '0': '\0'}

_NUM_RE = re.compile(r'(0[xX][0-9A-Fa-f]+|\d+)[LlUu]*')
_ID_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*')


def _unescape_rc(body):
    out = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '\\' and i + 1 < n:
            nxt = body[i + 1]
            if nxt in _RC_ESCAPES:
                out.append(_RC_ESCAPES[nxt])
                i += 2
                continue
            if nxt == 'x':
                m = re.match(r'[0-9A-Fa-f]{1,4}', body[i + 2:])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += 2 + len(m.group(0))
                    continue
            out.append(c)
            i += 1
            continue
        if c == '"' and i + 1 < n and body[i + 1] == '"':
            out.append('"')
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def tokenize_rc(text, defines=None):
    """Tokenize an RC script. Preprocessor lines are dropped, but simple
    ``#define NAME VALUE`` lines are collected into *defines*."""
    toks = []
    i = 0
    n = len(text)
    line = 1
    at_line_start = True
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
            at_line_start = True
            continue
        if c in ' \t\r\f\v':
            i += 1
            continue
        if at_line_start and c == '#':
            j = text.find('\n', i)
            if j < 0:
                j = n
            directive = text[i:j]
            # Line continuation for preprocessor lines.
            while directive.rstrip('\r').endswith('\\') and j < n:
                k = text.find('\n', j + 1)
                if k < 0:
                    k = n
                directive += text[j:k]
                line += 1
                j = k
            if defines is not None:
                m = re.match(r'#\s*define\s+(\w+)\s+\(?\s*(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*\)?', directive)
                if m:
                    defines[m.group(1)] = int(m.group(2), 0)
            i = j
            continue
        at_line_start = False
        if c == '/' and text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == '/' and text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            line += text.count('\n', i, j)
            i = j
            continue
        if c == '"' or (c in 'Ll' and i + 1 < n and text[i + 1] == '"'):
            start_line = line
            if c != '"':
                i += 1
            j = i + 1
            while j < n:
                if text[j] == '\\' and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            body = text[i + 1:j]
            line += body.count('\n')
            toks.append(Tok('str', _unescape_rc(body), start_line))
            i = j + 1
            continue
        if c.isdigit():
            m = _NUM_RE.match(text, i)
            toks.append(Tok('num', int(m.group(1), 0), line))
            i = m.end()
            continue
        if c.isalpha() or c == '_':
            m = _ID_RE.match(text, i)
            toks.append(Tok('id', m.group(0), line))
            i = m.end()
            continue
        toks.append(Tok('op', c, line))
        i += 1
    return toks


# ---------------------------------------------------------------------------
# Resource script parser
# ---------------------------------------------------------------------------

DIALOG_TEXT_CONTROLS = {
    'LTEXT', 'RTEXT', 'CTEXT', 'PUSHBUTTON', 'DEFPUSHBUTTON', 'PUSHBOX',
    'CHECKBOX', 'AUTOCHECKBOX', 'RADIOBUTTON', 'AUTORADIOBUTTON',
    'STATE3', 'AUTO3STATE', 'GROUPBOX', 'ICON',
}
DIALOG_NOTEXT_CONTROLS = {'EDITTEXT', 'COMBOBOX', 'LISTBOX', 'SCROLLBAR'}
DIALOG_CONTROLS = DIALOG_TEXT_CONTROLS | DIALOG_NOTEXT_CONTROLS | {'CONTROL'}
DIALOG_OPTIONS = {'STYLE', 'EXSTYLE', 'CAPTION', 'FONT', 'MENU', 'CLASS',
                  'LANGUAGE', 'CHARACTERISTICS', 'VERSION'}
MEMORY_FLAGS = {'DISCARDABLE', 'MOVEABLE', 'FIXED', 'PURE', 'IMPURE',
                'PRELOAD', 'LOADONCALL', 'SHARED', 'NONSHARED'}
BEGIN_WORDS = {'BEGIN', '{'}
END_WORDS = {'END', '}'}


class RcParseError(Exception):
    pass


class _Parser(object):
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    # -- token helpers ------------------------------------------------------
    def peek(self, off=0):
        j = self.i + off
        return self.toks[j] if j < len(self.toks) else None

    def next(self):
        t = self.peek()
        if t is None:
            raise RcParseError('unexpected end of file')
        self.i += 1
        return t

    def at_word(self, words, off=0):
        t = self.peek(off)
        return t is not None and ((t.kind == 'id' and t.value.upper() in words)
                                  or (t.kind == 'op' and t.value in words))

    def accept_op(self, op):
        t = self.peek()
        if t is not None and t.kind == 'op' and t.value == op:
            self.i += 1
            return True
        return False

    def expect_begin(self):
        if not self.at_word(BEGIN_WORDS):
            t = self.peek()
            raise RcParseError('expected BEGIN at line %s, got %r' % (t.line if t else '?', t.value if t else None))
        self.i += 1

    def skip_block(self):
        """Skip tokens up to and including the matching END."""
        self.expect_begin()
        depth = 1
        while depth:
            t = self.next()
            if (t.kind == 'id' and t.value.upper() == 'BEGIN') or (t.kind == 'op' and t.value == '{'):
                depth += 1
            elif (t.kind == 'id' and t.value.upper() == 'END') or (t.kind == 'op' and t.value == '}'):
                depth -= 1

    # -- expressions --------------------------------------------------------
    def term(self):
        t = self.next()
        if t.kind == 'id' and t.value.upper() == 'NOT':
            return 'NOT ' + self.term()
        if t.kind == 'op' and t.value == '(':
            parts = [self.expr()]
            while not self.accept_op(')'):
                parts.append(self.expr())
            return '(' + ' '.join(parts) + ')'
        if t.kind == 'op' and t.value in '-~':
            v = self.term()
            if t.value == '-' and isinstance(v, int):
                return -v
            return t.value + str(v)
        if t.kind == 'str':
            return {'str': t.value}
        if t.kind == 'num':
            return t.value
        return t.value

    def expr(self):
        """Parse ``term (| term)*``; returns a scalar or a list of flags."""
        first = self.term()
        parts = [first]
        while True:
            t = self.peek()
            if t is not None and t.kind == 'op' and t.value in '|+':
                self.i += 1
                parts.append(self.term())
            else:
                break
        if len(parts) == 1:
            return first
        return [p if isinstance(p, str) else str(p) for p in parts]

    def arglist(self):
        args = [self.expr()]
        while self.accept_op(','):
            args.append(self.expr())
        return args

    # -- resources ----------------------------------------------------------
    def parse(self):
        res = {'resources': [], 'stringtable': [], 'language': None}
        while self.peek() is not None:
            t = self.peek()
            if t.kind == 'id' and t.value.upper() == 'LANGUAGE':
                self.next()
                res['language'] = self.arglist()
                continue
            if t.kind == 'id' and t.value.upper() == 'STRINGTABLE':
                self.next()
                self.parse_stringtable(res['stringtable'])
                continue
            name_tok = self.next()
            if name_tok.kind not in ('id', 'num', 'str'):
                raise RcParseError('unexpected token %r at line %d' % (name_tok.value, name_tok.line))
            type_tok = self.next()
            rtype = str(type_tok.value).upper() if type_tok.kind in ('id', 'num') else str(type_tok.value)
            r = {'name': str(name_tok.value), 'type': rtype, 'line': name_tok.line}
            if rtype in ('MENU', 'MENUEX'):
                self.skip_memflags()
                r['items'] = self.parse_menu_block()
            elif rtype in ('DIALOG', 'DIALOGEX'):
                self.parse_dialog(r)
            elif rtype == 'VERSIONINFO':
                while not self.at_word(BEGIN_WORDS):
                    self.next()
                self.skip_block()
            else:
                self.skip_memflags()
                t2 = self.peek()
                if t2 is not None and t2.kind == 'str':
                    r['file'] = self.next().value
                else:
                    while t2 is not None and not self.at_word(BEGIN_WORDS):
                        self.next()
                        t2 = self.peek()
                    if t2 is not None:
                        self.skip_block()
            res['resources'].append(r)
        return res

    def skip_memflags(self):
        while self.at_word(MEMORY_FLAGS):
            self.next()

    def parse_stringtable(self, out):
        self.skip_memflags()
        while not self.at_word(BEGIN_WORDS):
            self.next()  # LANGUAGE/CHARACTERISTICS etc.
        self.expect_begin()
        while not self.at_word(END_WORDS):
            id_tok = self.next()
            self.accept_op(',')
            s = self.next()
            out.append({'id': str(id_tok.value), 'text': s.value, 'line': id_tok.line})
        self.next()

    def parse_menu_block(self):
        self.expect_begin()
        items = []
        while not self.at_word(END_WORDS):
            t = self.next()
            kw = t.value.upper() if t.kind == 'id' else t.value
            if kw == 'POPUP':
                text = self.next().value
                opts = []
                while self.accept_op(','):
                    opts.append(self.expr())
                items.append({'kind': 'popup', 'text': text, 'line': t.line,
                              'flags': [o for o in opts if isinstance(o, str)],
                              'items': self.parse_menu_block()})
            elif kw == 'MENUITEM':
                if self.at_word({'SEPARATOR'}):
                    self.next()
                    items.append({'kind': 'separator', 'line': t.line})
                    continue
                args = self.arglist()
                text = args[0]['str'] if isinstance(args[0], dict) else str(args[0])
                item = {'kind': 'item', 'text': text, 'line': t.line,
                        'id': str(args[1]) if len(args) > 1 else '',
                        'flags': [str(a) for a in args[2:]]}
                items.append(item)
            else:
                raise RcParseError('unexpected %r in MENU at line %d' % (t.value, t.line))
        self.next()
        return items

    def parse_dialog(self, r):
        self.skip_memflags()
        geo = self.arglist()
        r['x'], r['y'], r['w'], r['h'] = [_num(v) for v in geo[:4]]
        r['style'] = []
        r['exstyle'] = []
        r['caption'] = None
        r['font'] = None
        r['menu'] = None
        r['class'] = None
        while not self.at_word(BEGIN_WORDS):
            t = self.next()
            kw = t.value.upper() if t.kind == 'id' else t.value
            if kw == 'STYLE':
                r['style'] = _flags(self.expr())
            elif kw == 'EXSTYLE':
                r['exstyle'] = _flags(self.expr())
            elif kw == 'CAPTION':
                r['caption'] = self.next().value
                r['caption_line'] = t.line
            elif kw == 'FONT':
                a = self.arglist()
                r['font'] = {'size': _num(a[0]), 'name': a[1]['str'] if len(a) > 1 and isinstance(a[1], dict) else '',
                              'extra': [str(_plain(x)) for x in a[2:]]}
            elif kw == 'MENU':
                r['menu'] = str(self.next().value)
            elif kw == 'CLASS':
                r['class'] = str(self.next().value)
            elif kw in DIALOG_OPTIONS:
                self.arglist()
            else:
                raise RcParseError('unexpected %r in DIALOG header at line %d' % (t.value, t.line))
        self.expect_begin()
        controls = []
        while not self.at_word(END_WORDS):
            t = self.next()
            kw = t.value.upper() if t.kind == 'id' else None
            if kw not in DIALOG_CONTROLS:
                raise RcParseError('unknown dialog control %r at line %d' % (t.value, t.line))
            args = self.arglist()
            controls.append(_make_control(kw, args, t.line))
        self.next()
        r['controls'] = controls


def _num(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.match(r'^-?(0[xX][0-9A-Fa-f]+|\d+)$', v)
        if m:
            return int(v, 0)
    return v


def _plain(v):
    return v['str'] if isinstance(v, dict) else v


def _flags(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(_plain(v))]


def _make_control(kw, args, line):
    c = {'kind': kw, 'line': line, 'text': None, 'id': None, 'cls': None,
         'style': [], 'exstyle': [], 'x': 0, 'y': 0, 'w': 0, 'h': 0}
    a = list(args)
    if kw == 'CONTROL':
        # CONTROL text, id, class, style, x, y, w, h [, exstyle]
        c['text'] = _plain(a[0])
        c['id'] = str(_plain(a[1]))
        c['cls'] = str(_plain(a[2]))
        c['style'] = _flags(a[3])
        c['x'], c['y'], c['w'], c['h'] = [_num(_plain(v)) for v in a[4:8]]
        if len(a) > 8:
            c['exstyle'] = _flags(a[8])
    elif kw in DIALOG_NOTEXT_CONTROLS:
        c['id'] = str(_plain(a[0]))
        c['x'], c['y'], c['w'], c['h'] = [_num(_plain(v)) for v in a[1:5]]
        if len(a) > 5:
            c['style'] = _flags(a[5])
        if len(a) > 6:
            c['exstyle'] = _flags(a[6])
    else:
        c['text'] = _plain(a[0])
        if not isinstance(c['text'], str):
            c['text'] = str(c['text'])
        c['id'] = str(_plain(a[1]))
        if kw == 'ICON':
            c['x'], c['y'] = _num(_plain(a[2])), _num(_plain(a[3]))
            if len(a) >= 6:
                c['w'], c['h'] = _num(_plain(a[4])), _num(_plain(a[5]))
            if len(a) > 6:
                c['style'] = _flags(a[6])
        else:
            c['x'], c['y'], c['w'], c['h'] = [_num(_plain(v)) for v in a[2:6]]
            if len(a) > 6:
                c['style'] = _flags(a[6])
            if len(a) > 7:
                c['exstyle'] = _flags(a[7])
    if c['id'] in ('-1',):
        c['id'] = 'IDC_STATIC'
    return c


def parse_rc(text, defines=None):
    """Parse a resource script. Returns
    ``{'resources': [...], 'stringtable': [...], 'language': ..., 'defines': {...}}``."""
    if defines is None:
        defines = {}
    toks = tokenize_rc(text, defines)
    res = _Parser(toks).parse()
    res['defines'] = defines
    return res


def resources_by_name(rc):
    return dict((r['name'], r) for r in rc['resources'])


def load_header_defines(path=None):
    path = path or os.path.join(REPO_ROOT, 'shared', 'resource_r.h')
    d = {}
    if os.path.exists(path):
        tokenize_rc(read_text(path).text, d)
    return d


# ---------------------------------------------------------------------------
# Control classification (used by both checker and viewer)
# ---------------------------------------------------------------------------

# Placeholder captions emitted by the old VC++ resource editor; never shown.
PLACEHOLDER_TEXT_RE = re.compile(
    r'^(Slider|List|Spin|DateTimePicker|Tab|Progress|Tree|Custom|IPAddress|MonthCalendar|Animate|Hotkey|RichEdit)\d*$')


def control_role(c):
    """Return a coarse role: button, defbutton, check, radio, group, static,
    edit, combo, listbox, listview, trackbar, updown, datetime, progress, tab,
    icon, frame, other."""
    kw = c['kind']
    st = set(c.get('style') or [])
    if kw == 'CONTROL':
        cls = (c.get('cls') or '').lower()
        if cls == 'button':
            if st & {'BS_AUTOCHECKBOX', 'BS_CHECKBOX', 'BS_AUTO3STATE', 'BS_3STATE'}:
                return 'check'
            if st & {'BS_AUTORADIOBUTTON', 'BS_RADIOBUTTON'}:
                return 'radio'
            if 'BS_GROUPBOX' in st:
                return 'group'
            if 'BS_DEFPUSHBUTTON' in st:
                return 'defbutton'
            return 'button'
        if cls == 'static':
            if st & {'SS_BLACKFRAME', 'SS_GRAYFRAME', 'SS_WHITEFRAME', 'SS_ETCHEDFRAME',
                     'SS_ETCHEDHORZ', 'SS_ETCHEDVERT', 'SS_BLACKRECT', 'SS_GRAYRECT', 'SS_WHITERECT'}:
                return 'frame'
            if st & {'SS_ICON', 'SS_BITMAP'}:
                return 'icon'
            return 'static'
        return {
            'edit': 'edit', 'combobox': 'combo', 'comboboxex32': 'combo', 'listbox': 'listbox',
            'syslistview32': 'listview', 'systreeview32': 'listview',
            'msctls_trackbar32': 'trackbar', 'msctls_updown32': 'updown',
            'sysdatetimepick32': 'datetime', 'msctls_progress32': 'progress',
            'systabcontrol32': 'tab', 'scrollbar': 'scrollbar',
        }.get(cls, 'other')
    return {
        'LTEXT': 'static', 'RTEXT': 'static', 'CTEXT': 'static',
        'PUSHBUTTON': 'button', 'PUSHBOX': 'button', 'DEFPUSHBUTTON': 'defbutton',
        'CHECKBOX': 'check', 'AUTOCHECKBOX': 'check', 'STATE3': 'check', 'AUTO3STATE': 'check',
        'RADIOBUTTON': 'radio', 'AUTORADIOBUTTON': 'radio',
        'GROUPBOX': 'group', 'ICON': 'icon', 'EDITTEXT': 'edit', 'COMBOBOX': 'combo',
        'LISTBOX': 'listbox', 'SCROLLBAR': 'scrollbar',
    }.get(kw, 'other')


def control_visible(c):
    """rc.exe ORs WS_CHILD|WS_VISIBLE into every control statement, so a
    control is hidden only when its style says ``NOT WS_VISIBLE``."""
    return 'NOT WS_VISIBLE' not in (c.get('style') or [])


# Controls SSP uses as hidden data holders; never shown in the dialog.
HIDDEN_KEY_IDS = {'IDC_HELPFILE'}


def control_shown(c):
    """Whether the control is actually displayed by SSP."""
    return control_visible(c) and c.get('id') not in HIDDEN_KEY_IDS


def control_disabled(c):
    st = c.get('style') or []
    return 'WS_DISABLED' in st and 'NOT WS_DISABLED' not in st


# Flags that are implicit or zero-valued; ignored when comparing styles
# (decompiled scripts spell them out, hand-written ones do not).
IMPLICIT_STYLE_FLAGS = {
    'WS_CHILD', 'WS_VISIBLE', 'WS_GROUP', 'WS_TABSTOP', 'WS_BORDER',
    'BS_PUSHBUTTON', 'BS_TEXT', 'BS_DEFPUSHBUTTON', 'BS_GROUPBOX', 'BS_CHECKBOX', 'BS_AUTOCHECKBOX',
    'BS_RADIOBUTTON', 'BS_AUTORADIOBUTTON', 'BS_3STATE', 'BS_AUTO3STATE',
    'SS_LEFT', 'SS_RIGHT', 'SS_CENTER', 'ES_LEFT', 'TBS_HORZ', 'TBS_BOTTOM', 'TCS_TABS',
    'DTS_SHORTDATEFORMAT', 'LVS_ICON', 'WS_OVERLAPPED',
}


# Different spellings of the same bits.
STYLE_SYNONYMS = {'TBS_LEFT': 'TBS_TOP', 'TBS_RIGHT': 'TBS_BOTTOM', 'DTS_TIMEFORMAT': 'DTS_UPDOWN'}


def significant_style(c):
    """Style flags worth comparing between locales (visibility is compared
    separately; bare numbers and implicit flags are dropped)."""
    out = set()
    for f in c.get('style') or []:
        f = STYLE_SYNONYMS.get(f, f)
        if f in IMPLICIT_STYLE_FLAGS or f == 'NOT WS_VISIBLE' or re.match(r'^-?\d+$', f):
            continue
        out.add(f)
    if c.get('kind') == 'ICON':
        out.add('SS_ICON')
    return sorted(out)


TEXT_ROLES = {'button', 'defbutton', 'check', 'radio', 'group', 'static'}


def is_translatable_control(c):
    """True when the control's caption is user-visible UI text."""
    if c.get('text') is None or control_role(c) not in TEXT_ROLES:
        return False
    if c.get('id') == 'IDC_HELPFILE':
        return False  # help file name, used by code
    if PLACEHOLDER_TEXT_RE.match(c['text'] or ''):
        return False
    return True


# ---------------------------------------------------------------------------
# Locale folders
# ---------------------------------------------------------------------------


def list_locales(root=None):
    root = root or LANG_ROOT
    out = []
    for name in sorted(os.listdir(root)):
        if os.path.isfile(os.path.join(root, name, 'descript.txt')):
            out.append(name)
    return out


def load_locale(name_or_dir, overrides=None):
    """Load one locale folder.

    *overrides* may map a file name (e.g. ``'resource.rc'``) to text, used to
    load an older revision from git instead of the working tree.
    """
    d = name_or_dir if os.path.isdir(name_or_dir) else os.path.join(LANG_ROOT, name_or_dir)
    name = os.path.basename(os.path.normpath(d))
    overrides = overrides or {}
    loc = {'name': name, 'dir': d, 'files': {}}

    def get(fname):
        if fname in overrides:
            if overrides[fname] is None:
                return None
            tf = TextFile(os.path.join(d, fname), overrides[fname].encode('utf-8'))
        else:
            p = os.path.join(d, fname)
            if not os.path.exists(p):
                return None
            tf = read_text(p)
        loc['files'][fname] = tf
        return tf

    for kvname in ('descript.txt', 'message.txt', 'surfacetable.txt', 'install.txt'):
        tf = get(kvname)
        loc[kvname] = parse_kv(tf.text) if tf else None
    tf = get('resource.rc')
    loc['rc_error'] = None
    loc['rc'] = None
    if tf:
        try:
            loc['rc'] = parse_rc(tf.text)
        except RcParseError as e:
            loc['rc_error'] = str(e)
    desc = kv_dict(loc['descript.txt'] or [])
    loc['langid'] = desc['id'].value.strip() if 'id' in desc else None
    loc['display_name'] = desc['name'].value.strip() if 'name' in desc else name
    return loc


# Windows LANGID -> BCP47, used for font selection in the viewer.
LANGID_TO_BCP47 = {
    '1033': 'en', '2057': 'en-GB', '2052': 'zh-Hans', '4100': 'zh-Hans', '1028': 'zh-Hant',
    '3076': 'zh-Hant', '5124': 'zh-Hant', '1041': 'ja', '1042': 'ko', '1036': 'fr', '1031': 'de',
    '1040': 'it', '3082': 'es', '1046': 'pt-BR', '2070': 'pt', '1049': 'ru', '1058': 'uk',
    '1045': 'pl', '1029': 'cs', '1038': 'hu', '1055': 'tr', '1032': 'el', '1037': 'he',
    '1025': 'ar', '1054': 'th', '1066': 'vi', '1057': 'id', '1086': 'ms', '1043': 'nl',
    '1053': 'sv', '1044': 'nb', '1030': 'da', '1035': 'fi',
}


def bcp47_for(loc):
    return LANGID_TO_BCP47.get(loc.get('langid') or '', 'und')
