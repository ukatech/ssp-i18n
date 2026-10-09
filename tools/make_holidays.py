#!/usr/bin/env python3
"""Generate the holiday tables (holidays.txt, holidays-XX.txt) of the translated packs.

    python tools/make_holidays.py                       # all tables below, written into languages/<locale>/
    python tools/make_holidays.py korean                # the tables of one locale
    python tools/make_holidays.py --years 2020-2031     # another year range (default 2020-2030)
    python tools/make_holidays.py --out /tmp/holidays   # write to /tmp/holidays/<locale>/ instead (preview)

SSP marks the listed days as holidays in its calendar (Sundays need not be listed).
It looks for holidays-XX.txt first (XX = ISO 3166 country code of the Windows region
setting) and falls back to the holidayname of descript.txt (holidays.txt).
Format: "charset,UTF-8", header comments, then per month a "Year-Month,day day day" line
followed by one "Year-Month-Day,name" line per day (the name SSP shows), UTF-8, LF.

The english and japanese tables are maintained on the SSP side, not here.

Data comes from the python-holidays package (pip install -r tools/requirements.txt),
with these corrections (names are the package's names in the pack's language,
see LANG; Singapore has no Chinese names in the package, they are in SG_ZH):

  CN  2020-2026: the State Council holiday arrangements, whole blocks including the
      weekends inside them (CN_BLOCKS; add a year when it is published, usually in
      November). Weekend days of a block that the package does not list are named
      "<main holiday of the block>假期". Later years: statutory holidays only (the
      package's own "observed" guesses are dropped). Adjusted working days cannot be
      expressed.
  KR  2030 presidential election day: Public Official Election Act art. 34
      (first Wednesday from the 70th day before the end of the term, 2030-06-03).
  HK  statutory holidays + general holidays.
  MO  public holidays + compensatory rest days, without the half days.

Look at the diff before committing: the package changes between versions.
"""

import argparse
import datetime as dt
import os
import sys
from collections import defaultdict

try:
    import holidays
except ImportError:
    sys.exit('python-holidays is required: pip install -r tools/requirements.txt')

HERE = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(os.path.dirname(HERE), 'languages')

D = dt.date
FMT = '//format is "Year-Month,day day day". Example, 2026-1,1 19'
NAME_FMT = '//"Year-Month-Day,name" is the name of the holiday. Example, %s'

# Language of the holiday names of each country, and the separator of two names on one day.
LANG = {'CN': 'zh_CN', 'TW': 'zh_TW', 'HK': 'zh_HK', 'MO': 'zh_MO', 'KR': 'ko', 'SG': 'en_SG'}
SEP = {'ko': ', ', 'en_SG': '; '}  # default: '、'

# Singapore: official Chinese names (Ministry of Manpower).
SG_ZH = {
    "New Year's Day": '元旦', 'Chinese New Year': '农历新年', 'Good Friday': '耶稣受难日',
    'Hari Raya Puasa': '开斋节', 'Labour Day': '劳动节', 'Vesak Day': '卫塞节',
    'Hari Raya Haji': '哈芝节', 'National Day': '国庆日', 'Deepavali': '屠妖节',
    'Christmas Day': '圣诞节', 'Polling Day': '投票日',
}
SG_ZH_SUFFIX = {'observed': '补假', 'estimated': '预计', 'observed, estimated': '补假，预计'}
DEFAULT = ('//Default table. Country specific tables are holidays-XX.txt '
           '(XX = ISO 3166 country code of the Windows region setting).')


def lib(country, years, categories=('public',), drop=()):
    """{date: names} of the package, union of the categories, without days whose names all contain one of drop."""
    out = {}
    for cat in categories:
        h = holidays.country_holidays(country, years=years, categories=(cat,), language='en_US')
        for d, names in h.items():
            out.setdefault(d, set()).update(names.split('; '))
    return {d: n for d, n in out.items() if not all(any(x in s for x in drop) for s in n)}


def names(country, years, categories=('public',), drop=()):
    """{date: name} in the language of LANG; several names of one day joined with SEP."""
    lang = LANG[country]
    out = {}
    for cat in categories:
        h = holidays.country_holidays(country, years=years, categories=(cat,), language=lang)
        for d, n in h.items():
            lst = out.setdefault(d, [])
            for s in n.split('; '):
                if s not in lst and not any(x in s for x in drop):
                    lst.append(s)
    return {d: SEP.get(lang, '、').join(lst) for d, lst in out.items() if lst}


def pkg_table(country, categories=('public',), drop=(), translate=None):
    """Table function: the days of lib() with the names of names()."""
    def table(years):
        loc = names(country, years, categories, drop + ('（下午）',))
        if translate:
            loc = {d: '、'.join(translate(s) for s in n.split('; ')) for d, n in loc.items()}
        return {d: loc[d] for d in lib(country, years, categories, drop)}
    return table


def sg_zh(name):
    base, _, suffix = name.partition(' (')
    suffix = suffix.rstrip(')')
    if base not in SG_ZH or (suffix and suffix not in SG_ZH_SUFFIX):
        sys.exit('SG: no Chinese name for %r, add it to SG_ZH' % name)
    return SG_ZH[base] + ('（%s）' % SG_ZH_SUFFIX[suffix] if suffix else '')


def days_between(a, b):
    return [a + dt.timedelta(i) for i in range((b - a).days + 1)]


# China: State Council holiday arrangements (fang jia tiao xiu), whole blocks.
CN_BLOCKS = [
    (D(2020, 1, 1), D(2020, 1, 1)), (D(2020, 1, 24), D(2020, 2, 2)), (D(2020, 4, 4), D(2020, 4, 6)),
    (D(2020, 5, 1), D(2020, 5, 5)), (D(2020, 6, 25), D(2020, 6, 27)), (D(2020, 10, 1), D(2020, 10, 8)),
    (D(2021, 1, 1), D(2021, 1, 3)), (D(2021, 2, 11), D(2021, 2, 17)), (D(2021, 4, 3), D(2021, 4, 5)),
    (D(2021, 5, 1), D(2021, 5, 5)), (D(2021, 6, 12), D(2021, 6, 14)), (D(2021, 9, 19), D(2021, 9, 21)),
    (D(2021, 10, 1), D(2021, 10, 7)),
    (D(2022, 1, 1), D(2022, 1, 3)), (D(2022, 1, 31), D(2022, 2, 6)), (D(2022, 4, 3), D(2022, 4, 5)),
    (D(2022, 4, 30), D(2022, 5, 4)), (D(2022, 6, 3), D(2022, 6, 5)), (D(2022, 9, 10), D(2022, 9, 12)),
    (D(2022, 10, 1), D(2022, 10, 7)),
    (D(2022, 12, 31), D(2023, 1, 2)), (D(2023, 1, 21), D(2023, 1, 27)), (D(2023, 4, 5), D(2023, 4, 5)),
    (D(2023, 4, 29), D(2023, 5, 3)), (D(2023, 6, 22), D(2023, 6, 24)), (D(2023, 9, 29), D(2023, 10, 6)),
    (D(2024, 1, 1), D(2024, 1, 1)), (D(2024, 2, 10), D(2024, 2, 17)), (D(2024, 4, 4), D(2024, 4, 6)),
    (D(2024, 5, 1), D(2024, 5, 5)), (D(2024, 6, 8), D(2024, 6, 10)), (D(2024, 9, 15), D(2024, 9, 17)),
    (D(2024, 10, 1), D(2024, 10, 7)),
    (D(2025, 1, 1), D(2025, 1, 1)), (D(2025, 1, 28), D(2025, 2, 4)), (D(2025, 4, 4), D(2025, 4, 6)),
    (D(2025, 5, 1), D(2025, 5, 5)), (D(2025, 5, 31), D(2025, 6, 2)), (D(2025, 10, 1), D(2025, 10, 8)),
    (D(2026, 1, 1), D(2026, 1, 3)), (D(2026, 2, 15), D(2026, 2, 23)), (D(2026, 4, 4), D(2026, 4, 6)),
    (D(2026, 5, 1), D(2026, 5, 5)), (D(2026, 6, 19), D(2026, 6, 21)), (D(2026, 9, 25), D(2026, 9, 27)),
    (D(2026, 10, 1), D(2026, 10, 7)),
]
CN_LAST_ARRANGED = max(b.year for a, b in CN_BLOCKS)


def cn(years):
    pkg = lib('CN', years)
    days = set(d for a, b in CN_BLOCKS for d in days_between(a, b))
    # The blocks must contain every day off of the package and add weekends only.
    for d in pkg:
        if d.year <= CN_LAST_ARRANGED and d not in days:
            sys.exit('CN: %s (%s) is not in CN_BLOCKS' % (d, '; '.join(pkg[d])))
    for d in days:
        if d not in pkg and d.weekday() < 5:
            sys.exit('CN: %s in CN_BLOCKS is a weekday the package does not know' % d)
    for d, ns in pkg.items():
        if d.year > CN_LAST_ARRANGED and not all('(observed)' in s for s in ns):
            days.add(d)
    zh = names('CN', years)
    out = {d: zh[d] for d in days if d in zh}
    for a, b in CN_BLOCKS:
        if b.year not in years:
            continue
        bases = [cn_base(s) for d in days_between(a, b) if d in zh for s in zh[d].split('、')
                 if not s.startswith('休息日')]
        main = max(bases, key=bases.count)  # most frequent, first on ties
        for d in days_between(a, b):
            out.setdefault(d, main + '假期')
    return out


def cn_base(name):
    name = name.replace('（补假）', '').replace('延长假期', '')
    return '春节' if name == '农历除夕' else name


def kr(years):
    pkg = lib('KR', years)
    ko = names('KR', years)
    out = {d: ko[d] for d in pkg if not (d.year == 2030 and any('Presidential' in s for s in pkg[d]))}
    out[D(2030, 3, 27)] = '대통령 선거일'
    return out


# locale -> [(file name, header comment lines, function(years) -> {date: name})]
# The first entry of a locale is its default table (holidays.txt).
TABLES = {
    'chinese-simplified': [
        ('holidays.txt',
         ['//China (mainland) public holidays. Until %d: State Council holiday arrangements (whole blocks).'
          % CN_LAST_ARRANGED,
          '//Later years: statutory holidays only, until the State Council publishes the arrangements.'
          ' Adjusted working days are not expressible.'],
         cn),
        ('holidays-SG.txt',
         ['//Singapore public holidays (with observed days; future lunar and Islamic dates are estimated)'],
         pkg_table('SG', translate=sg_zh)),
    ],
    'chinese-traditional': [
        ('holidays.txt',
         ['//Taiwan national holidays (with substitute days and adjusted days off; typhoon days are not included)'],
         pkg_table('TW')),
        ('holidays-HK.txt',
         ['//Hong Kong general holidays (with substitute days)'],
         pkg_table('HK', ('public', 'optional'))),
        ('holidays-MO.txt',
         ['//Macao public holidays (with compensatory rest days; half days are not included)'],
         pkg_table('MO', ('public', 'government', 'optional'), drop=('(Afternoon)',))),
    ],
    'korean': [
        ('holidays.txt',
         ['//South Korea public holidays (with substitute holidays and election days)'],
         kr),
    ],
}


def render(header, days, years, default):
    by_month = defaultdict(list)
    for d in sorted(days):
        if d.year in years:
            by_month[(d.year, d.month)].append(d)
    first = by_month[min(by_month)][0]
    example = '%d-%d-%d,%s' % (first.year, first.month, first.day, days[first])
    lines = ['charset,UTF-8'] + header + ([DEFAULT] if default else []) + [FMT, NAME_FMT % example]
    for (y, m), ds in sorted(by_month.items()):
        lines.append('%d-%d,%s' % (y, m, ' '.join(str(d.day) for d in ds)))
        lines += ['%d-%d-%d,%s' % (d.year, d.month, d.day, days[d]) for d in ds]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('locales', nargs='*', help='default: %s' % ' '.join(TABLES))
    p.add_argument('--years', default='2020-2030', help='FIRST-LAST (default: 2020-2030)')
    p.add_argument('--out', help='output root (default: languages/)')
    args = p.parse_args(argv)

    first, last = map(int, args.years.split('-'))
    years = range(first, last + 1)
    for loc in args.locales or TABLES:
        if loc not in TABLES:
            sys.exit('unknown locale %s (known: %s)' % (loc, ' '.join(TABLES)))
        out_dir = os.path.join(args.out or LANG_DIR, loc)
        os.makedirs(out_dir, exist_ok=True)
        for i, (name, header, func) in enumerate(TABLES[loc]):
            text = render(header, func(years), years, i == 0)
            with open(os.path.join(out_dir, name), 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            print('%-22s %s' % (loc, name))
    print('holidays %s' % holidays.__version__)


if __name__ == '__main__':
    main()
