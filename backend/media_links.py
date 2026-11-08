"""Supplier associations plus a restricted exact SanMar filename recovery path."""
import json
import re


def usable(value):
    return str(value or '').strip().casefold() not in ('', 'na', 'n/a', 'none', 'null', 'not applicable')


def colour_key(value):
    return re.sub(r'\s+', ' ', re.sub(r'^[\s~]+', '', str(value or ''))).strip().casefold()


def xml_links(element):
    parts, colours = [], []
    for node in element.iter():
        if not isinstance(node.tag,str): continue
        tag=node.tag.rsplit('}',1)[-1].casefold()
        value=(node.text or '').strip()
        if not usable(value): continue
        if tag=='partid' and value not in parts: parts.append(value)
        if tag in ('color','colour','colorname','colourname','partcolor','primarycolor'):
            if colour_key(value) not in {colour_key(c) for c in colours}: colours.append(value)
    # Multiple colours require explicit part links; do not pick an arbitrary one.
    return {'part_ids':parts,'color':colours[0] if len(colours)==1 else ''}


def resolved_links(item, variants, colour_normalizer=None):
    key = colour_normalizer or colour_key
    parts=item.get('part_ids') or item.get('partIds') or item.get('source_part_ids') or []
    if not parts and item.get('part_id'):parts=[item['part_id']]
    if isinstance(parts,str):
        try: parsed=json.loads(parts)
        except (ValueError,TypeError):parsed=[parts]
        parts=parsed if isinstance(parsed,list) else [parts]
    parts=list(dict.fromkeys(str(x).strip() for x in parts if usable(x))) if isinstance(parts,list) else []
    colour=str(item.get('color') or item.get('source_color') or item.get('part_color') or '').strip()
    if not usable(colour) or not usable(key(colour)): colour=''
    by_sku={str(v.get('variant_sku') or '').strip().casefold():v for v in variants}
    matched=[by_sku[p.casefold()] for p in parts if p.casefold() in by_sku]
    known_colours={key(v.get('color')) for v in matched if key(v.get('color'))}
    if not colour and len(known_colours)==1:
        colour=next(v['color'] for v in matched if key(v.get('color')))
    if colour and known_colours and known_colours!={key(colour)}:
        # Contradictory metadata cannot safely identify a variant image.
        return '',[],False
    # Expand only a verified, unambiguous colour association to all of its sizes.
    if colour and (not known_colours or known_colours=={key(colour)}):
        same=[str(v['variant_sku']) for v in variants if key(v.get('color'))==key(colour)]
        parts=list(dict.fromkeys(parts+same))
    return colour,parts,bool(any(p.casefold() in by_sku for p in parts))



def sanmar_colour_alias(value):
    """Known SanMar label abbreviations; not a fuzzy or substring matcher."""
    key = colour_key(value)
    aliases = {
        'athletic grey*': 'athletic grey',
        'deep heather*': 'deep heather',
        'charcoal hthr': 'charcoal heather',
        'hthr cardinal': 'heather cardinal',
        'hthr forest': 'heather forest',
        'hthr navy': 'heather navy',
        'hthr teal': 'heather teal',
        'extreme yello': 'extreme yellow',
        '~orange': 'orange',
        '~silver': 'silver',
    }
    key = aliases.get(key, key)
    components = {'wht':'white', 'whit':'white', 'trueroy':'true royal',
                  'trueroyal':'true royal', 'truenavy':'true navy'}
    if '/' in key:
        key = '/'.join(components.get(part.strip(),part.strip()) for part in key.split('/'))
    return key


def associate_sanmar_images(images, variants, product_sku):
    """Recover missing associations from exact SanMar product/colour filename tokens.

    Explicit supplier associations always take precedence. This fallback rejects
    other hosts, products, unknown colours and ambiguous colour matches.
    Inventory and size never control image eligibility.
    """
    from urllib.parse import urlsplit, unquote
    style = str(product_sku or '').strip().casefold()
    result = []
    colours = {}
    for variant in variants:
        colour = str(variant.get('color') or '').strip()
        if usable(colour):
            colours.setdefault(sanmar_colour_alias(colour), colour)
    compact = {}
    for key in colours:
        compact.setdefault(re.sub(r'[^a-z0-9]', '', key), []).append(key)
    for original in images:
        image = dict(original)
        parts = image.get('source_part_ids') or image.get('part_ids') or []
        if isinstance(parts, str):
            try:
                parts = json.loads(parts)
            except (ValueError, TypeError):
                parts = [parts]
        explicit_parts = bool(parts)
        explicit_colour = image.get('source_color') or image.get('color') or image.get('part_color')
        if not style or explicit_parts or usable(explicit_colour):
            if style:
                colour, linked_parts, linked = resolved_links(
                    image, variants, colour_normalizer=sanmar_colour_alias)
                if linked:
                    image.update(source_color=colour, source_part_ids=linked_parts)
            result.append(image)
            continue
        try:
            url = urlsplit(str(image.get('url') or ''))
            filename = unquote(url.path.rsplit('/', 1)[-1])
            stem, extension = filename.rsplit('.', 1)
            port = url.port
        except (ValueError, TypeError):
            result.append(image)
            continue
        tokens = re.split(r'[_\-\s]+', stem.casefold())
        if (url.scheme != 'https' or url.hostname != 'media.sanmarcanada.com'
                or port not in (None, 443) or url.username is not None
                or not url.path.startswith('/catalog/product/')
                or extension.casefold() not in ('jpg', 'jpeg', 'png', 'webp')
                or len(tokens) < 2 or tokens[0] != style):
            result.append(image)
            continue
        matches = set()
        for start in range(1, len(tokens)):
            for end in range(start + 1, min(len(tokens), start + 6) + 1):
                token = ''.join(tokens[start:end])
                matches.update(compact.get(token, []))
        if len(matches) == 1:
            key = next(iter(matches))
            # A compact spelling must identify exactly one catalogue colour.
            if len(compact[re.sub(r'[^a-z0-9]', '', key)]) == 1:
                ids = [str(v.get('variant_sku') or '').strip() for v in variants
                       if sanmar_colour_alias(v.get('color')) == key and usable(v.get('variant_sku'))]
                if ids:
                    image.update(source_color=colours[key], source_part_ids=list(dict.fromkeys(ids)),
                                 association_source='sanmar_exact_product_colour_filename')
        result.append(image)
    return result



def matcher_runtime():
    """Identify the matcher loaded by this worker without exposing server paths."""
    import hashlib
    import marshal
    from types import CodeType
    def portable(code):
        return code.replace(co_filename='media_links.py',
                            co_consts=tuple(portable(value) if isinstance(value, CodeType) else value
                                            for value in code.co_consts))
    digest = hashlib.sha256()
    for function in (colour_key, usable, resolved_links, sanmar_colour_alias, associate_sanmar_images):
        digest.update(marshal.dumps(portable(function.__code__)))
    return {'version': 'generic-colour-prefix-v4', 'code_sha256': digest.hexdigest()}


