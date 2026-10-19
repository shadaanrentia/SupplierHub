from lxml import etree


SOAP_NS = (
    "http://schemas.xmlsoap.org/soap/envelope/"
)


def local_name(element):

    if "}" in element.tag:
        return element.tag.split("}")[-1]

    return element.tag


def direct_child_text(
    element,
    child_name
):

    for child in element:

        if local_name(child) == child_name:

            if child.text:
                return child.text.strip()

    return None


def parse_sellable_products(
    xml_text: str
) -> dict:

    root = etree.fromstring(
        xml_text.encode("utf-8")
    )

    # ==========================================
    # SOAP FAULT
    # ==========================================

    faults = root.xpath(
        "//*[local-name()='Fault']"
    )

    if faults:

        fault_strings = faults[0].xpath(
            ".//*[local-name()='faultstring']/text()"
        )

        message = (
            fault_strings[0]
            if fault_strings
            else "Unknown SOAP fault"
        )

        raise ValueError(
            f"SOAP Fault: {message}"
        )

    # ==========================================
    # PROMOSTANDARDS SERVICE MESSAGES
    # ==========================================

    service_messages = []

    for element in root.iter():

        if local_name(element) != "ServiceMessage":
            continue

        code = direct_child_text(
            element,
            "code"
        )

        description = direct_child_text(
            element,
            "description"
        )

        severity = direct_child_text(
            element,
            "severity"
        )

        message = {
            "code": code,
            "description": description,
            "severity": severity
        }

        service_messages.append(
            message
        )

        if (
            severity
            and severity.lower() == "error"
        ):
            raise ValueError(
                f"PromoStandards API Error "
                f"{code}: {description}"
            )

    # ==========================================
    # PRODUCT SELLABLE RECORDS
    # ==========================================

    sellable_records = []

    for element in root.iter():

        if (
            local_name(element)
            != "ProductSellable"
        ):
            continue

        product_id = direct_child_text(
            element,
            "productId"
        )

        part_id = direct_child_text(
            element,
            "partId"
        )

        line_name = direct_child_text(
            element,
            "lineName"
        )

        if not product_id:
            continue

        product_id = product_id.strip()

        # Supplier compatibility:
        # Some APIs may return
        # PRODUCT(COLOR,SIZE,...)
        if "(" in product_id:

            product_id = (
                product_id
                .split("(")[0]
                .strip()
            )

        sellable_records.append({
            "product_id": product_id,
            "part_id": part_id,
            "line_name": line_name
        })

    # ==========================================
    # UNIQUE PRODUCT IDS
    # ==========================================

    unique_product_ids = []

    seen = set()

    for item in sellable_records:

        product_id = (
            item["product_id"]
        )

        if product_id in seen:
            continue

        seen.add(product_id)

        unique_product_ids.append(
            product_id
        )

    return {
        "sellable_records": len(
            sellable_records
        ),

        "unique_products": len(
            unique_product_ids
        ),

        "products": (
            sellable_records
        ),

        "product_ids": (
            unique_product_ids
        ),

        "service_messages": (
            service_messages
        )
    }