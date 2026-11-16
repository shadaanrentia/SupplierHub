from multi_supplier.connector import Athletic


class FakeAthleticClient:
    def __init__(self):
        self.calls = 0

    def get_sellable_products_raw(self):
        self.calls += 1
        return """
        <Envelope>
            <ProductSellable><productId>PRODUCT-A</productId></ProductSellable>
            <ProductSellable><productId>PRODUCT-A</productId></ProductSellable>
            <ProductSellable><productId>PRODUCT-B</productId></ProductSellable>
        </Envelope>
        """


def make_connector():
    from threading import RLock

    connector = Athletic.__new__(Athletic)
    connector.lock = RLock()
    connector.cache = {}
    connector.discovery_limit = 1500
    connector.client = FakeAthleticClient()
    return connector


def test_existing_product_discovery_uses_sellable_products_only():
    connector = make_connector()
    result = connector.get_sellable_products()

    assert result["success"] is True
    assert result["products"] == [
        {"product_id": "PRODUCT-A"},
        {"product_id": "PRODUCT-B"},
    ]
    assert connector.client.calls == 1


def test_product_discovery_respects_discovery_limit():
    connector = make_connector()
    connector.discovery_limit = 1
    result = connector.get_sellable_products()

    assert result["success"] is True
    assert result["products"] == [{"product_id": "PRODUCT-A"}]
    assert connector.client.calls == 1


def test_non_sellable_reconciliation_methods_are_not_exposed():
    connector = make_connector()
    assert not hasattr(connector, "get_non_sellable_products")
    assert not hasattr(connector, "get_sellability_records")


def test_inventory_connector_maps_parsed_part_quantities():
    connector = make_connector()
    connector.client.get_inventory_raw = lambda sku: """
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
      xmlns:shared="http://www.promostandards.org/WSDL/Inventory/2.0.0/SharedObjects/">
      <soap:Body><shared:Inventory>
        <shared:productId>AK-100</shared:productId>
        <shared:PartInventory>
          <shared:partId>AK-100-BLK-M</shared:partId>
          <shared:quantityAvailable><shared:Quantity><shared:value>8</shared:value></shared:Quantity></shared:quantityAvailable>
        </shared:PartInventory>
      </shared:Inventory></soap:Body>
    </soap:Envelope>
    """
    result = connector.get_inventory("AK-100")
    assert result["success"] is True
    assert result["inventory"] == [{
        "part_id": "AK-100-BLK-M",
        "main_part": False,
        "color": None,
        "size": None,
        "quantity_available": 8,
        "uom": None,
        "manufactured_item": False,
        "buy_to_order": False,
        "last_modified": None,
    }]


def test_media_connector_preserves_part_associations():
    connector = make_connector()
    connector.client.get_media_raw = lambda sku: """
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
      xmlns:media="http://www.promostandards.org/WSDL/MediaService/1.0.0/"
      xmlns:shared="http://www.promostandards.org/WSDL/MediaService/1.0.0/SharedObjects/">
      <soap:Body><media:GetMediaContentResponse>
        <media:MediaContent>
          <shared:productId>AK-100</shared:productId>
          <shared:partId>AK-100-BLK-M</shared:partId>
          <media:url>https://cdn.example.test/ak100-black.jpg</media:url>
          <shared:mediaType>Image</shared:mediaType>
        </media:MediaContent>
      </media:GetMediaContentResponse></soap:Body>
    </soap:Envelope>
    """
    result = connector.get_media("AK-100")
    assert result["success"] is True
    assert result["media"] == [{
        "url": "https://cdn.example.test/ak100-black.jpg",
        "media_type": "Image",
        "class_types": [],
        "file_size": None,
        "single_part": None,
        "change_timestamp": None,
        "part_ids": ["AK-100-BLK-M"],
        "type": "Image",
        "source_part_ids": ["AK-100-BLK-M"],
    }]



def test_product_category_preserves_athletic_knit_subcategory():
    connector = make_connector()
    connector.parsed = lambda sku: {
        "name": "Hockey Jersey",
        "description": "Team jersey",
        "brand": "Athletic Knit",
        "category": "Apparel",
        "subcategory": "Hockey Jerseys",
        "variants": [],
    }

    result = connector.get_product("AK-100")

    assert result["success"] is True
    assert result["product"]["category"] == "Apparel > Hockey Jerseys"
