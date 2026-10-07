#!/usr/bin/env python3
"""Lay out SSP dialogs like Windows does, find text that does not fit, and
render dialogs / menus to PNG. Needs Pillow; no browser.

Layout model (shared by --audit, --png and the HTML viewer):

* dialog units -> pixels from the font's base units, as Windows does:
  base_x = (width of "A..Za..z" + 26) // 52, base_y = tmHeight;
  x px = round(x * base_x / 4), y px = round(y * base_y / 8).
* text is measured with the locale's dialog font (see fontbook.FONT_STACKS),
  lines are tmHeight apart, static text wraps at spaces and between CJK
  characters (DT_WORDBREAK; a single word longer than the box is clipped).
* SSP widens static labels whose text does not fit: left-aligned ones grow to
  the right, right-aligned ones to the left, centred ones to both sides, to
  the single-line text width. A widened label is then checked for running
  into another control, out of its group box or out of the dialog.

The result is an approximation: 1-3 px findings are usually noise.
"""

import math
import unicodedata

import fontbook

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = ImageDraw = None


def jsround(v):
    return int(math.floor(v + 0.5))


def has(c, flag):
    return flag in (c.get('style') or [])


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def strip_mnemonic(text, noprefix=False):
    """Return (plain text, index of the underlined character or None)."""
    if not isinstance(text, str):  # None, or a resource number (ICON)
        return '', None
    if noprefix:
        return text, None
    out, ul, i = [], None, 0
    while i < len(text):
        ch = text[i]
        if ch == '&':
            if text[i + 1:i + 2] == '&':
                out.append('&')
                i += 2
                continue
            if i + 1 < len(text):
                if ul is None:
                    ul = len(out)
                out.append(text[i + 1])
                i += 2
                continue
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out), ul


# no line break before / after these (simple kinsoku)
NO_BREAK_BEFORE = set('、。，．,.：:；;！!？?）)］]｝}」』】〕〉》〗〙〛"\'’”ー…‥・々〻ゝゞヽヾ'
                      'ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ%％‰℃')
NO_BREAK_AFTER = set('（(［[｛{「『【〔〈《〖〘〚“‘')


def is_wide(ch):
    return unicodedata.east_asian_width(ch) in 'WF'


def pieces(line):
    """Split a line into unbreakable pieces (trailing spaces stay attached)."""
    out = []
    cur = ''
    for i, ch in enumerate(line):
        if cur:
            prev = line[i - 1]
            brk = False
            if prev == ' ' and ch != ' ':
                brk = True
            elif ch != ' ' and prev != ' ' and (is_wide(prev) or is_wide(ch)) \
                    and ch not in NO_BREAK_BEFORE and prev not in NO_BREAK_AFTER:
                brk = True
            if brk:
                out.append(cur)
                cur = ''
        cur += ch
    if cur:
        out.append(cur)
    return out


def wrap(font, text, width):
    """DT_WORDBREAK: return [(start offset, line text)]."""
    out = []
    pos = 0
    for hard in text.split('\n'):
        hard_line = hard.rstrip('\r')
        cur, cur_start, off = '', pos, pos
        for p in pieces(hard_line):
            if cur and font.width((cur + p).rstrip(' ')) > width:
                out.append((cur_start, cur.rstrip(' ')))
                cur, cur_start = '', off
            cur += p
            off += len(p)
        out.append((cur_start, cur.rstrip(' ')))
        pos += len(hard) + 1
    return out


def hard_lines(text):
    out, pos = [], 0
    for hard in text.split('\n'):
        out.append((pos, hard.rstrip('\r')))
        pos += len(hard) + 1
    return out


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

BOX = 13          # check box / radio button glyph
BOX_GAP = 4       # between glyph and text
BTN_PAD = 2       # horizontal padding inside push buttons
GROUP_INSET = 12  # group box caption: 6 px from each edge, plus 2 px padding on each side of the text


class Item:
    def __init__(self, c, rect):
        self.c = c
        self.role = c['role']
        self.rect = list(rect)   # l, t, w, h (after widening)
        self.orig = list(rect)
        self.widened = 0
        self.noprefix = has(c, 'SS_NOPREFIX')
        self.text, self.ul = strip_mnemonic(c.get('text'), self.noprefix)
        self.visible = c.get('visible', True)

    @property
    def pk(self):
        return self.c['pk']

    def ltrb(self, orig=False):
        l, t, w, h = self.orig if orig else self.rect
        return l, t, l + w, t + h

    @property
    def align(self):
        c = self.c
        if c['kind'] == 'RTEXT' or has(c, 'SS_RIGHT'):
            return 'right'
        if c['kind'] == 'CTEXT' or has(c, 'SS_CENTER'):
            return 'center'
        return 'left'

    @property
    def border(self):
        if self.role == 'defbutton':
            return 2
        if self.role == 'button' or (self.role == 'static' and has(self.c, 'SS_SUNKEN')):
            return 1
        return 0

    def single_line(self):
        c = self.c
        if self.role == 'static':
            return bool(self.widened) or has(c, 'SS_LEFTNOWORDWRAP') or has(c, 'SS_SIMPLE') or has(c, 'SS_CENTERIMAGE')
        if self.role in ('check', 'radio', 'button', 'defbutton'):
            return not has(c, 'BS_MULTILINE')
        return True

    def text_box(self):
        """(width, height) available to the text."""
        l, t, w, h = self.rect
        b = self.border
        if self.role in ('check', 'radio'):
            return w - BOX - BOX_GAP, h
        if self.role in ('button', 'defbutton'):
            return w - 2 * b - 2 * BTN_PAD, h - 2 * b
        if self.role == 'group':
            return w - 2 - GROUP_INSET - 2 * BTN_PAD, h
        return w - 2 * b, h - 2 * b

    def lines(self, font):
        tw, _ = self.text_box()
        return hard_lines(self.text) if self.single_line() else wrap(font, self.text, tw)

    def overflow(self, font):
        """Pixels by which the text does not fit (<= 0: fits)."""
        if not self.text.strip() or self.role not in ('static', 'check', 'radio', 'button', 'defbutton', 'group'):
            return 0
        if self.role in ('button', 'defbutton') and has(self.c, 'BS_ICON'):
            return 0
        tw, th = self.text_box()
        lines = self.lines(font)
        wmax = max(font.width(s) for _, s in lines)
        if self.role == 'group':
            return wmax - tw
        if self.role in ('check', 'radio', 'button', 'defbutton') and self.single_line():
            return wmax - tw
        return max(wmax - tw, len(lines) * font.height - th)


def overlaps(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


def inside(o, i):
    return i[0] >= o[0] - 1 and i[2] <= o[2] + 1 and i[1] >= o[1] - 1 and i[3] <= o[3] + 1


class Layout:
    def __init__(self, dlg, bcp47, auto_width=True, font_name=None):
        self.dlg = dlg
        size = (dlg.get('font') or {}).get('size') or 9
        self.px = jsround(size * 96 / 72)
        self.font = fontbook.font_for_locale(bcp47, self.px, font_name)
        self.bx, self.by = self.font.base_x, self.font.height
        self.w, self.h = self.X(dlg['w']), self.Y(dlg['h'])
        self.auto_width = auto_width
        self.items = []
        for c in dlg['controls']:
            h = self.Y(c['h'])
            if c['role'] == 'combo':
                h = min(h, self.Y(14))
            self.items.append(Item(c, (self.X(c['x']), self.Y(c['y']), self.X(c['w']), h)))
        if auto_width:
            self._auto_width()
        self.issues = self._check()

    def X(self, v):
        return jsround(v * self.bx / 4)

    def Y(self, v):
        return jsround(v * self.by / 8)

    @property
    def shown(self):
        return [it for it in self.items if it.visible]

    def _auto_width(self):
        f = self.font
        for it in self.shown:
            if it.role != 'static' or not it.text.strip():
                continue
            if it.overflow(f) <= 1:
                continue
            need = max(f.width(s) for _, s in hard_lines(it.text)) + 2 * it.border
            l, t, w, h = it.rect
            if need <= w:
                continue
            delta = need - w
            a = it.align
            left = l - (delta if a == 'right' else jsround(delta / 2) if a == 'center' else 0)
            it.rect = [left, t, need, h]
            it.widened = delta

    def _check(self):
        out = []
        f = self.font

        def add(it, kind, px, other=None):
            out.append({'pk': it.pk, 'id': it.c['id'], 'text': it.text, 'px': int(round(px)), 'kind': kind,
                        'other': other.c['id'] if other else None, 'otherPk': other.pk if other else None,
                        'widened': it.widened, 'line': it.c.get('line')})

        shown = self.shown
        for it in shown:
            over = it.overflow(f)
            if over > 1:
                add(it, 'clipped', over)
        done = set()
        for it in shown:
            if not it.widened:
                continue
            exp, orig = it.ltrb(), it.ltrb(orig=True)
            if exp[0] < -1 or exp[2] > self.w + 1:
                add(it, 'outside', -exp[0] if exp[0] < 0 else exp[2] - self.w)
                continue
            for other in shown:
                if other is it:
                    continue
                o_now, o_orig = other.ltrb(), other.ltrb(orig=True)
                if other.role == 'group':
                    if inside(o_orig, orig) and not inside(o_now, exp):
                        add(it, 'frame', max(o_now[0] - exp[0], exp[2] - o_now[2]), other)
                    continue
                if overlaps(exp, o_now) and not overlaps(orig, o_orig):
                    key = tuple(sorted((it.pk, other.pk)))
                    if key in done:
                        continue
                    done.add(key)
                    add(it, 'overlap', min(exp[2], o_now[2]) - max(exp[0], o_now[0]), other)
        return out

    def to_json(self):
        return {
            'font': self.font.family, 'fonts': self.font.requested, 'exact': self.font.exact,
            'px': self.px, 'bu': [self.bx, self.by], 'w': self.w, 'h': self.h,
            'ctl': dict((it.pk, {'r': it.rect, 'o': it.orig, 'wd': it.widened}) for it in self.items),
            'issues': self.issues,
        }


def issue_text(o):
    kind = o.get('kind') or 'clipped'
    s = {'clipped': 'CLIPPED ~%dpx', 'overlap': 'OVERLAP ~%dpx', 'outside': 'OUTSIDE-DIALOG ~%dpx',
         'frame': 'CROSSES-GROUPBOX ~%dpx'}.get(kind, kind.upper() + ' ~%dpx') % o['px']
    if o.get('other'):
        s += ' with ' + o['other']
    return s


# ---------------------------------------------------------------------------
# rendering (Pillow)
# ---------------------------------------------------------------------------

DLG_BG = (240, 240, 240)
BLACK = (0, 0, 0)
GRAY_TEXT = (141, 141, 141)
PAGE_BG = (246, 247, 249)
PANE_BG = (255, 255, 255)
PANE_LINE = (215, 219, 227)
MUTED = (103, 112, 133)
BAD = (212, 49, 61)
OK = (47, 143, 78)
WARN = (194, 122, 0)
ACCENT = (47, 111, 222)
HILITE = (255, 159, 26)


def _dashed_rect(d, box, color, width=1, dash=4):
    l, t, r, b = box
    for x in range(l, r + 1, dash * 2):
        d.line([(x, t), (min(x + dash - 1, r), t)], fill=color, width=width)
        d.line([(x, b), (min(x + dash - 1, r), b)], fill=color, width=width)
    for y in range(t, b + 1, dash * 2):
        d.line([(l, y), (l, min(y + dash - 1, b))], fill=color, width=width)
        d.line([(r, y), (r, min(y + dash - 1, b))], fill=color, width=width)


def draw_line(d, font, x, top, text, color, ul=None, tab=None):
    """Draw one line of text at (x, top); ``ul`` = index of the char to underline."""
    base = top + font.ascent
    pos = 0
    stop = tab or 8 * font.base_x
    x0 = x
    for k, part in enumerate(text.split('\t')):
        if k:
            x = x0 + ((x - x0) // stop + 1) * stop
            pos += 1
        for face, s in font.runs(part):
            pf = font.pil(face)
            if ul is not None and pos <= ul < pos + len(s):
                ux = x + pf.getlength(s[:ul - pos])
                uw = pf.getlength(s[ul - pos])
                d.line([(ux, base + 1), (ux + max(uw - 1, 1), base + 1)], fill=color)
            if s.strip():
                d.text((x, base), s, font=pf, fill=color, anchor='ls')
            x += font.run_width(face, s)
            pos += len(s)


def draw_text_box(img, box, font, lines, align='left', valign='top', color=BLACK, ul=None):
    """Draw lines clipped to box = (l, t, r, b)."""
    l, t, r, b = [int(v) for v in box]
    if r <= l or b <= t:
        return
    layer = Image.new('RGBA', (r - l, b - t), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    total = len(lines) * font.height
    y = 0 if valign == 'top' else (b - t - total) // 2
    for start, s in lines:
        w = font.width(s)
        x = 0 if align == 'left' else (r - l - w) if align == 'right' else (r - l - w) // 2
        u = ul - start if ul is not None and start <= ul < start + len(s) else None
        draw_line(d, font, x, y, s, color, u)
        y += font.height
    img.alpha_composite(layer, (l, t))


def render_dialog(lay, menubar=None, highlight=None, show_hidden=False, overlays=True):
    """Return an RGBA image of the dialog window."""
    dlg = lay.dlg
    style = dlg.get('style') or []
    ui = fontbook.ui_font(12)
    chrome = []
    if 'WS_CAPTION' in style and 'WS_CHILD' not in style:
        chrome.append(('title', 30))
    elif dlg.get('caption'):
        chrome.append(('pagecap', 18))
    if dlg.get('menu'):
        chrome.append(('menubar', 20))
    top = sum(h for _, h in chrome)
    W, H = lay.w + 2, lay.h + top + 2
    img = Image.new('RGBA', (W, H), DLG_BG + (255,))
    d = ImageDraw.Draw(img)
    y = 1
    for kind, h in chrome:
        if kind == 'title':
            d.rectangle([1, y, W - 2, y + h - 1], fill=(255, 255, 255))
            d.line([(1, y + h - 1), (W - 2, y + h - 1)], fill=(229, 229, 229))
            draw_text_box(img, (9, y, W - 48, y + h - 1), ui, [(0, dlg.get('caption') or '')], valign='middle')
            draw_text_box(img, (W - 47, y, W - 2, y + h - 1), ui, [(0, '✕')], align='center', valign='middle',
                          color=(51, 51, 51))
        elif kind == 'pagecap':
            d.rectangle([1, y, W - 2, y + h - 1], fill=(223, 230, 243))
            d.line([(1, y + h - 1), (W - 2, y + h - 1)], fill=(195, 203, 217))
            draw_text_box(img, (7, y, W - 2, y + h - 1), ui, [(0, dlg.get('caption') or '')], valign='middle')
        else:
            d.rectangle([1, y, W - 2, y + h - 1], fill=(255, 255, 255))
            d.line([(1, y + h - 1), (W - 2, y + h - 1)], fill=(229, 229, 229))
            x = 6
            for label in (menubar or [dlg.get('menu') or '']):
                txt, ul = strip_mnemonic(label)
                draw_text_box(img, (x, y, W - 2, y + h - 1), ui, [(0, txt)], valign='middle', ul=ul)
                x += ui.width(txt) + 18
        y += h
    d.rectangle([0, 0, W - 1, H - 1], outline=(111, 111, 111))
    client = Image.new('RGBA', (lay.w, lay.h), DLG_BG + (255,))
    _draw_controls(client, lay, show_hidden)
    if overlays:
        _draw_overlays(client, lay, highlight)
    img.alpha_composite(client, (1, top + 1))
    return img


def _draw_controls(img, lay, show_hidden):
    d = ImageDraw.Draw(img)
    f = lay.font
    for it in lay.items:
        if not it.visible and not show_hidden:
            continue
        c, role = it.c, it.role
        l, t, r, b = it.ltrb()
        r -= 1
        b -= 1
        if r < l or b < t:
            continue
        color = GRAY_TEXT if c.get('disabled') else BLACK
        if not it.visible:
            _dashed_rect(d, (l, t, r, b), (119, 119, 119))
        if role == 'static':
            if has(c, 'SS_SUNKEN'):
                d.line([(l, b), (l, t), (r, t)], fill=(160, 160, 160))
                d.line([(r, t), (r, b), (l, b)], fill=(255, 255, 255))
            bd = it.border
            valign = 'middle' if has(c, 'SS_CENTERIMAGE') else 'top'
            draw_text_box(img, (l + bd, t + bd, r + 1 - bd, b + 1 - bd), f, it.lines(f), it.align, valign, color, it.ul)
        elif role in ('button', 'defbutton'):
            d.rectangle([l, t, r, b], fill=(225, 225, 225), outline=(173, 173, 173))
            if role == 'defbutton':
                d.rectangle([l, t, r, b], outline=(0, 120, 215), width=2)
            if has(c, 'BS_ICON'):
                draw_text_box(img, (l, t, r + 1, b + 1), f, [(0, '◆')], 'center', 'middle', color)
            else:
                bd = it.border
                draw_text_box(img, (l + bd + BTN_PAD, t + bd, r + 1 - bd - BTN_PAD, b + 1 - bd), f, it.lines(f),
                              'center', 'middle', color, it.ul)
        elif role in ('check', 'radio'):
            left_text = has(c, 'BS_LEFTTEXT') or has(c, 'BS_RIGHTBUTTON')
            by = t + (b - t + 1 - BOX) // 2
            bx = r + 1 - BOX if left_text else l
            if role == 'radio':
                d.ellipse([bx, by, bx + BOX - 1, by + BOX - 1], fill=(255, 255, 255), outline=(51, 51, 51))
            else:
                d.rectangle([bx, by, bx + BOX - 1, by + BOX - 1], fill=(255, 255, 255), outline=(51, 51, 51))
            tl = l if left_text else l + BOX + BOX_GAP
            draw_text_box(img, (tl, t, tl + it.text_box()[0], b + 1), f, it.lines(f), 'left', 'middle', color, it.ul)
        elif role == 'group':
            gy = t + f.height // 2
            d.rectangle([l, gy, r, b], outline=(220, 220, 220))
            if it.text:
                tw = min(f.width(it.text), it.text_box()[0])
                d.rectangle([l + 6, t, l + 6 + tw + 2 * BTN_PAD, t + f.height], fill=DLG_BG)
                draw_text_box(img, (l + 6 + BTN_PAD, t, l + 6 + BTN_PAD + it.text_box()[0], t + f.height), f,
                              [(0, it.text)], color=color, ul=it.ul)
        elif role in ('edit', 'combo', 'listbox', 'listview', 'datetime'):
            d.rectangle([l, t, r, b], fill=(255, 255, 255), outline=(122, 122, 122))
            if role == 'listview' and has(c, 'LVS_REPORT') and not has(c, 'LVS_NOCOLUMNHEADER'):
                d.line([(l + 1, t + 18), (r - 1, t + 18)], fill=(229, 229, 229))
            if role == 'combo' or (role == 'datetime' and not has(c, 'DTS_UPDOWN')):
                cx, cy = r - 7, (t + b) // 2
                d.polygon([(cx - 3, cy - 1), (cx + 3, cy - 1), (cx, cy + 2)], fill=(51, 51, 51))
            if role == 'datetime':
                timefmt = has(c, 'DTS_TIMEFORMAT') or '8' in (c.get('style') or [])
                draw_text_box(img, (l + 3, t, r - 12, b + 1), f, [(0, '12:34:56' if timefmt else '2026/10/07')],
                              'left', 'middle', (85, 85, 85))
        elif role == 'trackbar':
            cy = (t + b) // 2
            d.rectangle([l + 6, cy - 2, r - 6, cy + 1], fill=(218, 218, 218), outline=(181, 181, 181))
            tx = l + (r - l) * 3 // 10
            d.rectangle([tx, cy - 7, tx + 7, cy + 7], fill=(0, 120, 215))
        elif role == 'updown':
            d.rectangle([l, t, r, b], fill=(225, 225, 225), outline=(173, 173, 173))
            m = (t + b) // 2
            d.line([(l, m), (r, m)], fill=(173, 173, 173))
        elif role == 'progress':
            d.rectangle([l, t, r, b], fill=(230, 230, 230), outline=(188, 188, 188))
            d.rectangle([l + 1, t + 1, l + (r - l) * 2 // 5, b - 1], fill=(6, 176, 37))
        elif role == 'tab':
            d.line([(l, b), (r, b)], fill=(217, 217, 217))
            d.rectangle([l, t, min(r, l + 40), t + f.height + 2], fill=(255, 255, 255), outline=(217, 217, 217))
            draw_text_box(img, (l + 8, t + 1, min(r, l + 40), t + f.height + 2), f, [(0, 'Tab')])
        elif role == 'icon':
            _dashed_rect(d, (l, t, r, b), (138, 138, 138), dash=2)
        elif role == 'frame':
            d.rectangle([l, t, r, b], outline=BLACK)


def _draw_overlays(img, lay, highlight):
    d = ImageDraw.Draw(img)
    bad = set(o['pk'] for o in lay.issues)
    collide = set(o['otherPk'] for o in lay.issues if o.get('otherPk'))
    tint = Image.new('RGBA', img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(tint)
    for it in lay.shown:
        if it.widened:
            l, t, r, b = it.ltrb()
            td.rectangle([l, t, r - 1, b - 1], fill=ACCENT + (24,))
    img.alpha_composite(tint)
    for it in lay.shown:
        l, t, r, b = it.ltrb()
        if it.widened:
            ol, ot, orr, ob = it.ltrb(orig=True)
            _dashed_rect(d, (ol, ot, orr - 1, ob - 1), ACCENT)
        if it.pk in collide:
            _dashed_rect(d, (l - 1, t - 1, r, b), WARN, width=2)
        if it.pk in bad:
            d.rectangle([l - 1, t - 1, r, b], outline=BAD, width=2)
        if highlight and highlight in (it.pk, it.c['id']):
            d.rectangle([l - 3, t - 3, r + 2, b + 2], outline=HILITE, width=2)


def render_menu(items, bcp47, highlight=None):
    """Return an RGBA image of a menu (popups expanded below their item)."""
    f = fontbook.menu_font(bcp47, 12)
    small = fontbook.ui_font(10)
    rows = []

    def walk(its, depth):
        for it in its:
            if it['kind'] == 'separator':
                rows.append(('sep', depth, None))
            else:
                rows.append(('item', depth, it))
                if it['kind'] == 'popup':
                    walk(it.get('items') or [], depth + 1)
    walk(items, 0)
    rh = f.height + 8
    widths = []
    for kind, depth, it in rows:
        if kind == 'item':
            parts = (it.get('text') or '').split('\t')
            label = strip_mnemonic(parts[0])[0]
            w = depth * 20 + 28 + f.width(label) + 24
            if len(parts) > 1:
                w += f.width(parts[1]) + 24
            if it.get('id'):
                w += small.width(it['id']) + 8
            widths.append(w + 18)
    W = max([200] + widths)
    H = sum(rh if k == 'item' else 7 for k, _, _ in rows) + 6
    img = Image.new('RGBA', (W, H), (242, 242, 242, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=(204, 204, 204))
    y = 3
    for kind, depth, it in rows:
        x = depth * 20
        if kind == 'sep':
            d.line([(x + 28, y + 3), (W - 3, y + 3)], fill=(204, 204, 204))
            y += 7
            continue
        if highlight and it.get('id') == highlight:
            d.rectangle([x + 1, y, W - 2, y + rh - 1], fill=(255, 226, 184))
        parts = (it.get('text') or '').split('\t')
        label, ul = strip_mnemonic(parts[0])
        draw_text_box(img, (x + 28, y, W - 2, y + rh), f, [(0, label)], valign='middle', ul=ul)
        rx = W - 18
        if it.get('id'):
            iw = small.width(it['id'])
            draw_text_box(img, (rx - iw, y, rx, y + rh), small, [(0, it['id'])], valign='middle', color=(136, 136, 136))
            rx -= iw + 8
        if len(parts) > 1:
            sw = f.width(parts[1])
            draw_text_box(img, (rx - sw, y, rx, y + rh), f, [(0, parts[1])], valign='middle', color=(68, 68, 68))
        if it['kind'] == 'popup':
            draw_text_box(img, (W - 14, y, W - 2, y + rh), f, [(0, '›')], valign='middle')
        y += rh
    return img


def pane(body, title, sub=None, badge=None):
    """Wrap an image in a titled pane like the HTML viewer."""
    ui = fontbook.ui_font(12)
    small = fontbook.ui_font(11)
    head = ui.height + 8
    tw = 8 + ui.width(title) + 8 + (small.width(sub) + 8 if sub else 0) + (small.width(badge[0]) + 20 if badge else 0)
    W = max(body.width + 16, tw + 8)
    H = body.height + head + 12
    img = Image.new('RGBA', (W, H), PANE_BG + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=PANE_LINE)
    x = 8
    draw_text_box(img, (x, 4, W, 4 + ui.height), ui, [(0, title)])
    x += ui.width(title) + 8
    if sub:
        draw_text_box(img, (x, 5, W, 5 + small.height), small, [(0, sub)], color=MUTED)
        x += small.width(sub) + 8
    if badge:
        text, color = badge
        bw = small.width(text) + 14
        d.rounded_rectangle([x, 4, x + bw, 4 + small.height + 2], radius=8, fill=color)
        draw_text_box(img, (x, 5, x + bw, 5 + small.height + 2), small, [(0, text)], align='center',
                      color=(255, 255, 255))
    img.alpha_composite(body, (8, head + 4))
    return img


def compose(panes, max_width=1700, gap=16):
    """Flow panes left to right, wrapping at max_width."""
    rows, cur, cw = [], [], 0
    for p in panes:
        if cur and cw + gap + p.width > max_width:
            rows.append(cur)
            cur, cw = [], 0
        cur.append(p)
        cw += (gap if cw else 0) + p.width
    if cur:
        rows.append(cur)
    W = max(sum(p.width for p in r) + gap * (len(r) - 1) for r in rows) + 2 * gap
    H = sum(max(p.height for p in r) for r in rows) + gap * (len(rows) + 1)
    img = Image.new('RGBA', (W, H), PAGE_BG + (255,))
    y = gap
    for r in rows:
        x = gap
        for p in r:
            img.alpha_composite(p, (x, y))
            x += p.width + gap
        y += max(p.height for p in r) + gap
    return img


def save_png(img, path, scale=1):
    if scale and scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.NEAREST)
    img.convert('RGB').save(path)
