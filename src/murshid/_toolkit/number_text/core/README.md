# Reading the numbers people write, and finding them in text

A person writes "12,50", "1.234,56", "١٢٫٥٠" or "fifteen"; a reader that drops every comma reads
"12,50" as 1250. This core reads one number by one decimal rule and refuses, with a reason, a form
the rule cannot settle. It also finds every number, date, time and code in free text as whole tokens
with spans in the original text, reads whole numbers written in English and Arabic words, finds a
figure in a text as cited, elsewhere or absent, and says which ISO codes a currency word can mean.
Plain functions, standard library only, sync.

## How to call it

```python
from decimal import Decimal

from toolkit.number_text.core import find_figure, infer_decimal_mark, numbers_in, read_number
from toolkit.number_text.core import dates_match, figures_in, numbers_in_data, read_words, words_in
from toolkit.number_text.core import currencies_agree, currency_codes, times_match

read_number("1.234,56", max_places=2)  # NumberRead(value=Decimal("1234.56"))
read_number("1,500", max_places=3)  # reason "ambiguous", readings (1500, 1.500)
read_number("1,500", max_places=3, decimal_mark=infer_decimal_mark(["12,50"]))  # 1.500
read_number("-5", max_places=0, negative=True, limit=Decimal(10**6))

for token in numbers_in("Lines 1,2 and 3 of INV-000041, due 7 March 2026 at 9:30 pm: SAR900"):
    token.kind, token.span, token.readings, token.dates, token.times, token.code, token.currency

numbers_in_data({"id": 7, "total": "4120.50", "due": "2026-03-07"})  # skips ids, keeps paths
dates_match(cited.dates[0], known.dates[0])  # by calendar day, or by the parts cited
times_match(cited.times[0], known.times[0])  # the hour and minute, and the second when cited
read_words("اتنين أو تلاتة")  # 3: a range in words reads as its highest number
words_in("We need fifteen laptops")  # number tokens with in_words=True
find_figure(Decimal(50), text, cited=[(120, 188)])  # where: "cited", "elsewhere" or "absent"
figures = figures_in(text)  # scan a long text once, then find_figure(value, figures, cited)
numbers_in("Vendor V003 has 3 disputes")  # a code V003 and the number 3
numbers_in("Vendor V003", joined_codes=False)  # the number 003: joined codes off
currency_codes("ريال")  # frozenset({"SAR", "QAR", "OMR", "YER"})
currencies_agree("riyal", "SAR")  # True; ("USD", "SAR") is False; an unknown side agrees
```

## The decimal rule

The Arabic decimal separator is always decimal and the Arabic thousands separator always groups.
With a comma and a point, the last is decimal. One mark before one or two final digits is decimal.
One mark before exactly three digits follows the document's decimal mark when it is known, at any
number of places ("12.505" where the document writes "4,120.50" is too precise for SAR, never
12505). Otherwise it groups when the value has at most two places ("1,200 SAR" is 1200), and is
`ambiguous` when it may have three ("1,500 KWD", a quantity), unless the whole part is zero
("0,500" is 0.5). Within one value a plain or no-break
space groups by three. Reasons: `empty`, `ambiguous`, `not_a_number`, `out_of_range`,
`too_precise`.

## What `numbers_in` returns

| Kind | Written as | Holds |
|---|---|---|
| `number` | "4,120.50", "SAR900", "٩٠٠ريال" | `readings`: every reading the form allows, each a tuple of values; `currency`; `numbering` for "1." at a line's start |
| `date` | "2026-03-07", "15 October 2026", "07/03/2026", "2026-03-07T10:30:00Z" | `dates`: one `PartialDate` per reading; `times` when a time follows a date in digits |
| `month_year` | "October 2026", "تشرين الأول ٢٠٢٦" | `dates` with no day |
| `day_month` | "October 15", "١٥ أكتوبر" | `dates` with no year |
| `time` | "9:00", "21:30:15", "9:30 pm", "٩:٣٠ م", "10:30+03:00" | `times`: one `TimeOfDay` on the 24-hour clock |
| `code` | "INV-000041", "Q3", "V003", "WDD1771421J550011" | `code`: letters in upper case, digits folded, hyphens dropped |

In free text nothing is refused: "1,500" reads as 1500 and as 1.5, "1,2" as 1.2 and as 1 and 2,
"15-20" as 15 and 20, and a plain space ends a number. A date's parts, a time's parts and a code's
digits are never numbers. A month and year matches any day of that month, and a day and month
matches it in any year. Numbers are magnitudes: a sign is not read in text, so a changed sign is not
caught. A day or a year is never part of a number: "4120.15 October 2026" is 4120.15 and October
2026.

## Joined codes

A joined code is one run of Latin letters and digits, with single hyphens between them, that holds
a letter and a digit and is written as no figure is: "V003", "WDD1771421J550011", "ORD-48213",
"FY2026", "H1". It is one `code` token, so no number is read inside it; "ord48213" and "ORD-48213"
have one key. A run is a figure when every piece between its hyphens is a figure's piece: a number
with a word after it ("150k", "1st", "2-year", "48213AB"), a size ("160x200"), a number with a
currency, a month or an x joined before it ("QAR138000", "Oct19", "x2"), a unit with its power
("m2", "100m2"), or am and pm after a number ("10am-5pm"). Letters alone before a hyphen start a
figure only as a currency ("AED-500"), a month before one day or one year ("oct-19", "Sept-2026"),
or am or pm after a time, with its minutes after a colon or a point ("9:30 am-11:30 am",
"8.30 am-5.30 pm"); a unit, an x, am or pm there starts a code ("CM-000012", "X-200", "PM-0042"),
and so does a month with more pieces ("MAR-2026-01"). A currency joined by a hyphen is the number's
currency ("SAR-900" is 900 SAR). Arabic letters never stand in a code ("ال٣٣٣" is 333), digits
alone stay a number, and "Flat 12", with its space, is the number 12 while "Flat-12" is a code. A
code never takes some of a number's digits: "v1.2" is the number 1.2. The rule runs after the
dates and times in digits, so a timestamp is never a code, and after the caller's code shape: the
default shape gives way to it for a run written as a figure, and a shape of your own decides first,
as written. `joined_codes=False` on `numbers_in`, `numbers_in_data`, `figures_in` and
`find_figure` gives the reading without it, and so leaves out the ISO codes that the currency
pattern does not name.

## Currencies

`currency_codes(word)` gives the ISO 4217 codes a currency word, symbol or abbreviation can mean,
in any case and with its Arabic or English plural: "SAR" and "ر.س" mean SAR; "riyal" and "ريال"
mean SAR, QAR, OMR and YER; "dinar" and "دينار" mean seven dinars; "$" means USD; an ISO code means
itself; an unknown word means the empty set. `currencies_agree(a, b)` is True when either set is
empty or the two sets meet. Every word `CURRENCY_SHAPE` reads has a set: a test spells the pattern
to check it.

## Times

A time is an hour from 0 to 23, a colon, two digits of minutes and optional seconds, in any script's
digits. It reads on the 24-hour clock: "9:00" is 09:00, never 21:00, because a person reads it as
the morning. A marker after it changes an hour from 1 to 12: am, pm, a.m. and p.m. in any case, and
the Arabic ص and م or صباحًا and مساءً ("12:30 am" is 00:30, "٩:٣٠ م" is 21:30); on any other hour
it is left outside the token ("13:00 pm" is 13:00). "Z" or a "+" offset belongs to the token and
changes nothing; a hyphen is a range, so "8:00-9:30" is two times. A time is never part of a larger
number: "10:30:45:12" is four numbers, "12:30.5" is 12 and 30.5, "24:00" and "9:60" are two each,
and a ratio whose second part is not two digits is its numbers ("3:1" is 3 and 1). One whose second
part is two digits reads as a time ("1:30"), as the text does not say which. `times_match` compares
the hour and minute, and the second when cited: "9:00" is backed by 09:00:30, never by 09:01. A
datetime or time in data, and a timestamp in text, hold their time as written, in their own zone.
After a date in digits, a time joined with "T" may carry "Z", a "+" or a "-" offset
("2026-11-05T10:30-05:00", as ISO 8601 writes it). A time joined with a space carries "Z" or a "+"
offset only, and a hyphen after it is a range: "2026-11-05 10:30-11:30" is the date with 10:30,
then the time 11:30 as a token of its own.

## Numbers in words, and the words that are not read

`words_in` and `read_words` read whole numbers from 0 to 9,999 in English and Arabic, with the
Gulf, Egyptian and Levantine forms. A number word with another meaning is still read ("one", ست,
سبع), except where the other meaning is the more common one alone: تلت ("a third") and تمن
("price") are read only inside a longer word, مية and ميه ("water" in Egyptian) only inside a
longer number ("مية وخمسين" is 150, "مية ريال" is not read), and two with the article (الاثنين,
الاتنين) is Monday and is never read. The standard مئة, written with its hamza, is read alone.

## Seams

- `max_places`, `decimal_mark`, `negative` and `limit` on `read_number`; `decimal_mark` on the
  scanners. `infer_decimal_mark(values)` gives a document's mark from the values that prove one.
- `code_shape`: a compiled pattern run on the text with its digits folded (write `[0-9]`). The
  default is letters, a hyphen and digits, and Q1 to Q4. `joined_codes` (default True) reads joined
  codes after it. `currency_shape`: what may stand beside a number. With the default shape and
  joined codes on, any ISO 4217 code in capitals (`ISO_4217`) stands beside a number too ("120
  CAD", "CAD120"), so a price in another currency is never read as a code; in small letters such
  codes are words ("cad", "nok"). The codes that are also English words or common abbreviations in
  capitals are left out ("TOP 10", "ALL 5", "50 KGS", "CVE-2024-3094": the list is in
  `scanning.py`). Your own shape replaces both.
- The currency table in `currencies.py`: each word, symbol and abbreviation and its ISO codes.
- `is_id`: which keys of structured data hold ids (default `id` and `*_id`). A UUID is skipped
  wherever it is. A string that is a plain machine number ("1.500") has one reading.
- `words` on `find_figure` and `figures_in`: False looks at digits only. A scan of 400,000
  characters took about half a second on 2026-10-16, so scan a long text once with `figures_in`.

## When lifting, change

Each value's maximum decimal places (from its currency, or zero for a count), the document's
decimal mark when it declares one, the code shape, whether joined codes are read, the id keys, and,
when your currencies are others, both the currency table in `currencies.py` and the currency
pattern (`currency_shape`), since a word only the table holds is never read beside a number; your
own pattern also turns off the reading of ISO codes in capitals. Not done here: numbers in words
above 9,999, words in languages other than English and Arabic, Maghreb month names, two-digit
years, signs in free text, times written with a point ("9.30" is a number) or without minutes
("9 am" is the number 9), times in words ("in the evening"), a negative time zone in free text
anywhere but after a date joined to its time with "T", a unit's power ("100m2" is 100 and 2), a
date in digits inside a code (read as a date), and a code that the code shape ends before the run
does ("SKU-77-B" is the code SKU-77).
`fold_digits` folds the digits of every script and keeps positions. `fold_arabic(text, marks=True)`
folds the Arabic letter forms one character to one (أ إ آ ٱ to ا, ة to ه, ى to ي, ؤ to و, ئ to ي)
and removes the marks and the tatweel; with `marks=False` it keeps positions. Both readers compare
letters through it, so a lift that folds text the same way agrees.

Needs: the standard library. Tests: `toolkit/number_text/tests/`.
