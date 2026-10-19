"""Natural supplier-size ordering without changing labels or variant identities."""
import re
from decimal import Decimal


def size_key(value):
    text = re.sub(r'[\s_-]+', '', str(value or '').strip().upper())
    aliases = {'SMALL':'S', 'MEDIUM':'M', 'LARGE':'L', 'EXTRASMALL':'XS',
               'EXTRALARGE':'XL', 'OS':'ONESIZE', 'OSFA':'ONESIZE', 'OSFM':'ONESIZE'}
    text = aliases.get(text, text)
    repeated = re.fullmatch(r'(X+)(S|L)', text)
    if repeated:
        text = str(len(repeated.group(1))) + 'X' + repeated.group(2)
    match = re.fullmatch(r'(\d*)XS', text)
    if match:
        return (0, -int(match.group(1) or 1), ())
    if text in ('S', 'M', 'L'):
        return (0, {'S':0, 'M':1, 'L':2}[text], ())
    match = re.fullmatch(r'(\d*)XL', text)
    if match:
        return (0, 2 + int(match.group(1) or 1), ())
    if text == 'ONESIZE':
        return (2, 0, ())
    if not text:
        return (4, 0, ())
    # Numeric, youth, infant and dimensions use natural token order.
    tokens = tuple((0, Decimal(part)) if re.fullmatch(r'\d+(?:\.\d+)?', part)
                   else (1, part) for part in re.split(r'(\d+(?:\.\d+)?)', text) if part)
    return (1 if any(token[0] == 0 for token in tokens) else 3, 0, tokens)


def sort_variants(variants):
    return sorted(variants or [], key=lambda v: (
        size_key(v.get('size')), str(v.get('color') or '').casefold(),
        str(v.get('variant_sku') or '').casefold(), str(v.get('id') or '')))
