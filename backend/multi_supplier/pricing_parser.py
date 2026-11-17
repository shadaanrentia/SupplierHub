"""Parser for PromoStandards Pricing and Configuration responses."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _child_text(element, name):
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return None


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def parse_configuration_and_pricing(xml_text: str) -> dict:
    """Return currency, price type, and quantity tiers grouped by supplier part ID.

    The supplier response uses Part/PartPriceArray/PartPrice. Invalid or
    non-positive prices are omitted so they cannot overwrite a valid stored cost.
    """
    root = ET.fromstring(xml_text)
    configuration = next(
        (node for node in root.iter() if _local_name(node.tag) == "Configuration"),
        None,
    )
    if configuration is None:
        fault = next((node for node in root.iter() if _local_name(node.tag) in {"faultstring", "ErrorMessage"}), None)
        detail = (fault.text or "").strip() if fault is not None else "Configuration element missing"
        raise ValueError(f"Invalid Athletic Knit pricing response: {detail}")

    currency = _child_text(configuration, "currency")
    price_type = _child_text(configuration, "priceType")
    pricing = []

    for part in configuration.iter():
        if _local_name(part.tag) != "Part":
            continue
        part_id = _child_text(part, "partId")
        if not part_id:
            continue

        tiers = []
        for price_node in part.iter():
            if _local_name(price_node.tag) != "PartPrice":
                continue
            min_quantity_text = _child_text(price_node, "minQuantity")
            price = _number(_child_text(price_node, "price"))
            try:
                min_quantity = int(min_quantity_text)
            except (TypeError, ValueError):
                continue
            if min_quantity < 1 or price is None:
                continue
            tier = {"min_quantity": min_quantity, "price": price}
            discount_code = _child_text(price_node, "discountCode")
            price_uom = _child_text(price_node, "priceUom")
            if discount_code:
                tier["discount_code"] = discount_code
            if price_uom:
                tier["price_uom"] = price_uom
            tiers.append(tier)

        tiers.sort(key=lambda item: item["min_quantity"])
        if tiers:
            pricing.append({"part_id": part_id, "prices": tiers})

    return {"currency": currency, "price_type": price_type, "pricing": pricing}
