from lxml import etree


SOAP_NS = (
    "http://schemas.xmlsoap.org/soap/envelope/"
)

INVENTORY_NS = (
    "http://www.promostandards.org/"
    "WSDL/Inventory/2.0.0/"
)

SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/Inventory/2.0.0/SharedObjects/"
)


NS = {
    "soap": SOAP_NS,
    "inv": INVENTORY_NS,
    "shared": SHARED_NS,
}


def get_text(element, xpath, default=None):

    found = element.find(
        xpath,
        namespaces=NS
    )

    if found is None:
        return default

    if found.text is None:
        return default

    value = found.text.strip()

    return value if value else default


def get_bool(element, xpath, default=False):

    value = get_text(
        element,
        xpath
    )

    if value is None:
        return default

    return value.lower() == "true"


def get_int(element, xpath, default=0):

    value = get_text(
        element,
        xpath
    )

    if value is None:
        return default

    try:
        return int(float(value))

    except (ValueError, TypeError):
        return default


def parse_inventory(xml_text: str) -> dict:
    """
    Parse Athletic Knit PromoStandards
    Inventory 2.0 GetInventoryLevels response.
    """

    root = etree.fromstring(
        xml_text.encode("utf-8")
    )

    # ----------------------------
    # SOAP fault
    # ----------------------------

    fault = root.find(
        ".//soap:Fault",
        namespaces=NS
    )

    if fault is not None:

        fault_string = get_text(
            fault,
            "faultstring",
            "Unknown SOAP fault"
        )

        raise ValueError(
            f"SOAP Fault: {fault_string}"
        )

    # ----------------------------
    # Inventory root
    # ----------------------------

    inventory_element = root.find(
        ".//shared:Inventory",
        namespaces=NS
    )

    if inventory_element is None:

        raise ValueError(
            "No Inventory element found "
            "in Athletic Knit response."
        )

    result = {
        "product_id": get_text(
            inventory_element,
            "shared:productId"
        ),

        "items": []
    }

    # ----------------------------
    # Part inventory
    # ----------------------------

    for part in inventory_element.findall(
        ".//shared:PartInventory",
        namespaces=NS
    ):

        item = {

            "part_id": get_text(
                part,
                "shared:partId"
            ),

            "main_part": get_bool(
                part,
                "shared:mainPart"
            ),

            "color": get_text(
                part,
                "shared:partColor"
            ),

            "size": get_text(
                part,
                "shared:labelSize"
            ),

            "quantity_available": get_int(
                part,
                "shared:quantityAvailable/"
                "shared:Quantity/"
                "shared:value",
                None
            ),

            "uom": get_text(
                part,
                "shared:quantityAvailable/"
                "shared:Quantity/"
                "shared:uom"
            ),

            "manufactured_item": get_bool(
                part,
                "shared:manufacturedItem"
            ),

            "buy_to_order": get_bool(
                part,
                "shared:buyToOrder"
            ),

            "last_modified": get_text(
                part,
                "shared:lastModified"
            ),
        }

        if item["part_id"]:
            result["items"].append(
                item
            )

    result["total_quantity"] = sum(
        item["quantity_available"] or 0
        for item in result["items"]
    )

    return result