from lxml import etree


SOAP_NS = (
    "http://schemas.xmlsoap.org/"
    "soap/envelope/"
)

MEDIA_NS = (
    "http://www.promostandards.org/"
    "WSDL/MediaService/1.0.0/"
)

SHARED_NS = (
    "http://www.promostandards.org/"
    "WSDL/MediaService/1.0.0/"
    "SharedObjects/"
)


NS = {
    "soap": SOAP_NS,
    "media": MEDIA_NS,
    "shared": SHARED_NS,
}


def get_text(
    element,
    path,
):

    child = element.find(
        path,
        namespaces=NS,
    )

    if (
        child is None
        or child.text is None
    ):
        return None

    return child.text.strip()


def get_int(
    element,
    path,
):

    value = get_text(
        element,
        path,
    )

    if value is None:
        return None

    try:
        return int(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


def get_bool(
    element,
    path,
):

    value = get_text(
        element,
        path,
    )

    if value is None:
        return None

    normalized = (
        value.strip().lower()
    )

    if normalized in (
        "true",
        "1",
        "yes",
    ):
        return True

    if normalized in (
        "false",
        "0",
        "no",
    ):
        return False

    return None


def parse_media(
    xml_text: str,
) -> dict:

    root = etree.fromstring(
        xml_text.encode(
            "utf-8"
        )
    )

    # ==========================================
    # SOAP FAULT
    # ==========================================

    fault = root.find(
        ".//soap:Fault",
        namespaces=NS,
    )

    if fault is not None:

        message = fault.findtext(
            "faultstring"
        )

        raise ValueError(
            f"SOAP Fault: "
            f"{message or 'Unknown fault'}"
        )

    # ==========================================
    # RAW MEDIA RECORDS
    # ==========================================

    records = []

    media_elements = (
        root.findall(
            ".//media:MediaContent",
            namespaces=NS,
        )
    )

    for media in media_elements:

        # --------------------------------------
        # Class types
        # --------------------------------------

        class_types = []

        class_elements = (
            media.findall(
                "./media:ClassTypeArray/"
                "media:ClassType",
                namespaces=NS,
            )
        )

        for class_element in (
            class_elements
        ):

            class_types.append({
                "id": get_int(
                    class_element,
                    "media:classTypeId",
                ),

                "name": get_text(
                    class_element,
                    "media:classTypeName",
                ),
            })

        # --------------------------------------
        # Build raw record
        # --------------------------------------

        record = {

            "product_id": (
                get_text(
                    media,
                    "shared:productId",
                )
            ),

            "part_id": (
                get_text(
                    media,
                    "shared:partId",
                )
            ),

            "url": (
                get_text(
                    media,
                    "media:url",
                )
            ),

            "media_type": (
                get_text(
                    media,
                    "shared:mediaType",
                )
            ),

            "class_types": (
                class_types
            ),

            "file_size": (
                get_int(
                    media,
                    "media:fileSize",
                )
            ),

            # IMPORTANT
            "single_part": (
                get_bool(
                    media,
                    "media:singlePart",
                )
            ),

            "change_timestamp": (
                get_text(
                    media,
                    "shared:changeTimeStamp",
                )
            ),
        }

        if record["url"]:

            records.append(
                record
            )

    # ==========================================
    # DEDUPLICATE BY URL
    # ==========================================

    unique_by_url = {}

    for record in records:

        url = record[
            "url"
        ]

        if url not in unique_by_url:

            unique_by_url[url] = {

                "url": (
                    url
                ),

                "media_type": (
                    record.get(
                        "media_type"
                    )
                ),

                "class_types": (
                    record.get(
                        "class_types",
                        [],
                    )
                ),

                "file_size": (
                    record.get(
                        "file_size"
                    )
                ),

                # IMPORTANT:
                # preserve it during
                # deduplication
                "single_part": (
                    record.get(
                        "single_part"
                    )
                ),

                "change_timestamp": (
                    record.get(
                        "change_timestamp"
                    )
                ),

                "part_ids": [],
            }

        part_id = (
            record.get(
                "part_id"
            )
        )

        if (
            part_id
            and part_id
            not in unique_by_url[
                url
            ]["part_ids"]
        ):

            unique_by_url[
                url
            ][
                "part_ids"
            ].append(
                part_id
            )

        # If any repeated record explicitly
        # reports singlePart=True,
        # preserve True.
        if (
            record.get(
                "single_part"
            )
            is True
        ):

            unique_by_url[
                url
            ][
                "single_part"
            ] = True

    unique_media = list(
        unique_by_url.values()
    )

    # ==========================================
    # SUMMARY
    # ==========================================

    return {

        "record_count": (
            len(records)
        ),

        "unique_media_count": (
            len(
                unique_media
            )
        ),

        "records": (
            records
        ),

        "unique_media": (
            unique_media
        ),
    }