from multi_supplier.product_parser import parse_product


def product_xml(shared_namespace):
    return f"""<?xml version="1.0"?>
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:pd="http://www.promostandards.org/WSDL/ProductDataService/2.0.0/"
        xmlns:shared="{shared_namespace}">
      <soap:Body>
        <pd:GetProductResponse>
          <pd:Product>
            <shared:productId>AK-100</shared:productId>
            <shared:productName>Hockey Jersey</shared:productName>
            <shared:ProductCategory>
              <shared:category>Apparel</shared:category>
              <shared:subCategory>Hockey Jerseys</shared:subCategory>
            </shared:ProductCategory>
          </pd:Product>
        </pd:GetProductResponse>
      </soap:Body>
    </soap:Envelope>"""


def test_parses_parent_and_subcategory_with_promostandards_namespace():
    xml = product_xml(
        "http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/"
    )

    result = parse_product(xml)

    assert result["category"] == "Apparel"
    assert result["subcategory"] == "Hockey Jerseys"


def test_parses_parent_and_subcategory_when_supplier_uses_different_namespace():
    xml = product_xml("urn:athletic-knit:product-data:shared")

    result = parse_product(xml)

    assert result["category"] == "Apparel"
    assert result["subcategory"] == "Hockey Jerseys"


def test_category_values_are_none_when_product_has_no_category():
    xml = """<Product><productId>AK-101</productId><productName>Test</productName></Product>"""

    result = parse_product(xml)

    assert result["category"] is None
    assert result["subcategory"] is None
