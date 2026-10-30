"""Temporary export eligibility; supplier records are never deleted."""
import math


def missing_price(value):
    if value is None or str(value).strip() in ('', '-', '—'): return True
    try: return math.isfinite(float(value)) and float(value) == 0
    except (ValueError, TypeError, OverflowError): return False



def skip_sku(row):
    try:
        zero_stock = (
            row.get("inventory") is not None
            and float(row["inventory"]) == 0
        )
    except (ValueError, TypeError, OverflowError):
        zero_stock = False

    return missing_price(row.get("price")) or zero_stock


def eligible_variants(rows):
    return [dict(row) for row in rows if row.get('is_active') is not False and not skip_sku(row)]
