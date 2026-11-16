from lxml import etree


def local_name(element):
    """Return an XML element's local name, ignoring its namespace."""
    if "}" in element.tag:
        return element.tag.split("}")[-1]
    return element.tag


def direct_child_text(element, child_name):
    """Read a direct child's text without depending on its namespace."""
    for child in element:
        if local_name(child) == child_name:
            if child.text:
                return child.text.strip()
    return None


def parse_sellable_products(xml_text: str) -> dict:
    """
    Parse Athletic Knit PromoStandards ProductSellable response.

    Only products returned by the isSellable=true request are used.
    Preserve exact supplier product IDs and deduplicate the discovery list.
    """
    root = etree.fromstring(xml_text.encode("utf-8"))

    faults = root.xpath("//*[local-name()='Fault']")
    if faults:
        fault_strings = faults[0].xpath(
            ".//*[local-name()='faultstring']/text()"
        )
        message = fault_strings[0] if fault_strings else "Unknown SOAP fault"
        raise ValueError(f"SOAP Fault: {message}")

    service_messages = []
    for element in root.iter():
        if local_name(element) != "ServiceMessage":
            continue
        code = direct_child_text(element, "code")
        description = direct_child_text(element, "description")
        severity = direct_child_text(element, "severity")
        service_messages.append({
            "code": code,
            "description": description,
            "severity": severity,
        })
        if severity and severity.lower() == "error":
            raise ValueError(
                f"PromoStandards API Error {code}: {description}"
            )

    sellable_records = []
    for element in root.iter():
        if local_name(element) != "ProductSellable":
            continue
        product_id = direct_child_text(element, "productId")
        if not product_id:
            continue
        sellable_records.append({"product_id": product_id.strip()})

    unique_product_ids = []
    seen = set()
    for item in sellable_records:
        product_id = item["product_id"]
        if product_id in seen:
            continue
        seen.add(product_id)
        unique_product_ids.append(product_id)

    return {
        "sellable_records": len(sellable_records),
        "unique_products": len(unique_product_ids),
        "products": sellable_records,
        "product_ids": unique_product_ids,
        "service_messages": service_messages,
    }
