import pytest

from multi_supplier.inventory_parser import parse_inventory


def response(values):
    parts = "".join(
        f"""
        <shared:PartInventory>
            <shared:partId>{sku}</shared:partId>
            <shared:partColor>Royal</shared:partColor>
            <shared:labelSize>{size}</shared:labelSize>
            <shared:quantityAvailable>
                <shared:Quantity><shared:value>{qty}</shared:value><shared:uom>EA</shared:uom></shared:Quantity>
            </shared:quantityAvailable>
        </shared:PartInventory>
        """
        for sku, size, qty in values
    )
    return f"""
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
      xmlns:inv="http://www.promostandards.org/WSDL/Inventory/2.0.0/"
      xmlns:shared="http://www.promostandards.org/WSDL/Inventory/2.0.0/SharedObjects/">
      <soap:Body><inv:GetInventoryLevelsResponse><shared:Inventory>
        <shared:productId>AK-100</shared:productId>{parts}
      </shared:Inventory></inv:GetInventoryLevelsResponse></soap:Body>
    </soap:Envelope>
    """


def test_parses_inventory_by_exact_part_sku_and_sums_quantities():
    result = parse_inventory(response([
        ("AK-100-BLK-S", "S", "12"),
        ("AK-100-BLK-M", "M", "0"),
        ("AK-100-BLK-L", "L", "7"),
    ]))
    assert result["product_id"] == "AK-100"
    assert [row["part_id"] for row in result["items"]] == [
        "AK-100-BLK-S", "AK-100-BLK-M", "AK-100-BLK-L"
    ]
    assert [row["quantity_available"] for row in result["items"]] == [12, 0, 7]
    assert result["total_quantity"] == 19


@pytest.mark.parametrize("invalid", ["1.5", "unknown", "-2"])
def test_does_not_truncate_or_accept_invalid_inventory(invalid):
    result = parse_inventory(response([("AK-100-S", "S", invalid)]))
    assert result["items"][0]["quantity_available"] is None


def test_raises_on_soap_fault():
    xml = """
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body><soap:Fault><faultstring>Bad credentials</faultstring></soap:Fault></soap:Body>
    </soap:Envelope>
    """
    with pytest.raises(ValueError, match="Bad credentials"):
        parse_inventory(xml)


def test_rejects_response_without_inventory():
    with pytest.raises(ValueError, match="No Inventory element"):
        parse_inventory("<root/>")
