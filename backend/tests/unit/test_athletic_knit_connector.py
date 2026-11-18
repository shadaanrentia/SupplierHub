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
    connector.parsed = lambda sku: {}
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
        "type": "image",
        "source_part_ids": ["AK-100-BLK-M"],
        "is_primary": False,
    }]



def test_media_connector_uses_media_service_when_product_data_fails():
    connector = make_connector()
    def unavailable_product_data(sku):
        raise RuntimeError("ProductData temporarily unavailable")
    connector.parsed = unavailable_product_data
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
    assert [item["url"] for item in result["media"]] == [
        "https://cdn.example.test/ak100-black.jpg"
    ]


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
    # Parent and child are intentionally stored separately for the
    # supplier-wide category hierarchy and Products page fields.
    assert result["product"]["category"] == "Apparel"
    assert result["product"]["subcategory"] == "Hockey Jerseys"


def test_product_title_has_athletic_knit_prefix_and_default_brand():
    connector = make_connector()
    connector.parsed = lambda sku: {
        "name": "Hockey Jersey",
        "description": "Team jersey",
        "brand": None,
        "category": "Apparel",
        "subcategory": "Hockey Jerseys",
        "variants": [],
    }

    result = connector.get_product("AK-100")

    assert result["success"] is True
    assert result["product"]["product_name"] == "Athletic Knit Hockey Jersey"
    assert result["product"]["brand"] == "Athletic Knit"


def test_product_title_does_not_duplicate_athletic_knit_prefix():
    connector = make_connector()
    connector.parsed = lambda sku: {
        "name": "Athletic Knit Hockey Jersey",
        "description": "Team jersey",
        "brand": "Athletic Knit",
        "category": "Apparel",
        "subcategory": "Hockey Jerseys",
        "variants": [],
    }

    result = connector.get_product("AK-100")

    assert result["success"] is True
    assert result["product"]["product_name"] == "Athletic Knit Hockey Jersey"



def test_media_connector_includes_product_data_primary_image_without_duplicate_urls():
    connector = make_connector()
    connector.parsed = lambda sku: {
        "primary_image_url": "https://cdn.example.test/ak100-primary.jpg",
    }
    connector.client.get_media_raw = lambda sku: """
    <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
      xmlns:media="http://www.promostandards.org/WSDL/MediaService/1.0.0/"
      xmlns:shared="http://www.promostandards.org/WSDL/MediaService/1.0.0/SharedObjects/">
      <soap:Body><media:GetMediaContentResponse>
        <media:MediaContent>
          <shared:productId>AK-100</shared:productId>
          <media:url>https://cdn.example.test/ak100-front.jpg</media:url>
          <shared:mediaType>Image</shared:mediaType>
        </media:MediaContent>
        <media:MediaContent>
          <shared:productId>AK-100</shared:productId>
          <media:url>https://cdn.example.test/ak100-primary.jpg</media:url>
          <shared:mediaType>Image</shared:mediaType>
        </media:MediaContent>
        <media:MediaContent>
          <shared:productId>AK-100</shared:productId>
          <media:url>https://cdn.example.test/ak100-back.jpg</media:url>
          <shared:mediaType>Image</shared:mediaType>
        </media:MediaContent>
      </media:GetMediaContentResponse></soap:Body>
    </soap:Envelope>
    """

    result = connector.get_media("AK-100")

    assert result["success"] is True
    assert [item["url"] for item in result["media"]] == [
        "https://cdn.example.test/ak100-primary.jpg",
        "https://cdn.example.test/ak100-front.jpg",
        "https://cdn.example.test/ak100-back.jpg",
    ]
    assert result["media"][0]["is_primary"] is True
    assert sum(item["url"].endswith("ak100-primary.jpg") for item in result["media"]) == 1
