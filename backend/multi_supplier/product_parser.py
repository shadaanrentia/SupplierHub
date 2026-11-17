from lxml import etree


PRODUCT_NS = (
    "http://www.promostandards.org/"
    "WSDL/ProductDataService/2.0.0/"
)

SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/ProductDataService/2.0.0/SharedObjects/"
)

SOAP_NS = (
    "http://schemas.xmlsoap.org/soap/envelope/"
)


NS = {
    "soap": SOAP_NS,
    "pd": PRODUCT_NS,
    "shared": SHARED_NS,
}


def _local_name(element):
    """Return an XML element's local name regardless of its namespace."""
    try:
        return etree.QName(element).localname.casefold()
    except (TypeError, ValueError):
        return ""


def _first_by_local_name(element, *names):
    wanted = {name.casefold() for name in names}
    return next(
        (node for node in element.iter() if _local_name(node) in wanted),
        None,
    )


def _text_by_local_name(element, *names):
    found = _first_by_local_name(element, *names)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def get_text(element, xpath, default=None):
    """
    Safely retrieve text from an XML element.
    """

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


def get_int(element, xpath, default=None):
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


def get_float(element, xpath, default=None):
    value = get_text(
        element,
        xpath
    )

    if value is None:
        return default

    try:
        return float(value)

    except (ValueError, TypeError):
        return default


def parse_product(xml_text: str) -> dict:
    """
    Parse Athletic Knit PromoStandards
    ProductData 2.0 GetProduct response.
    """

    root = etree.fromstring(
        xml_text.encode("utf-8")
    )

    # -----------------------------------------
    # Check SOAP fault
    # -----------------------------------------

    fault = _first_by_local_name(root, "Fault")

    if fault is not None:

        fault_string = _text_by_local_name(fault, "faultstring") or "Unknown SOAP fault"

        raise ValueError(
            f"SOAP Fault: {fault_string}"
        )

    # -----------------------------------------
    # Find Product
    # -----------------------------------------

    product = _first_by_local_name(root, "Product")

    if product is None:
        raise ValueError(
            "No Product element found in "
            "Athletic Knit response."
        )

    result = {
        "supplier_product_id": get_text(
            product,
            "shared:productId"
        ),

        "name": get_text(
            product,
            "shared:productName"
        ),

        "description": get_text(
            product,
            "shared:description"
        ),

        "brand": get_text(
            product,
            "shared:productBrand"
        ),

        "primary_image_url": get_text(
            product,
            "shared:primaryImageUrl"
        ),

        "category": None,
        "subcategory": None,

        "currency": None,

        "is_closeout": get_bool(
            product,
            "shared:isCloseout"
        ),

        "last_change_date": get_text(
            product,
            "pd:lastChangeDate"
        ),

        "creation_date": get_text(
            product,
            "pd:creationDate"
        ),

        "keywords": [],

        "variants": [],

        "prices": [],

        "fob_points": []
    }

    # -----------------------------------------
    # Keywords
    # -----------------------------------------

    for keyword in product.findall(
        ".//shared:ProductKeyword/shared:keyword",
        namespaces=NS
    ):

        if keyword.text:
            result["keywords"].append(
                keyword.text.strip()
            )

    # -----------------------------------------
    # Category
    # -----------------------------------------

    # Supplier responses are not always consistent about namespace URI or
    # prefixes. Match category fields by XML local name so a namespace
    # variation cannot silently discard the subcategory.
    category_element = _first_by_local_name(product, "ProductCategory")

    if category_element is not None:
        result["category"] = _text_by_local_name(
            category_element, "category", "categoryName"
        )
        result["subcategory"] = _text_by_local_name(
            category_element, "subCategory", "subcategory", "subCategoryName"
        )

    # -----------------------------------------
    # Product Parts / Variants
    # -----------------------------------------

    for part in product.findall(
        ".//pd:ProductPart",
        namespaces=NS
    ):

        variant = {
            "part_id": get_text(
                part,
                "shared:partId"
            ),

            "description": get_text(
                part,
                "shared:description"
            ),

            "country_of_origin": get_text(
                part,
                "shared:countryOfOrigin"
            ),

            "color": get_text(
                part,
                ".//shared:colorName"
            ),

            "apparel_style": get_text(
                part,
                ".//shared:apparelStyle"
            ),

            "size": get_text(
                part,
                ".//shared:labelSize"
            ),

            "lead_time": get_int(
                part,
                "pd:leadTime"
            ),

            "is_rush_service": get_bool(
                part,
                "shared:isRushService"
            ),

            "is_closeout": get_bool(
                part,
                "shared:isCloseout"
            ),

            "effective_date": get_text(
                part,
                "shared:effectiveDate"
            ),

            "end_date": get_text(
                part,
                "shared:endDate"
            ),
        }

        if variant["part_id"]:
            result["variants"].append(
                variant
            )

    # -----------------------------------------
    # Prices
    # -----------------------------------------

    currencies = set()

    price_groups = product.findall(
        ".//shared:ProductPriceGroup",
        namespaces=NS
    )

    for group in price_groups:

        part_id = get_text(
            group,
            "shared:groupName"
        )

        currency = get_text(
            group,
            "shared:currency"
        )

        if currency:
            currencies.add(currency)

        price_elements = group.findall(
            ".//shared:ProductPrice",
            namespaces=NS
        )

        for price_element in price_elements:

            price = {
                "part_id": part_id,

                "quantity_min": get_int(
                    price_element,
                    "shared:quantityMin",
                    1
                ),

                "quantity_max": get_int(
                    price_element,
                    "shared:quantityMax"
                ),

                "price": get_float(
                    price_element,
                    "shared:price",
                    0.0
                ),

                "currency": currency
            }

            result["prices"].append(
                price
            )

    if currencies:
        result["currency"] = sorted(
            currencies
        )[0]

    # -----------------------------------------
    # FOB
    # -----------------------------------------

    for fob in product.findall(
        ".//shared:FobPoint",
        namespaces=NS
    ):

        result["fob_points"].append({
            "id": get_text(
                fob,
                "shared:fobId"
            ),

            "city": get_text(
                fob,
                "shared:fobCity"
            ),

            "state": get_text(
                fob,
                "shared:fobState"
            ),

            "postal_code": get_text(
                fob,
                "shared:fobPostalCode"
            ),

            "country": get_text(
                fob,
                "shared:fobCountry"
            )
        })

    # -----------------------------------------
    # Attach matching prices to variants
    # -----------------------------------------

    price_lookup = {}

    for price in result["prices"]:
        part_id = price["part_id"]

        if not part_id:
            continue

        price_lookup.setdefault(
            part_id,
            []
        ).append(price)

    for variant in result["variants"]:

        variant["prices"] = price_lookup.get(
            variant["part_id"],
            []
        )

    return result