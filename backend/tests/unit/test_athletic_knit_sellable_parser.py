import pytest

from multi_supplier.sellable_parser import parse_sellable_products


def make_response(product_ids):
    records = "".join(
        f"""
        <ns2:ProductSellable>
            <ns1:productId>{product_id}</ns1:productId>
        </ns2:ProductSellable>
        """
        for product_id in product_ids
    )
    return f"""
    <SOAP-ENV:Envelope
        xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:ns1="http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/"
        xmlns:ns2="http://www.promostandards.org/WSDL/ProductDataService/2.0.0/">
        <SOAP-ENV:Body>
            <ns2:GetProductSellableResponse>
                <ns2:ProductSellableArray>{records}</ns2:ProductSellableArray>
            </ns2:GetProductSellableResponse>
        </SOAP-ENV:Body>
    </SOAP-ENV:Envelope>
    """


def test_preserves_exact_product_id_with_parentheses():
    result = parse_sellable_products(make_response(["PRODUCT-A(COLOR,SIZE)"]))
    assert result["product_ids"] == ["PRODUCT-A(COLOR,SIZE)"]


def test_preserves_multiple_records_for_same_product():
    result = parse_sellable_products(make_response(["A1375-206"] * 3))
    assert result["sellable_records"] == 3
    assert result["unique_products"] == 1
    assert result["product_ids"] == ["A1375-206"]
    assert result["products"] == [{"product_id": "A1375-206"}] * 3


def test_preserves_multiple_distinct_product_ids_in_order():
    result = parse_sellable_products(make_response([
        "A1375-206", "A1375-207", "A1375-206", "A1375-208"
    ]))
    assert result["product_ids"] == ["A1375-206", "A1375-207", "A1375-208"]


def test_ignores_records_without_product_id():
    xml = """
    <root>
        <ProductSellable><partId>PART-001</partId></ProductSellable>
        <ProductSellable><productId>A1375-206</productId></ProductSellable>
    </root>
    """
    result = parse_sellable_products(xml)
    assert result["sellable_records"] == 1
    assert result["product_ids"] == ["A1375-206"]


def test_returns_existing_result_structure():
    result = parse_sellable_products(make_response(["A1375-206"]))
    assert set(result) == {
        "sellable_records", "unique_products", "products",
        "product_ids", "service_messages"
    }


def test_raises_on_soap_fault():
    xml = """
    <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
        <SOAP-ENV:Body><SOAP-ENV:Fault>
            <faultstring>Invalid credentials</faultstring>
        </SOAP-ENV:Fault></SOAP-ENV:Body>
    </SOAP-ENV:Envelope>
    """
    with pytest.raises(ValueError, match="Invalid credentials"):
        parse_sellable_products(xml)


def test_raises_on_promostandards_error_message():
    xml = """
    <root><ServiceMessage><code>100</code>
    <description>Invalid request</description><severity>Error</severity>
    </ServiceMessage></root>
    """
    with pytest.raises(ValueError, match="Invalid request"):
        parse_sellable_products(xml)


def test_preserves_service_messages():
    xml = """
    <root>
        <ServiceMessage><code>200</code>
        <description>Informational message</description>
        <severity>Warning</severity></ServiceMessage>
        <ProductSellable><productId>A1375-206</productId></ProductSellable>
    </root>
    """
    result = parse_sellable_products(xml)
    assert result["service_messages"] == [{
        "code": "200",
        "description": "Informational message",
        "severity": "Warning",
    }]
