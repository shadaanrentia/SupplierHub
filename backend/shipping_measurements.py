"""Verified piece measurements only; no carton, image or garment-chart inference."""
import json
import math
import os
import logging
from functools import lru_cache


@lru_cache(maxsize=1)
def warn_unknown_bulk_unit():
    logging.getLogger('shipping_measurements').warning(
        'SanMar bulk weight skipped: its unit is unconfirmed. Price, inventory and images may continue. '
        'After confirming the supplier unit, set SANMAR_BULK_WEIGHT_UNIT and restart; category defaults are used when configured; otherwise existing Lightspeed weights are retained.'
    )


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def unit(value, dimension=False):
    value = str(value or '').strip().upper()
    aliases = {'LBS': 'LB', 'POUND': 'LB', 'POUNDS': 'LB', 'GRAMS': 'G',
               'KILOGRAMS': 'KG', 'INCHES': 'IN', 'INCH': 'IN'}
    value = aliases.get(value, value)
    allowed = {'IN', 'CM', 'MM', 'YD'} if dimension else {'CT', 'G', 'OZ', 'LB', 'KG'}
    return value if value in allowed else None


def source_measurements(variant):
    explicit = variant.get('shipping_measurements') or variant.get('measurements') or {}
    if isinstance(explicit, str):
        explicit = json.loads(explicit)
    if not isinstance(explicit, dict):
        raise ValueError('Invalid shipping measurements for ' + str(variant.get('variant_sku')))
    metadata = variant.get('bulk_metadata') or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        metadata = {}
    # Bulk rows are per-piece and must match this exact source variant.
    variant_sku = str(variant.get('variant_sku') or variant.get('sku') or '').strip().casefold()
    if not variant_sku or str(metadata.get('product_id') or '').strip().casefold() != variant_sku:
        metadata = {}
    raw = metadata.get('raw_fields') or {}
    if not isinstance(raw, dict):
        raw = {}
    result = {}
    weight = positive(explicit.get('weight'))
    weight_unit = unit(explicit.get('weight_unit'))
    if weight is not None and not weight_unit:
        raise ValueError('Shipping weight requires a verified weight_unit for ' + variant_sku)
    if weight is None:
        weight = positive(metadata.get('weight') or raw.get('weight'))
        if weight is not None:
            weight_unit = unit(metadata.get('weight_unit') or raw.get('weightUnit') or raw.get('weightUom') or os.getenv('SANMAR_BULK_WEIGHT_UNIT'))
            if not weight_unit:
                warn_unknown_bulk_unit()
                weight = None
    if weight is not None:
        result.update(weight=weight, weight_unit=weight_unit)
    # Only an explicit shipping measurement object may supply parcel dimensions.
    # BulkData does not supply these; media width/height and size charts are unrelated.
    dimensions = {name: positive(explicit.get(name)) for name in ('dimensions_length', 'dimensions_width', 'dimensions_height')}
    if any(v is not None for v in dimensions.values()):
        dimensions_unit = unit(explicit.get('dimensions_unit'), dimension=True)
        if not all(v is not None for v in dimensions.values()) or not dimensions_unit:
            raise ValueError('Shipping dimensions require positive length, width, height and a verified dimensions_unit for ' + variant_sku)
        result.update(dimensions, dimensions_unit=dimensions_unit)
    fallback = variant.get('category_shipping') or {}
    if result.get('weight') is None and positive(fallback.get('weight_lb')):
        result.update(weight=positive(fallback['weight_lb']),weight_unit='LB')
    if not any(k.startswith('dimensions_') for k in result) and all(positive(fallback.get(k)) for k in ('length_in','width_in','height_in')):
        result.update(dimensions_length=positive(fallback['length_in']),dimensions_width=positive(fallback['width_in']),dimensions_height=positive(fallback['height_in']),dimensions_unit='IN')
    # Export shipping measurements in the store's requested units.
    if result.get('weight') is not None:
        factors={'LB':1,'KG':2.2046226218487757,'G':0.0022046226218487757,'OZ':0.0625,'CT':0.0004409245243697552}
        result['weight']=round(result['weight']*factors[result['weight_unit']],6);result['weight_unit']='LB'
    if result.get('dimensions_unit'):
        factors={'IN':1,'CM':1/2.54,'MM':1/25.4,'YD':36}
        factor=factors[result['dimensions_unit']]
        for key in ('dimensions_length','dimensions_width','dimensions_height'):result[key]=round(result[key]*factor,6)
        result['dimensions_unit']='IN'
    return result


def measurements_match(remote, desired):
    if not isinstance(remote, dict):
        return False
    for key, value in desired.items():
        if key.endswith('_unit'):
            if str(remote.get(key) or '').upper() != value:
                return False
        else:
            current = positive(remote.get(key))
            if current is None or not math.isclose(current, value, rel_tol=1e-6, abs_tol=1e-7):
                return False
    return True
