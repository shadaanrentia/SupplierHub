from multi_supplier.connector import Athletic
from multi_supplier.pricing_parser import parse_configuration_and_pricing


SAMPLE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:ns1="http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/SharedObjects/"
 xmlns:ns2="http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <SOAP-ENV:Body><ns2:GetConfigurationAndPricingResponse><ns2:Configuration>
  <ns2:PartArray>
   <ns2:Part><ns1:partId>B1715-414_A_2XL</ns1:partId><ns2:PartPriceArray>
    <ns2:PartPrice><ns2:minQuantity>1</ns2:minQuantity><ns2:price>12.5</ns2:price><ns2:discountCode>A</ns2:discountCode><ns2:priceUom>EA</ns2:priceUom></ns2:PartPrice>
    <ns2:PartPrice><ns2:minQuantity>100</ns2:minQuantity><ns2:price>11.88</ns2:price><ns2:discountCode>A</ns2:discountCode><ns2:priceUom>EA</ns2:priceUom></ns2:PartPrice>
    <ns2:PartPrice><ns2:minQuantity>500</ns2:minQuantity><ns2:price>10.5</ns2:price><ns2:discountCode>A</ns2:discountCode><ns2:priceUom>EA</ns2:priceUom></ns2:PartPrice>
   </ns2:PartPriceArray></ns2:Part>
   <ns2:Part><ns1:partId>B1715-414_A_3XL</ns1:partId><ns2:PartPriceArray>
    <ns2:PartPrice><ns2:minQuantity>1</ns2:minQuantity><ns2:price>14.5</ns2:price></ns2:PartPrice>
   </ns2:PartPriceArray></ns2:Part>
  </ns2:PartArray><ns1:currency>CAD</ns1:currency><ns1:priceType>Customer</ns1:priceType>
 </ns2:Configuration></ns2:GetConfigurationAndPricingResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def test_pricing_parser_maps_part_ids_and_all_quantity_breaks():
    parsed = parse_configuration_and_pricing(SAMPLE)

    assert parsed["currency"] == "CAD"
    assert parsed["price_type"] == "Customer"
    assert parsed["pricing"] == [
        {
            "part_id": "B1715-414_A_2XL",
            "prices": [
                {"min_quantity": 1, "price": 12.5, "discount_code": "A", "price_uom": "EA"},
                {"min_quantity": 100, "price": 11.88, "discount_code": "A", "price_uom": "EA"},
                {"min_quantity": 500, "price": 10.5, "discount_code": "A", "price_uom": "EA"},
            ],
        },
        {
            "part_id": "B1715-414_A_3XL",
            "prices": [{"min_quantity": 1, "price": 14.5}],
        },
    ]


def test_pricing_parser_ignores_invalid_price_tiers():
    xml = SAMPLE.replace("<ns2:price>10.5</ns2:price>", "<ns2:price>NaN</ns2:price>")
    parsed = parse_configuration_and_pricing(xml)
    first = parsed["pricing"][0]["prices"]
    assert [tier["min_quantity"] for tier in first] == [1, 100]


def test_athletic_connector_returns_pricing_service_tiers():
    connector = Athletic.__new__(Athletic)
    connector.pricing_parsed = lambda sku: parse_configuration_and_pricing(SAMPLE)

    result = connector.get_pricing("B1715-414")

    assert result["success"] is True
    assert result["currency"] == "CAD"
    assert result["price_type"] == "Customer"
    assert result["pricing"][0]["part_id"] == "B1715-414_A_2XL"
    assert result["pricing"][0]["prices"][0]["price"] == 12.5
