#!/usr/bin/env python3
"""Generate the localized ssp-pictures/ images from the english ones.

    python tools/make_pictures.py                    # all locales below, written into languages/<locale>/ssp-pictures/
    python tools/make_pictures.py korean             # one locale
    python tools/make_pictures.py --out /tmp/pics    # write to /tmp/pics/<locale>/ instead (preview)

Each image is the english one with its text area cleared and the localized text
drawn at the same place (right-aligned, wide letter spacing like english):

    realize[_dark].png     500x260  title above the rule at y=238, subtitle below it
    nowloading[_dark].png  261x48   "Wait..." above the rule at y=27

Needs Pillow. Fonts are looked up by name with fontbook.py; the first installed
one of each stack is used. The Windows fonts come first because the committed
images were made with them; the others are look-alikes for Linux/macOS, so the
result there differs slightly. Look at the images before committing them.

To add a locale, add an entry to LOCALES.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fontbook  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit('Pillow is required: pip install -r tools/requirements.txt')

REPO_ROOT = os.path.dirname(HERE)
LANG_DIR = os.path.join(REPO_ROOT, 'languages')
SRC = os.path.join(LANG_DIR, 'english', 'ssp-pictures')

# light: realize title; regular: realize subtitle and nowloading text.
STACKS = {
    'zh-Hans': {
        'light': ['Microsoft YaHei Light', 'Noto Sans CJK SC Light', 'Noto Sans SC Light',
                  'Source Han Sans SC Light', 'PingFang SC Light'],
        'regular': ['Microsoft YaHei', 'Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC',
                    'PingFang SC', 'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei'],
    },
    'zh-Hant': {
        'light': ['Microsoft JhengHei Light', 'Noto Sans CJK TC Light', 'Noto Sans TC Light',
                  'Source Han Sans TC Light', 'PingFang TC Light'],
        'regular': ['Microsoft JhengHei', 'Noto Sans CJK TC', 'Noto Sans TC', 'Source Han Sans TC',
                    'PingFang TC', 'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei'],
    },
    'ko': {
        'light': ['Malgun Gothic Semilight', 'Noto Sans CJK KR Light', 'Noto Sans KR Light',
                  'Source Han Sans KR Light', 'Apple SD Gothic Neo Light', 'NanumGothic Light'],
        'regular': ['Malgun Gothic', 'Noto Sans CJK KR', 'Noto Sans KR', 'Source Han Sans KR',
                    'Apple SD Gothic Neo', 'NanumGothic', 'UnDotum'],
    },
}

LOCALES = {
    'chinese-simplified': dict(lang='zh-Hans', title='统计', subtitle='使用率图表', wait='请稍候...'),
    'chinese-traditional': dict(lang='zh-Hant', title='統計', subtitle='使用率圖表', wait='請稍候...'),
    'korean': dict(lang='ko', title='통계', subtitle='사용률 그래프', wait='잠시만요...'),
}


def _faces_named(name):
    key = name.lower()
    seen, res = set(), []
    for face in fontbook.font_index().values():
        if id(face) not in seen and key in face.names:
            seen.add(id(face))
            res.append(face)
    return res


def find_font(names, text, light):
    """First installed face of *names* that has every glyph of *text*.

    A family name is shared by all weights of a family; for the regular weight
    the face with the fewest names (no "<family> Bold" etc.) is taken."""
    for name in names:
        faces = [f for f in _faces_named(name) if all(f.has(ord(c)) for c in text)]
        if not faces:
            continue
        if light:
            return faces[0], name
        return min(faces, key=lambda f: (len(f.names), f.path, f.index)), name
    return None, None


def load_font(lang, weight, text, px):
    names = STACKS[lang][weight]
    if weight == 'light':
        names = names + STACKS[lang]['regular']  # no light face: regular is close enough
    face, name = find_font(names, text, weight == 'light')
    if face is None:
        sys.exit('no font for %s (%s); install one of: %s' % (lang, weight, ', '.join(STACKS[lang][weight])))
    return ImageFont.truetype(face.path, px, index=face.index), name


def text_mask(text, font, tracking):
    """Render *text* with *tracking* extra pixels after each glyph; ink-cropped L mask."""
    m = Image.new('L', (2000, 200), 0)
    d = ImageDraw.Draw(m)
    x = 10
    for ch in text:
        d.text((x, 50), ch, font=font, fill=255)
        x += font.getlength(ch) + tracking
    return m.crop(m.getbbox())


def place(img, mask, right, bottom, ink):
    """Draw *mask* in colour *ink* so that its ink box ends at (right, bottom) inclusive."""
    w, h = mask.size
    full = Image.new('L', img.size, 0)
    full.paste(mask, (right - w + 1, bottom - h + 1))
    img.paste(Image.new('L', img.size, ink), (0, 0), full)


def build(cfg, out_dir):
    lang = cfg['lang']
    title_font, n1 = load_font(lang, 'light', cfg['title'], 22)
    sub_font, n2 = load_font(lang, 'regular', cfg['subtitle'], 12)
    wait_font, n3 = load_font(lang, 'regular', cfg['wait'], 18)
    os.makedirs(out_dir, exist_ok=True)
    for dark in (False, True):
        sfx = '_dark' if dark else ''
        bg, ink = (0, 255) if dark else (255, 0)

        im = Image.open(os.path.join(SRC, 'realize%s.png' % sfx)).convert('L')
        d = ImageDraw.Draw(im)
        d.rectangle((90, 205, 499, 237), fill=bg)
        d.rectangle((90, 239, 499, 259), fill=bg)
        place(im, text_mask(cfg['title'], title_font, 14), 495, 232, ink)
        place(im, text_mask(cfg['subtitle'], sub_font, 9), 493, 255, ink)
        im.save(os.path.join(out_dir, 'realize%s.png' % sfx), optimize=True)

        im = Image.open(os.path.join(SRC, 'nowloading%s.png' % sfx)).convert('L')
        d = ImageDraw.Draw(im)
        d.rectangle((90, 0, 260, 26), fill=bg)
        place(im, text_mask(cfg['wait'], wait_font, 0), 255, 23, ink)
        im.save(os.path.join(out_dir, 'nowloading%s.png' % sfx), optimize=True)
    return sorted({n1, n2, n3})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('locales', nargs='*', help='default: %s' % ' '.join(LOCALES))
    p.add_argument('--out', help='output root (default: languages/<locale>/ssp-pictures)')
    args = p.parse_args(argv)
    for loc in args.locales or LOCALES:
        if loc not in LOCALES:
            sys.exit('unknown locale %r (known: %s)' % (loc, ', '.join(LOCALES)))
        out = os.path.join(args.out, loc) if args.out else os.path.join(LANG_DIR, loc, 'ssp-pictures')
        fonts = build(LOCALES[loc], out)
        print('%-22s %s  (%s)' % (loc, os.path.relpath(out, REPO_ROOT), ', '.join(fonts)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
