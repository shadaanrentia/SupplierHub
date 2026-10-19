"""Supplier-provided associations only; never infer colour from filenames or SKU prefixes."""
import json
import re


def usable(value):
    return str(value or '').strip().casefold() not in ('', 'na', 'n/a', 'none', 'null', 'not applicable')


def colour_key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


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


def resolved_links(item, variants):
    parts=item.get('part_ids') or item.get('partIds') or item.get('source_part_ids') or []
    if not parts and item.get('part_id'):parts=[item['part_id']]
    if isinstance(parts,str):
        try: parsed=json.loads(parts)
        except (ValueError,TypeError):parsed=[parts]
        parts=parsed if isinstance(parsed,list) else [parts]
    parts=list(dict.fromkeys(str(x).strip() for x in parts if usable(x))) if isinstance(parts,list) else []
    colour=str(item.get('color') or item.get('source_color') or item.get('part_color') or '').strip()
    if not usable(colour): colour=''
    by_sku={str(v.get('variant_sku') or '').strip().casefold():v for v in variants}
    matched=[by_sku[p.casefold()] for p in parts if p.casefold() in by_sku]
    known_colours={colour_key(v.get('color')) for v in matched if colour_key(v.get('color'))}
    if not colour and len(known_colours)==1:
        colour=next(v['color'] for v in matched if colour_key(v.get('color')))
    if colour and known_colours and known_colours!={colour_key(colour)}:
        # Contradictory metadata cannot safely identify a variant image.
        return '',[],False
    # Expand only a verified, unambiguous colour association to all of its sizes.
    if colour and (not known_colours or known_colours=={colour_key(colour)}):
        same=[str(v['variant_sku']) for v in variants if colour_key(v.get('color'))==colour_key(colour)]
        parts=list(dict.fromkeys(parts+same))
    return colour,parts,bool(any(p.casefold() in by_sku for p in parts))
