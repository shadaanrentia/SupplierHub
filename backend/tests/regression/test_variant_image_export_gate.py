import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from media_links import image_matches_variant, prepare_variant_images
from product_readiness import evaluate


class VariantImageExportGateTests(unittest.TestCase):
    def setUp(self):
        self.variants = [
            {"id": "v1", "variant_sku": "STYLE-1", "color": "True Navy", "size": "S", "price": 8.0, "inventory": 4},
            {"id": "v2", "variant_sku": "STYLE-2", "color": "True Navy", "size": "M", "price": 8.0, "inventory": 0},
            {"id": "v3", "variant_sku": "STYLE-3", "color": "White", "size": "S", "price": 8.0, "inventory": 2},
        ]
        self.product = {"product_name": "Test Tee", "supplier_sku": "TS445", "base_price": 8.0}

    def test_exact_colour_association_covers_every_size_in_colour(self):
        images, missing = prepare_variant_images(
            [{"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_true_navy_front.jpg", "media_type": "image"}],
            self.variants, "TS445")
        self.assertEqual(missing, ["STYLE-3"])
        self.assertTrue(image_matches_variant(images[0], self.variants[0]))
        self.assertTrue(image_matches_variant(images[0], self.variants[1]))

    def test_explicit_part_association_does_not_fall_back_to_wrong_colour(self):
        image = {"url": "https://example.com/navy.jpg", "media_type": "image",
                 "source_part_ids": ["OTHER-SKU"], "source_color": "True Navy"}
        self.assertFalse(image_matches_variant(image, self.variants[0]))

    def test_missing_variant_image_blocks_readiness(self):
        images = [{"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_true_navy_front.jpg", "media_type": "image"}]
        state = evaluate(self.product, self.variants, images, [], "category-1")
        self.assertFalse(state["is_valid"])
        self.assertTrue(any("Verified individual images" in e for e in state["validation_errors"]))

    def test_all_variant_images_allow_readiness(self):
        images = [
            {"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_true_navy_front.jpg", "media_type": "image"},
            {"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_white_front.jpg", "media_type": "image"},
        ]
        state = evaluate(self.product, self.variants, images, [], "category-1")
        self.assertTrue(state["is_valid"], state["validation_errors"])

    def test_existing_zero_stock_variant_is_retained_and_requires_image(self):
        product = dict(self.product, lightspeed_product_id="existing-destination")
        images = [
            {"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_true_navy_front.jpg", "media_type": "image"},
            {"url": "https://media.sanmarcanada.com/catalog/product/t/s/ts445_white_front.jpg", "media_type": "image"},
        ]
        state = evaluate(product, self.variants, images, [], "category-1")
        self.assertTrue(any(v["variant_sku"] == "STYLE-2" for v in state["variants"]))
        self.assertTrue(state["is_valid"], state["validation_errors"])

    def test_new_zero_stock_variant_is_not_included(self):
        state = evaluate(self.product, [dict(self.variants[1])], [], [], "category-1")
        self.assertEqual(state["variants"], [])
        self.assertTrue(state["excluded_from_queue"])


if __name__ == "__main__":
    unittest.main()
