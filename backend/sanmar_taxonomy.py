"""Parse SanMar Canada's style/category export without guessing SKU prefixes.

English names for French paths are curated translations, not a live website scrape.
Unknown translations and ambiguous primary destinations stay in the review queue.
"""
import csv
import hashlib
import html
import io
import re
import unicodedata
from collections import Counter

ROOTS = ['Accessories', 'Bags', 'Headwear', 'Fleece', 'Ladies’ Only',
         'Pants/Shorts', 'Polos', 'Outerwear', 'Protective Wear', 'T-Shirts',
         'Workwear', 'Woven Shirts', 'Youth Only', 'On Sale']
TRANSLATIONS = {
    'Accessoires': 'Accessories', 'Sacs': 'Bags', 'Chapeaux': 'Headwear',
    'Molletons': 'Fleece', 'Molleton': 'Fleece', 'Pour femmes': 'Ladies’ Only',
    'Pantalons': 'Pants/Shorts', 'Pantalons et shorts': 'Pants/Shorts', 'Polos': 'Polos',
    "Vêtements d'extérieur": 'Outerwear', 'Vêtements d’extérieur': 'Outerwear',
    'Vêtement de protection': 'Protective Wear', 'Vêtements de travail': 'Workwear',
    'Chemises tissées': 'Woven Shirts', 'Pour jeunes': 'Youth Only', 'En vente': 'On Sale',
    'T-shirts et vêtements de sport': 'T-Shirts', 'T-shirts et vêtements actif': 'T-Shirts',
    'T-Shirts et Vêtements actif': 'T-Shirts', 'T-Shirts & Activewear': 'T-Shirts',
    'T-Shirts/Activewear': 'T-Shirts', 'Pants & Shorts': 'Pants/Shorts',
    'Adulte': 'Adult', 'Femme': 'Ladies’', 'Jeune': 'Youth',
    'Manches longues': 'Long Sleeve', 'Manches courtes': 'Short Sleeve',
    'Manches longues et manches 3/4': 'Long Sleeve & 3/4 Sleeve',
    'Sans manches': 'Sleeveless', 'Débardeurs': 'Tanks', 'Col en V': 'V-Neck',
    'Avec poche': 'Pocketed', 'Col rond': 'Crewneck', 'Sans capuchon': 'Non-Hooded',
    'Capuchon': 'Hooded', 'Glissière complète': 'Full Zip',
    'Demi-glissière et glissière 1/4': '1/2 and 1/4 Zip', 'Col droit': 'Cadet Collar',
    "Pantalons d'exercice": 'Sweatpants', 'Coton/mélange de coton': 'Cotton/Cotton Blend',
    '100 % coton': '100% Cotton', 'Sergé de coton': 'Cotton Twill', 'Mode': 'Fashion',
    'Bicolore': 'Colour Block', 'Anti-accroc': 'Anti-Snag', 'Ajustable': 'Adjustable',
    'Ajusté': 'Fitted', 'Visière plate': 'Flat Bill', '3 tailles ajustables': '3-Size Adjustable',
    'Tuques/bonnets': 'Toque/Beanie', 'Sacs à dos': 'Backpacks', 'Sacs souples': 'Cinch Packs',
    'Sacs de sport': 'Duffels', 'Sacs à bandoulière': 'Messengers', 'Sacs de tissu': 'Totes',
    'Sacs de voyage': 'Travel', 'Glacières': 'Coolers', 'Sac à outils': 'Tool Bags',
    'Tabliers': 'Aprons', 'Ceintures': 'Belts', 'Écharpes': 'Scarves', 'Couverture': 'Blankets',
    'Couvre-visages': 'Face Coverings', 'Accessoires de présentation': 'Display Accessories',
    'Manteaux légers et coquille': 'Lightweight & Shell Jackets', 'Manteaux de pluie': 'Rain Jackets',
    'Coquilles souples': 'Soft Shells', 'Vestes': 'Vests', 'Doublé': 'Insulated',
    'Système de manteau 3 en 1': '3-in-1 System Jackets', 'Coupe-vent': 'Windbreaker',
    'Capuchon amovible': 'Detachable Hood', 'Capuchon scuba': 'Scuba Hood',
    'Réfléchissant à la lumière': 'Light Reflective', 'Hydrofuge': 'Water Repelling',
    "Résistant à l'eau": 'Water Resistant', 'Imperméable': 'Waterproof',
    'Élément réfléchissant': 'Reflective Features', 'Fusionné': 'Bonded',
    'Facile d’entretien': 'Easy Care', 'Industriel': 'Industrial', 'Ignifuge': 'Flame Resistant',
    'Protection contre les risques électriques': 'Electric Hazard Protection',
    'Vêtements haute visibilité': 'High-Visibility Wear', 'Haute visibilité': 'High-Visibility Wear',
    'Couleurs de sécurité et vibrantes': 'Safety Colours & Brights', 'Combinaison': 'Coveralls',
    'En commande spéciale': 'Special Order Features', 'Styles de vêtements de travail en stock': 'In-Stock Workwear',
    'Boutons-pression': 'Snap Front', 'Facilitant le détachage': 'Stain Release',
    "Grand et jusqu'à 6TG": 'Tall & Up To 6XL', "Grand et jusqu'à 6 TG": 'Tall & Up To 6XL',
    "Jusqu'à 6TG": 'Up To 6XL', "Jusqu'à 5TG": 'Up To 5XL',
    'Nouveaux styles': 'New Styles', 'Réduction de prix': 'Price Reduction',
    'Vente de manteaux': 'Outerwear Sale', 'Prix du marché': 'Market Price',
    'Everyday FILÉ': 'Everyday RING SPUN',
    'ATC': 'ATC™', 'ATC ESActive': 'ATC™ ESActive®', 'ATC Everyday': 'ATC™ Everyday',
    'ATC Realtree': 'ATC™ Realtree®', 'ATC Earth Wash': 'ATC™ Earth Wash®',
    'ATC Flexfit': 'ATC™ Flexfit®', 'ATC WeRK': 'ATC WeRK™',
    'The North Face': 'The North Face®', 'Original Penguin': 'Original Penguin®',
    'EuroSpun': 'ATC™ EuroSpun®', 'Red Kap MIMIX': 'Red Kap® MIMIX™',
    'Chef Designs': 'Chef Designs®', 'Mimix': 'MIMIX™',
    'Casquette en mailles extensibles': 'Stretch Mesh Caps',
}
# Garment/shape branches outrank fabric, brands, and collections. A tied decision is reviewed.
PRIORITY = ['Coveralls', 'Aprons', 'Sweatpants', 'Backpacks', 'Duffels', 'Cinch Packs',
            'Messengers', 'Totes', 'Travel', 'Coolers', 'Tool Bags', 'Toque/Beanie',
            'Rain Jackets', '3-in-1 System Jackets', 'Soft Shells', 'Vests',
            'Lightweight & Shell Jackets', 'Long Sleeve & 3/4 Sleeve', 'Long Sleeve',
            'Short Sleeve', 'Tanks', 'Sleeveless', 'Hooded', 'Full Zip',
            '1/2 and 1/4 Zip', 'Crewneck', 'V-Neck', 'Pocketed', 'Core',
            'Performance', 'Cotton/Cotton Blend', '100% Cotton', 'Fashion']


def clean(value):
    value = html.unescape(value or '')
    # Remove trademark superscripts before splitting '>' path separators.
    value = re.sub(r'<sup\b[^>]*>.*?</sup>', '', value, flags=re.I)
    value = re.sub(r'<[^>]+>', '', value)
    return re.sub(r'\s+', ' ', value).strip()


def key(value):
    value = clean(value).replace('’', "'")
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', value.casefold())


T_LOOKUP = {key(k): v for k, v in TRANSLATIONS.items()}


# These are source browse facets, not garment category destinations.
BRAND_COLLECTION_PREFIXES = tuple(key(label) for label in (
    'ATC', 'Gildan', 'KOI', 'OGIO', 'Nike', 'New Era', 'The North Face',
    'Original Penguin', 'Coal Harbour', 'CH Essential', 'Callaway', 'Dickies',
    'Red Kap', 'Chef Designs', 'Bulwark', 'DryFrame', 'Eddie Bauer', 'Realtree',
    'Flexfit', 'EuroSpun', 'Everyday', 'Collection Everyday', 'Pro Team',
    'MIMIX', 'Yupoong', 'Port Authority', 'Port & Company', 'Sport-Tek',
    'North End', 'Stormtech', 'Adidas', 'Puma', 'Carhartt', 'Jerzees',
))


def is_brand_category_path(path):
    parts = [p.strip() for p in str(path or '').split(' > ')]
    # Never classify a garment root such as T-Shirts as a brand.
    return any(key(part).startswith(BRAND_COLLECTION_PREFIXES) for part in parts)


def category_path(path):
    """Product category + subcategory; retain deeper source paths separately."""
    if not path or is_brand_category_path(path):
        return None
    parts = [p.strip() for p in str(path).split(' > ') if p.strip()]
    return ' > '.join([parts[0], ' — '.join(parts[1:])]) if len(parts) > 1 else (parts[0] if parts else None)


def sku_key(value):
    return value.strip().upper()  # never turn a style identifier into an integer


def translate(value, english_labels):
    if key(value) in T_LOOKUP:
        return T_LOOKUP[key(value)], True
    candidates = {label for label in english_labels if key(label) == key(value)}
    if candidates:
        return sorted(candidates, key=lambda x: (-len(x), x))[0], True
    if value in ('Core', 'Camo', 'Performance', 'Triblend', 'Everyday', 'Pro Team', 'Essential', 'FR'):
        return value, True
    return value, False


def choose_primary(paths, nodes):
    eligible = [p for p in paths if nodes[p]['verified'] and nodes[p]['leaf']
                and p.split(' > ')[0] not in ('Ladies’ Only', 'Youth Only', 'On Sale')]
    roots = {p.split(' > ')[0] for p in eligible}
    # A garment may also appear in Workwear/Protective Wear; keep the garment branch.
    garment_roots = roots - {'Workwear', 'Protective Wear'}
    if len(garment_roots) == 1:
        root = next(iter(garment_roots))
    elif len(roots) == 1:
        root = next(iter(roots))
    else:
        return None, 'Multiple product families require a primary category' if roots else 'No verified leaf category'
    choices = [p for p in eligible if p.split(' > ')[0] == root]
    def score(path):
        names = [name.strip() for part in path.split(' > ')[1:] for name in part.split(' — ')]
        rank = min((PRIORITY.index(n) for n in names if n in PRIORITY), default=1000)
        return rank, -len(names)  # Prefer the supplied audience-specific leaf over its generic sibling.
    best_score = min(map(score, choices))
    best = [p for p in choices if score(p) == best_score]
    if len(best) == 1:
        return best[0], 'Exact style match; curated garment/category priority'
    return None, 'Multiple equally ranked leaf categories; select a primary category'


def parse_csv(raw):
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('Upload a non-empty CSV no larger than 10 MiB')
    try:
        text = raw.decode('utf-8-sig'); encoding = 'utf-8-sig'
    except UnicodeDecodeError:
        text = raw.decode('cp1252'); encoding = 'cp1252'
    reader = csv.DictReader(io.StringIO(text, newline=''))
    if not {'sku', 'english_categories', 'french_categories'}.issubset(reader.fieldnames or []):
        raise ValueError('Required columns: sku, english_categories, french_categories')
    rows = []; seen = set(); labels = Counter(); warnings = []; nodes = {}
    for number, row in enumerate(reader, 2):
        if number > 25001:
            raise ValueError('CSV exceeds 25,000 styles')
        sku = (row.get('sku') or '').strip()
        if not sku or len(sku) > 200 or '\x00' in sku:
            raise ValueError(f'Row {number}: invalid style SKU')
        if sku_key(sku) in seen:
            raise ValueError(f'Row {number}: duplicate style SKU {sku}')
        seen.add(sku_key(sku))
        english = list(dict.fromkeys(clean(x) for x in clean(row.get('english_categories')).split(',') if clean(x)))
        invalid = [x for x in english if key(x) in ('null', 'na', 'none') or x.isdigit()]
        if invalid:
            warnings.append({'sku': sku, 'message': 'Invalid labels ignored: ' + ', '.join(invalid)})
        english = [x for x in english if x not in invalid]
        labels.update(english)
        french = list(dict.fromkeys(clean(x) for x in clean(row.get('french_categories')).split(',') if clean(x)))
        rows.append({'sku': sku, 'sku_key': sku_key(sku), 'labels': english,
                     'source_paths': french, 'paths': []})
    if not rows:
        raise ValueError('CSV contains no products')
    all_english = set(labels)
    all_english |= {p.strip() for label in labels for p in label.split('>')}
    for row in rows:
        candidate_paths = []
        for source in row['source_paths']:
            parts = [p.strip() for p in source.split('>')]
            if not parts or key(parts[0]) != key('Magasiner le catalogue'):
                continue
            parts = parts[1:]
            if not parts or key(parts[0]) == key('Magasiner par'):
                continue  # Shop By paths preserved as facets; many exceed POS's 3-level limit.
            translations = [translate(p, all_english) for p in parts]
            translated_path = ' > '.join(t[0] for t in translations)
            if is_brand_category_path(translated_path):
                # Retain original English labels and French paths for source provenance.
                continue
            if translations[0][0] not in ROOTS:
                warnings.append({'sku': row['sku'], 'message': 'Unknown root: ' + parts[0]}); continue
            # Keep the supplied category/audience labels in one final leaf,
            # e.g. T-Shirts > Core — Adult, under Apparel in Lightspeed.
            if len(parts) > 3:
                warnings.append({'sku': row['sku'], 'message': 'Unsupported category depth: ' + source})
                continue
            if len(translations) > 2:
                translations = [translations[0], (' — '.join(t[0] for t in translations[1:]), all(t[1] for t in translations[1:]))]
                parts = [parts[0], ' > '.join(parts[1:])]
            for depth in range(1, len(parts) + 1):
                path = ' > '.join(t[0] for t in translations[:depth])
                node = nodes.setdefault(path, {'path': path, 'name': translations[depth-1][0],
                    'parent_path': ' > '.join(t[0] for t in translations[:depth-1]) or None,
                    'level': depth, 'verified': True, 'leaf': True, 'source_paths': set()})
                node['verified'] = node['verified'] and all(t[1] for t in translations[:depth])
                node['source_paths'].add(' > '.join(parts[:depth]))
            candidate_paths.append(' > '.join(t[0] for t in translations))
        row['paths'] = sorted(set(candidate_paths))
    for node in nodes.values():
        if node['parent_path'] in nodes:
            nodes[node['parent_path']]['leaf'] = False
    for row in rows:
        row['primary_path'], row['reason'] = choose_primary(row['paths'], nodes)
        row['status'] = 'ready' if row['primary_path'] else 'review'
    counts = Counter(p for row in rows for p in row['paths'])
    primaries = Counter(row['primary_path'] for row in rows if row['primary_path'])
    for node in nodes.values():
        node['source_paths'] = sorted(node['source_paths'])
        node['product_count'] = counts[node['path']]
        node['primary_count'] = primaries[node['path']]
    return {'digest': hashlib.sha256(raw).hexdigest(), 'encoding': encoding,
        'rows': rows, 'nodes': sorted(nodes.values(), key=lambda n: n['path']),
        'labels': [{'label': l, 'count': c} for l, c in sorted(labels.items())],
        'warnings': warnings, 'summary': {'styles': len(rows), 'labels': len(labels),
          'category_policy': 'product-only-two-level-audience-v3',
          'categories': len(nodes), 'ready': sum(r['status'] == 'ready' for r in rows),
          'review': sum(r['status'] == 'review' for r in rows),
          'unverified_categories': sum(not n['verified'] for n in nodes.values())}}
