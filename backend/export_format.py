"""Shared display formatting and image response contract. Source identities stay intact."""
import html
import math
import re
import unicodedata
from html.parser import HTMLParser

EXPORT_BUILD = '2026-10-12.export-polish-1'
ACRONYMS = {'atc':'ATC', 'ajm':'AJM', 'ogio':'OGIO', 'koi':'KOI', 'usa':'USA',
            'uv':'UV', 'upf':'UPF', 'cvc':'CVC', 'ansi':'ANSI', 'csa':'CSA',
            'xs':'XS', 'xl':'XL', 'xxl':'XXL', 'pvc':'PVC', 'dtf':'DTF', 'dtg':'DTG'}


def product_title(name, sku=''):
    value = unicodedata.normalize('NFC', html.unescape(str(name or '')))
    value = re.sub(r'[™®©]', '', value)
    sku = str(sku or '').strip()
    if sku:
        value = re.sub(r'(?<![A-Za-z0-9])' + re.escape(sku) + r'(?![A-Za-z0-9])', '', value, flags=re.I)
    value = re.sub(r'\bL/S\b', 'Long Sleeve', value, flags=re.I)
    value = re.sub(r'\bS/S\b', 'Short Sleeve', value, flags=re.I)
    value = re.sub(r'\bYTH\b', 'Youth', value, flags=re.I)
    value = re.sub(r'\s+', ' ', value).strip(' .,;:|')
    value = re.sub(r'\s+([.,;:!?])', r'\1', value)
    # Preserve intentional mixed-case branding; normalize shouting supplier titles.
    if value == value.upper():
        value = value.lower().title()
    value = re.sub(r"\b[A-Za-z]+\b", lambda m: ACRONYMS.get(m.group().lower(), m.group()), value)
    if sku and value.casefold() != sku.casefold():
        value = f'{value} {sku}'.strip()
    return value or sku


def family_title(name, sku, number):
    return f'{product_title(name, sku)} — Colours {int(number):02d}'


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data): self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ('br','p','li','div'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('p','li','div'): self.parts.append('\n')


def description_lines(value):
    parser = _Text()
    parser.feed(str(value or ''))
    value = ''.join(parser.parts).replace('\xa0',' ')
    # Split sentence boundaries, but keep decimal numbers and every fabric footnote.
    value = re.sub(r'(?<=[.!?])\s+(?=[A-Z0-9*])', '\n', value)
    return [re.sub(r'\s+', ' ', line).strip() for line in value.splitlines() if line.strip()]


def description_html(value):
    lines = description_lines(value)
    return '<ul>' + ''.join('<li>' + html.escape(line) + '</li>' for line in lines) + '</ul>' if lines else ''


def description_text(value):
    return re.sub(r'\s+', ' ', ' '.join(description_lines(value))).strip()


def normalize_image_ack(result, owner_field, owner_id):
    if not isinstance(result, dict): return {'_image_ack_unverified': True}
    if result.get('_lightspeed_validation_error'): return result
    data = result.get('data') if isinstance(result.get('data'), dict) else result
    image_id = data.get('id')
    if not isinstance(image_id, str) or not image_id.strip() or data.get('error'):
        return {'_image_ack_unverified': True}
    if data.get(owner_field) is not None and str(data[owner_field]) != str(owner_id):
        return {'_image_ack_unverified': True}
    return {'data': dict(data), '_image_acknowledged': True}


def assert_service_compatible(service):
    # Check the real service before any image POST. Test adapters may supply their own contract.
    if type(service).__module__ == 'lightspeed_service' and getattr(service, 'export_build', None) != EXPORT_BUILD:
        raise RuntimeError('Incompatible export files. Replace the complete lightspeed_service.py and export_format.py, then restart Uvicorn. No image request sent.')


def inventory_quantity(row):
    value = row.get('inventory')
    try:
        number = float(value)
        if not math.isfinite(number) or number < 0 or not number.is_integer(): raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Unknown, invalid or fractional inventory for ' + str(row.get('variant_sku') or row.get('sku') or 'variant') + '; no stock update sent')
    return int(number)
