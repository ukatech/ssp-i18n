#!/usr/bin/env python3
"""Find installed fonts by family name and measure text like Windows GDI.

Used by dlglayout.py. Needs Pillow (FreeType) for glyph advances; the font
tables that GDI uses for line metrics (OS/2, VDMX) and glyph coverage (cmap)
are read directly with ``struct``.

Measured against GDI on Windows 11: advances of SimSun / MS UI Gothic match
exactly at 12 px, Latin UI fonts within a pixel or two per word; tmHeight
matches when computed from VDMX (or rounded OS/2 win metrics).
"""

import bisect
import json
import os
import struct
import sys
import unicodedata

try:
    from PIL import ImageFont
except ImportError:  # pragma: no cover - reported by callers
    ImageFont = None

FONT_EXTS = ('.ttf', '.ttc', '.otf', '.otc')

# Font stacks per locale (BCP 47), first installed one wins. The first entries
# are what "MS Shell Dlg" maps to on that Windows language; the rest are
# look-alikes for other systems. FALLBACK is used for glyphs none of them has.
FONT_STACKS = {
    'en': ['Microsoft Sans Serif', 'Tahoma', 'Liberation Sans', 'Arial', 'Helvetica', 'DejaVu Sans'],
    'zh-Hans': ['SimSun', 'NSimSun', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Noto Sans SC',
                'Source Han Sans SC', 'WenQuanYi Zen Hei', 'PingFang SC'],
    'zh-Hant': ['PMingLiU', 'MingLiU', 'Microsoft JhengHei', 'Noto Sans CJK TC', 'Noto Sans TC',
                'Source Han Sans TC', 'WenQuanYi Zen Hei', 'PingFang TC'],
    'ja': ['MS UI Gothic', 'Meiryo UI', 'Yu Gothic UI', 'Noto Sans CJK JP', 'Noto Sans JP',
           'Source Han Sans JP', 'Hiragino Sans'],
    'ko': ['Gulim', 'Malgun Gothic', 'Noto Sans CJK KR', 'Noto Sans KR', 'Source Han Sans KR',
           'Apple SD Gothic Neo'],
}
FALLBACK = ['Microsoft Sans Serif', 'Tahoma', 'Arial', 'DejaVu Sans', 'Liberation Sans',
            'MS UI Gothic', 'SimSun', 'Microsoft YaHei', 'Microsoft JhengHei', 'Malgun Gothic', 'Yu Gothic UI',
            'Noto Sans CJK JP', 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'Segoe UI Symbol', 'Arial Unicode MS',
            'Noto Sans Symbols', 'DejaVu Sans Mono']
UI_STACK = ['Segoe UI', 'Noto Sans', 'DejaVu Sans', 'Liberation Sans', 'Arial', 'Helvetica']
# Menu font (SPI_GETNONCLIENTMETRICS lfMenuFont) per Windows language.
MENU_STACKS = {
    'en': UI_STACK,
    'zh-Hans': ['Microsoft YaHei UI', 'Microsoft YaHei'] + FONT_STACKS['zh-Hans'],
    'zh-Hant': ['Microsoft JhengHei UI', 'Microsoft JhengHei'] + FONT_STACKS['zh-Hant'],
    'ja': ['Yu Gothic UI', 'Meiryo UI'] + FONT_STACKS['ja'],
    'ko': ['Malgun Gothic'] + FONT_STACKS['ko'],
}


def stack_for(bcp47, stacks=FONT_STACKS):
    tag = bcp47 or 'en'
    return stacks.get(tag) or stacks.get(tag.split('-')[0]) or stacks['en']


def font_dirs():
    dirs = []
    if sys.platform == 'win32':
        dirs.append(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'))
        if os.environ.get('LOCALAPPDATA'):
            dirs.append(os.path.join(os.environ['LOCALAPPDATA'], 'Microsoft', 'Windows', 'Fonts'))
    elif sys.platform == 'darwin':
        dirs += ['/System/Library/Fonts', '/Library/Fonts', os.path.expanduser('~/Library/Fonts')]
    else:
        dirs += ['/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.fonts'),
                 os.path.expanduser('~/.local/share/fonts')]
    extra = os.environ.get('RCVIEW_FONT_DIRS')
    if extra:
        dirs = extra.split(os.pathsep) + dirs
    return [d for d in dirs if os.path.isdir(d)]


# ---------------------------------------------------------------------------
# sfnt tables
# ---------------------------------------------------------------------------


def _faces(f):
    """Offsets of the font faces in an sfnt/TTC file."""
    f.seek(0)
    head = f.read(12)
    if head[:4] == b'ttcf':
        n = struct.unpack('>I', head[8:12])[0]
        return list(struct.unpack('>%dI' % n, f.read(4 * n)))
    return [0]


def _table_dir(f, off):
    f.seek(off)
    hdr = f.read(12)
    n = struct.unpack('>H', hdr[4:6])[0]
    raw = f.read(16 * n)
    t = {}
    for i in range(n):
        tag, _, o, ln = struct.unpack('>4sIII', raw[16 * i:16 * i + 16])
        t[tag.decode('latin-1')] = (o, ln)
    return t


def _read(f, tables, tag):
    if tag not in tables:
        return None
    o, ln = tables[tag]
    f.seek(o)
    return f.read(ln)


def _names(data):
    """Family / full names (lower case) from a 'name' table."""
    out = set()
    if not data or len(data) < 6:
        return out
    _, count, soff = struct.unpack('>HHH', data[:6])
    for i in range(count):
        rec = data[6 + 12 * i:18 + 12 * i]
        if len(rec) < 12:
            break
        pid, eid, lid, nid, ln, o = struct.unpack('>HHHHHH', rec)
        if nid not in (1, 4, 16):
            continue
        raw = data[soff + o:soff + o + ln]
        try:
            if pid in (0, 3):
                s = raw.decode('utf-16-be')
            elif pid == 1 and eid == 0:
                s = raw.decode('mac_roman')
            else:
                continue
        except UnicodeDecodeError:
            continue
        out.add(s.strip().lower())
    return out


def _cmap_ranges(data):
    """Return sorted (start, end) code point ranges that map to a real glyph."""
    if not data:
        return []
    n = struct.unpack('>H', data[2:4])[0]
    subs = {}
    for i in range(n):
        pid, eid, o = struct.unpack('>HHI', data[4 + 8 * i:12 + 8 * i])
        subs[(pid, eid)] = o
    for key in ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0), (3, 0)):
        if key not in subs:
            continue
        o = subs[key]
        fmt = struct.unpack('>H', data[o:o + 2])[0]
        if fmt == 12:
            ngroups = struct.unpack('>I', data[o + 12:o + 16])[0]
            out = []
            for g in range(ngroups):
                s, e, gid = struct.unpack('>III', data[o + 16 + 12 * g:o + 28 + 12 * g])
                if gid == 0:
                    s += 1
                if s <= e:
                    out.append((s, e))
            return out
        if fmt == 4:
            segx2 = struct.unpack('>H', data[o + 6:o + 8])[0]
            seg = segx2 // 2
            ends = struct.unpack('>%dH' % seg, data[o + 14:o + 14 + segx2])
            starts = struct.unpack('>%dH' % seg, data[o + 16 + segx2:o + 16 + 2 * segx2])
            deltas = struct.unpack('>%dh' % seg, data[o + 16 + 2 * segx2:o + 16 + 3 * segx2])
            ro_pos = o + 16 + 3 * segx2
            ros = struct.unpack('>%dH' % seg, data[ro_pos:ro_pos + segx2])
            out = []
            for i in range(seg):
                s, e = starts[i], ends[i]
                if s == 0xFFFF:
                    continue
                if ros[i] == 0:
                    # glyph = (c + delta) & 0xFFFF; only one c can map to 0
                    zero = (-deltas[i]) & 0xFFFF
                    if s <= zero <= e:
                        if s < zero:
                            out.append((s, zero - 1))
                        if zero < e:
                            out.append((zero + 1, e))
                    else:
                        out.append((s, e))
                    continue
                run = None
                for c in range(s, e + 1):
                    p = ro_pos + 2 * i + ros[i] + 2 * (c - s)
                    gid = struct.unpack('>H', data[p:p + 2])[0] if p + 2 <= len(data) else 0
                    if gid:
                        run = [c, c] if run is None or run[1] != c - 1 else [run[0], c]
                        if out and out[-1][0] == run[0]:
                            out[-1] = tuple(run)
                        else:
                            out.append(tuple(run))
            return sorted(out)
    return []


def _vdmx(data, ppem):
    """(ascent, descent) for ppem from a VDMX table, 1:1 aspect ratio."""
    if not data or len(data) < 6:
        return None
    _, _, nratios = struct.unpack('>HHH', data[:6])
    for i in range(nratios):
        _, x, ys, ye = struct.unpack('>BBBB', data[6 + 4 * i:10 + 4 * i])
        if x == 0 or ys <= x <= ye:
            o = struct.unpack('>H', data[6 + 4 * nratios + 2 * i:8 + 4 * nratios + 2 * i])[0]
            recs = struct.unpack('>H', data[o:o + 2])[0]
            for r in range(recs):
                h, ymax, ymin = struct.unpack('>Hhh', data[o + 4 + 6 * r:o + 10 + 6 * r])
                if h == ppem:
                    return ymax, -ymin
            return None
    return None


# ---------------------------------------------------------------------------
# font index
# ---------------------------------------------------------------------------


class FontFace:
    def __init__(self, path, index, names):
        self.path, self.index, self.names = path, index, names
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        with open(self.path, 'rb') as f:
            off = _faces(f)[self.index]
            t = _table_dir(f, off)
            self.ranges = _cmap_ranges(_read(f, t, 'cmap'))
            self._starts = [r[0] for r in self.ranges]
            head = _read(f, t, 'head')
            self.upem = struct.unpack('>H', head[18:20])[0] if head else 1000
            os2 = _read(f, t, 'OS/2')
            hhea = _read(f, t, 'hhea')
            if os2 and len(os2) >= 78:
                self.win = struct.unpack('>HH', os2[74:78])
            elif hhea:
                a, d = struct.unpack('>hh', hhea[4:8])
                self.win = (a, -d)
            else:
                self.win = (int(self.upem * 0.9), int(self.upem * 0.25))
            self.vdmx_data = _read(f, t, 'VDMX')

    def has(self, cp):
        self._load()
        i = bisect.bisect_right(self._starts, cp) - 1
        return i >= 0 and self.ranges[i][0] <= cp <= self.ranges[i][1]

    def line_metrics(self, ppem):
        """GDI tmAscent, tmDescent."""
        self._load()
        v = _vdmx(self.vdmx_data, ppem)
        if v:
            return v
        s = ppem / self.upem
        return int(self.win[0] * s + 0.5), int(self.win[1] * s + 0.5)

    @property
    def family(self):
        return sorted(self.names, key=len)[0] if self.names else os.path.basename(self.path)


_INDEX = None
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.rcview', 'fonts.json')


def _scan_file(path):
    faces = []
    with open(path, 'rb') as f:
        for off in _faces(f):
            faces.append(sorted(_names(_read(f, _table_dir(f, off), 'name'))))
    return faces


def font_index():
    """name (lower case) -> FontFace, for every installed font.

    Reading the name tables of a full Windows font folder takes seconds, so the
    result is cached in .rcview/fonts.json (re-read only for changed files)."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    try:
        with open(CACHE_PATH, encoding='utf-8') as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    new_cache, dirty = {}, False
    _INDEX = {}
    for d in font_dirs():
        for root, _, files in os.walk(d):
            for fn in sorted(files):
                if not fn.lower().endswith(FONT_EXTS):
                    continue
                path = os.path.join(root, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                stamp = [st.st_size, int(st.st_mtime)]
                hit = cache.get(path)
                if hit and hit[0] == stamp:
                    faces = hit[1]
                else:
                    dirty = True
                    try:
                        faces = _scan_file(path)
                    except (OSError, struct.error, IndexError, ValueError):
                        faces = []
                new_cache[path] = [stamp, faces]
                for i, names in enumerate(faces):
                    face = FontFace(path, i, set(names))
                    for n in names:
                        _INDEX.setdefault(n, face)
    if dirty or len(new_cache) != len(cache):
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(new_cache, f)
        except OSError:
            pass
    return _INDEX


def find_face(name):
    return font_index().get(name.lower())


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------


MISSING = object()  # face_for(): no installed font has the glyph


class Font:
    """A font at a pixel size (= GDI lfHeight < 0) with glyph fallback."""

    def __init__(self, names, px, fallback=FALLBACK):
        if ImageFont is None:
            raise RuntimeError('Pillow is required: pip install pillow')
        self.px = px
        self.faces = []
        seen = set()
        for n in list(names) + list(fallback):
            face = find_face(n)
            if face and (face.path, face.index) not in seen:
                seen.add((face.path, face.index))
                self.faces.append(face)
        self.requested = list(names)
        self._pil = {}
        self._cache = {}
        self._pick = {}
        if self.faces:
            self.primary = self.faces[0]
            self.family = next((n for n in names if find_face(n) is self.primary), self.primary.family)
            self.ascent, self.descent = self.primary.line_metrics(px)
        else:  # no system fonts at all: Pillow's bundled font
            self.primary = None
            self.family = '(Pillow default)'
            self.ascent, self.descent = int(px * 0.9 + 0.5), int(px * 0.25 + 0.5)
        self.height = self.ascent + self.descent
        az = self.width('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')
        self.avg = az / 52.0
        # GdiGetCharDimensions: (width + 26) / 52, integer division
        self.base_x = int((az + 26) // 52)

    @property
    def exact(self):
        """True when the first requested font (the one Windows uses) is installed."""
        return self.primary is not None and find_face(self.requested[0]) is self.primary

    def pil(self, face):
        if face is MISSING:
            face = self.primary
        key = (face.path, face.index) if face else None
        f = self._pil.get(key)
        if f is None:
            if face is None:
                try:
                    f = ImageFont.load_default(self.px)
                except TypeError:
                    f = ImageFont.load_default()
            else:
                f = ImageFont.truetype(face.path, self.px, index=face.index,
                                       layout_engine=ImageFont.Layout.BASIC)
            self._pil[key] = f
        return f

    def face_for(self, ch):
        """The first face that has a glyph for ch, or MISSING."""
        f = self._pick.get(ch)
        if f is None:
            cp = ord(ch)
            f = next((x for x in self.faces if x.has(cp)), MISSING)
            self._pick[ch] = f
        return f

    def run_width(self, face, s):
        """Advance of a run from runs() (float px)."""
        if face is MISSING:
            # no installed font has these glyphs: full width for CJK, else the primary's .notdef
            return sum(self.px if unicodedata.east_asian_width(ch) in 'WF' else self.pil(self.primary).getlength(ch)
                       for ch in s)
        return self.pil(face).getlength(s)

    @property
    def missing(self):
        """Characters measured so far that no installed font has."""
        # Pillow's bundled font (no system fonts at all) has no cmap here but covers Latin
        return sorted(ch for ch, f in self._pick.items() if f is MISSING and not ch.isspace()
                      and (self.primary is not None or unicodedata.east_asian_width(ch) in 'WF'))

    def runs(self, text):
        """Split text into (face, substring) runs of a single face."""
        out = []
        for ch in text:
            face = self.face_for(ch)
            if out and out[-1][0] is face:
                out[-1][1].append(ch)
            else:
                out.append((face, [ch]))
        return [(f, ''.join(cs)) for f, cs in out]

    def width(self, text, tab=None):
        """Advance width in pixels (one line). Tabs expand to ``tab`` px stops."""
        if not text:
            return 0
        w = self._cache.get((text, tab))
        if w is not None:
            return w
        if '\t' in text:
            stop = tab or 8 * max(1, getattr(self, 'base_x', 6))
            x = 0
            for i, part in enumerate(text.split('\t')):
                if i:
                    x = (x // stop + 1) * stop
                x += self.width(part)
            w = x
        else:
            w = int(round(sum(self.run_width(face, s) for face, s in self.runs(text))))
        self._cache[(text, tab)] = w
        return w


_FONTS = {}


def font_for_locale(bcp47, px, override=None):
    names = [override] if override else stack_for(bcp47)
    key = (tuple(names), px)
    if key not in _FONTS:
        _FONTS[key] = Font(names, px)
    return _FONTS[key]


def ui_font(px):
    key = (tuple(UI_STACK), px)
    if key not in _FONTS:
        _FONTS[key] = Font(UI_STACK, px)
    return _FONTS[key]


def menu_font(bcp47, px):
    names = stack_for(bcp47, MENU_STACKS)
    key = (tuple(names), px)
    if key not in _FONTS:
        _FONTS[key] = Font(names, px)
    return _FONTS[key]
