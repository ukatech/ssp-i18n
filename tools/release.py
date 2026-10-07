#!/usr/bin/env python3
"""Network-update files and release packages for the SSP language packs.

Cross-platform replacement for what CI does (Python 3 stdlib only):

    python tools/release.py updates [LOCALE ...]   # regenerate languages/<locale>/updates.txt
    python tools/release.py verify  [LOCALE ...]   # check updates.txt against the files (exit 1 on mismatch)
    python tools/release.py nar     [LOCALE ...] [--out dist]   # build <locale>.nar like auto_release.yml
    python tools/release.py notes TAG [LOCALE ...]              # release notes body (Markdown)

``updates`` reproduces Taromati2/ukagaka-mirror-md5-CI-build in "other" mode
(used by md5-CI-build.yml): files are filtered with the locale's
``md5buildignore.txt``, the date field is the fixed ``2012-12-21T00:00:00``,
entries are sorted by path, and lines end with CRLF. Only updates.txt is
produced; updates2.dau is not used by this repository.

Without LOCALE arguments every folder under languages/ is processed.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sspres  # noqa: E402

UPDATES = 'updates.txt'
IGNORE_FILE = 'md5buildignore.txt'
FIXED_DATE = '2012-12-21T00:00:00'
# Removed from the folder before packing in auto_release.yml.
NAR_EXCLUDE = {'updates.txt', 'md5buildignore.txt'}
NAR_ICON_DIR = '.nar_icon'
REPO_URL = 'https://github.com/ukatech/ssp-i18n'

# Link labels used in the release notes (auto_release.yml); others use install.txt "name".
RELEASE_LABELS = {'english': 'English', 'chinese-simplified': '简体中文', 'chinese-traditional': '繁體中文'}


# ---------------------------------------------------------------------------
# md5buildignore.txt matching (port of my-gists/file/filematch.cpp)
# ---------------------------------------------------------------------------


def _rule_regex(rule):
    """'*' matches any run of characters (including '/'), '?' one character."""
    out = []
    for ch in rule:
        if ch == '*':
            out.append('.*')
        elif ch == '?':
            out.append('.')
        else:
            out.append(re.escape(ch))
    return re.compile('^' + ''.join(out) + '$', re.S)


class IgnoreRules(object):
    def __init__(self, lines):
        self.ignore = []    # plain rules
        self.keep = []      # "!rule": re-include, checked first
        for raw in lines:
            rule = raw.rstrip('\r\n')
            if not rule:
                continue
            neg = rule.startswith('!')
            if neg:
                rule = rule[1:]
            rule = rule.replace('\\', '/')
            if not rule.startswith('/'):
                rule = '*/' + rule
            if rule.endswith('/'):
                rule = rule[:-1]
            (self.keep if neg else self.ignore).append(_rule_regex(rule))

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls([])
        with open(path, encoding='utf-8', errors='replace') as f:
            return cls(f.read().splitlines())

    def included(self, rel):
        """*rel* is '/'-prefixed, e.g. '/ssp-pictures/realize.png'."""
        if any(r.match(rel) for r in self.keep):
            return True
        if any(r.match(rel) for r in self.ignore):
            return False
        return True


def collect_files(locale_dir):
    """Paths (relative, '/'-separated) that go into updates.txt."""
    rules = IgnoreRules.load(os.path.join(locale_dir, IGNORE_FILE))
    out = []

    def walk(abs_dir, rel_dir):
        for name in sorted(os.listdir(abs_dir)):
            rel = rel_dir + '/' + name
            if not rules.included(rel):
                continue
            p = os.path.join(abs_dir, name)
            if os.path.isdir(p):
                walk(p, rel)
            else:
                out.append(rel[1:])
    walk(locale_dir, '')
    return sorted(out)


def file_entry(locale_dir, rel):
    p = os.path.join(locale_dir, *rel.split('/'))
    with open(p, 'rb') as f:
        data = f.read()
    return rel, hashlib.md5(data).hexdigest(), len(data)


def render_updates(entries):
    lines = ['charset,UTF-8']
    for rel, md5, size in entries:
        lines.append('file,%s\x01%s\x01size=%d\x01date=%s\x01' % (rel, md5, size, FIXED_DATE))
    return ('\r\n'.join(lines) + '\r\n').encode('utf-8')


def parse_updates(data):
    entries = {}
    for line in data.decode('utf-8', 'replace').splitlines():
        if not line.startswith('file,'):
            continue
        parts = line[5:].split('\x01')
        if len(parts) < 3:
            continue
        size = parts[2][5:] if parts[2].startswith('size=') else ''
        entries[parts[0]] = (parts[1], int(size) if size.isdigit() else None)
    return entries


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def locale_dirs(names):
    all_names = sspres.list_locales()
    names = names or all_names
    for n in names:
        if n not in all_names:
            sys.exit('unknown locale: %s (have: %s)' % (n, ', '.join(all_names)))
    return [(n, os.path.join(sspres.LANG_ROOT, n)) for n in names]


def cmd_updates(args):
    changed = 0
    for name, d in locale_dirs(args.locales):
        data = render_updates([file_entry(d, rel) for rel in collect_files(d)])
        path = os.path.join(d, UPDATES)
        old = open(path, 'rb').read() if os.path.exists(path) else None
        if old == data:
            print('%-22s %s unchanged' % (name, UPDATES))
            continue
        with open(path, 'wb') as f:
            f.write(data)
        changed += 1
        print('%-22s %s written' % (name, UPDATES))
    return 0


def cmd_verify(args):
    bad = 0
    for name, d in locale_dirs(args.locales):
        path = os.path.join(d, UPDATES)
        if not os.path.exists(path):
            print('MISSING  languages/%s/%s' % (name, UPDATES))
            bad += 1
            continue
        listed = parse_updates(open(path, 'rb').read())
        actual = dict((rel, (md5, size)) for rel, md5, size in (file_entry(d, r) for r in collect_files(d)))
        for rel in sorted(set(listed) | set(actual)):
            if rel not in actual:
                print('STALE    languages/%s/%s lists %s (not shipped / not present)' % (name, UPDATES, rel))
                bad += 1
            elif rel not in listed:
                print('UNLISTED languages/%s/%s is not in %s' % (name, rel, UPDATES))
                bad += 1
            elif listed[rel][0] != actual[rel][0] or (listed[rel][1] is not None and listed[rel][1] != actual[rel][1]):
                print('MISMATCH languages/%s/%s (md5/size differ from %s)' % (name, rel, UPDATES))
                bad += 1
        expected = render_updates([(r,) + actual[r] for r in sorted(actual)])
        if not bad and open(path, 'rb').read() != expected:
            print('FORMAT   languages/%s/%s differs from the canonical output (run: release.py updates %s)'
                  % (name, UPDATES, name))
            bad += 1
    print('%d problem(s)' % bad if bad else 'updates.txt OK')
    return 1 if bad else 0


def tracked_files(rel_dir):
    """Files under *rel_dir* (repo-relative) that git tracks; working tree as fallback."""
    try:
        out = subprocess.check_output(['git', 'ls-files', '-z', '--', rel_dir], cwd=sspres.REPO_ROOT)
        files = [p for p in out.decode('utf-8').split('\0') if p]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    res = []
    for root, _dirs, names in os.walk(os.path.join(sspres.REPO_ROOT, rel_dir)):
        for n in names:
            res.append(os.path.relpath(os.path.join(root, n), sspres.REPO_ROOT).replace(os.sep, '/'))
    return res


def cmd_nar(args):
    out_dir = os.path.abspath(args.out)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for name, d in locale_dirs(args.locales):
        nar = os.path.join(out_dir, name + '.nar')
        files = []
        for p in tracked_files('languages/%s' % name):
            arc = p[len('languages/'):]
            if os.path.basename(arc) in NAR_EXCLUDE and arc.count('/') == 1:
                continue
            files.append((os.path.join(sspres.REPO_ROOT, p), arc))
        for p in tracked_files(NAR_ICON_DIR):
            files.append((os.path.join(sspres.REPO_ROOT, p), p))
        if os.path.exists(nar):
            os.remove(nar)
        with zipfile.ZipFile(nar, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for src, arc in sorted(files, key=lambda x: x[1]):
                z.write(src, arc)
        print('%-22s %s (%d files, %d KB)' % (name, os.path.relpath(nar), len(files), os.path.getsize(nar) // 1024))
    return 0


def cmd_notes(args):
    lines = []
    dirs = locale_dirs(args.locales)
    dirs.sort(key=lambda nd: nd[0] != sspres.SOURCE_LOCALE)  # english first, as before
    for name, d in dirs:
        label = RELEASE_LABELS.get(name)
        if not label:
            inst = sspres.kv_dict(sspres.parse_kv(sspres.read_text(os.path.join(d, 'install.txt')).text))
            label = inst['name'].value.strip() if 'name' in inst else name
        lines.append('[%s](%s/releases/download/%s/%s.nar)' % (label, REPO_URL, args.tag, name))
    lines.append('')
    lines.append('If you encounter issues, try online-updating SSP, ghosts, and language packs first.')
    print('\n'.join(lines))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('updates', help='regenerate updates.txt')
    p.add_argument('locales', nargs='*')
    p = sub.add_parser('verify', help='check updates.txt against the files')
    p.add_argument('locales', nargs='*')
    p = sub.add_parser('nar', help='build .nar packages')
    p.add_argument('locales', nargs='*')
    p.add_argument('--out', default=os.path.join(sspres.REPO_ROOT, 'dist'), help='output folder (default: dist/)')
    p = sub.add_parser('notes', help='print release notes')
    p.add_argument('tag')
    p.add_argument('locales', nargs='*')
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if not args.cmd:
        ap.print_help()
        return 2
    return {'updates': cmd_updates, 'verify': cmd_verify, 'nar': cmd_nar, 'notes': cmd_notes}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
