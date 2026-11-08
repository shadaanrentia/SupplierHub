"""Readable display labels while preserving supplier identities."""
import re
STYLE_PHRASES = {'S4002': [(r'\bCo\s+Inset\b', 'Contrast Inset')]}
NAME_RULES = [
    (r'\bCBlockPolo\b', 'Colour Block Polo'),
    (r'\bCBlock\b', 'Colour Block'),
    (r'\bLds\b[\u2019\']?\s*', 'Ladies\u2019 '),
    (r'\bYth\b', 'Youth'),
    (r'\bPckt\b|\bPkt\b', 'Pocket'),
    (r'\bSnag\s+Resist\b', 'Snag Resistant'),
    (r'\bProTeam\b', 'Pro Team'),
    (r'\bCotton/Poly\b', 'Cotton/Polyester'),
    (r'\bL/S\b', 'Long Sleeve'),
    (r'\bS/S\b', 'Short Sleeve'),
]
COLOUR_ALIASES = {
    'charcoal hthr': 'Charcoal Heather', 'hthr cardinal': 'Heather Cardinal',
    'hthr forest': 'Heather Forest', 'hthr navy': 'Heather Navy',
    'hthr teal': 'Heather Teal', 'extreme yello': 'Extreme Yellow',
    '~orange': 'Orange', '~silver': 'Silver', 'wildraspberry': 'Wild Raspberry',
    'irongrey': 'Iron Grey', 'truenavy': 'True Navy',
}

def full_product_name(value, supplier_sku=''):
    text = str(value or '').strip()
    for pattern, replacement in STYLE_PHRASES.get(str(supplier_sku).strip().upper(), []):
        text = re.sub(pattern, replacement, text, flags=re.I)
    for pattern, replacement in NAME_RULES:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip()

def full_colour_name(value):
    text = re.sub(r'\s+', ' ', re.sub(r'^[\s~]+', '', str(value or ''))).strip()
    return COLOUR_ALIASES.get(text.casefold(), COLOUR_ALIASES.get('~'+text.casefold(), text))

def display_product_labels(row):
    from export_format import product_title
    result = dict(row)
    result['source_product_name'] = row.get('product_name')
    result['product_name'] = product_title(row.get('product_name'), row.get('supplier_sku'))
    return result

def display_variant_labels(row):
    result = dict(row)
    result['source_color'] = row.get('color')
    result['color'] = full_colour_name(row.get('color'))
    return result
