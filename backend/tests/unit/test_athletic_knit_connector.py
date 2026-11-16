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
