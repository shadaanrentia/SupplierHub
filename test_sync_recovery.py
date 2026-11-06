"""Offline ownership, inventory and image matching regression tests."""
import ast
import importlib.util
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent / 'backend'

def load_file(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def extract(name, functions, namespace):
    tree = ast.parse((ROOT / (name + '.py')).read_text(encoding='utf-8'))
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
    exec(compile(ast.Module(body=body, type_ignores=[]), name, 'exec'), namespace)
    return namespace

media = load_file('media_links')
inventory = load_file('inventory_selection')
ns = extract('single_family', {'sku', 'members', 'matched_images'}, {})
extract('multi_family', {'verify_group_destination'}, ns)
extract('single_family', {'verify_owner'}, ns)

class OwnershipTests(unittest.TestCase):
    def family(self, skus=('a', 'b')):
        return {'id': 'family', 'name': 'Renamed marketing title',
                'products': [{'id': str(i), 'sku': sku} for i, sku in enumerate(skus)]}
    def verify(self, family, expected=('a', 'b'), found=None):
        return ns['verify_group_destination'](family, expected, found or {}, None, 'Old title', 1)
    def test_exact_skus_allow_name_change(self):
        self.assertEqual(set(self.verify(self.family())), {'a', 'b'})
    def test_partial_renamed_family_rejected(self):
        with self.assertRaises(ValueError): self.verify(self.family(('a',)))
    def test_foreign_sku_rejected(self):
        with self.assertRaises(ValueError): self.verify(self.family(('a', 'b', 'foreign')))
    def test_cross_family_search_rejected(self):
        with self.assertRaises(ValueError): self.verify(self.family(), found={'a': {'id': 'elsewhere'}})
    def test_duplicate_sku_rejected(self):
        with self.assertRaises(ValueError): self.verify(self.family(('a', 'a')))
    def test_custom_codes_allow_name_change(self):
        family = self.family(('generated1', 'generated2'))
        for item, code in zip(family['products'], ('a', 'b')):
            item['codes'] = [{'type': 'CUSTOM', 'code': code}]
        self.assertEqual(set(self.verify(family)), {'a', 'b'})
    def test_empty_family_rejected(self):
        with self.assertRaises(ValueError): self.verify(self.family(()))

    def test_single_family_rename(self):
        with patch.dict(sys.modules, {'export_safety': SimpleNamespace(export_name=lambda *args: 'Old title')}):
            result = ns['verify_owner'](self.family(), {'product_name': 'Old title', 'supplier_sku': 'style'},
                                        [{'variant_sku': 'a'}, {'variant_sku': 'b'}])
        self.assertEqual(set(result), {'a', 'b'})
    def test_single_family_partial_rename_rejected(self):
        with patch.dict(sys.modules, {'export_safety': SimpleNamespace(export_name=lambda *args: 'Old title')}):
            with self.assertRaises(ValueError):
                ns['verify_owner'](self.family(('a',)), {'product_name': 'Old title', 'supplier_sku': 'style'},
                                   [{'variant_sku': 'a'}, {'variant_sku': 'b'}])

class InventoryTests(unittest.TestCase):
    def verify(self, rows, expected=12):
        return inventory.verify_inventory_records(rows, 'p', 'o', expected)
    def record(self, amount=12, outlet='o'):
        return {'product_id': 'p', 'outlet_id': outlet, 'current_inventory_level': amount}
    def test_exact_stock_passes(self): self.assertTrue(self.verify([self.record()]))
    def test_missing_outlet_rejected(self):
        with self.assertRaisesRegex(ValueError, 'matching_records=0'):
            self.verify([self.record(outlet='other')])
    def test_duplicate_outlet_rejected(self):
        with self.assertRaisesRegex(ValueError, 'matching_records=2'):
            self.verify([self.record(), self.record()])
    def test_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'expected 12, received 13'):
            self.verify([self.record(13)])
    def test_zero_requires_explicit_record(self):
        self.assertTrue(self.verify([self.record(0)], 0))
        with self.assertRaises(ValueError): self.verify([], 0)

class ImageTests(unittest.TestCase):
    def test_all_known_aliases_include_zero_stock_sizes(self):
        cases = [('Charcoal Hthr', 'CharcoalHeather'), ('Extreme Yello', 'ExtremeYellow'),
                 ('Hthr Navy', 'HeatherNavy'), ('Hthr Cardinal', 'HeatherCardinal'),
                 ('Hthr Forest', 'HeatherForest'), ('Hthr Teal', 'HeatherTeal'),
                 ('~Orange', 'Orange'), ('~Silver', 'Silver'), ('Kelly Green', 'KellyGreen')]
        for label, filename in cases:
            with self.subTest(label=label):
                variants = [{'variant_sku': 'a', 'color': label, 'inventory': 0},
                            {'variant_sku': 'b', 'color': label, 'inventory': 20}]
                images = media.associate_sanmar_images([{'url': 'https://media.sanmarcanada.com/catalog/product/a/t/ATC8001L_' + filename + '_Front.jpg'}], variants, 'ATC8001L')
                self.assertEqual(images[0].get('source_part_ids'), ['a', 'b'])
    def test_other_style_not_associated(self):
        result = media.associate_sanmar_images([{'url': 'https://media.sanmarcanada.com/catalog/product/a/ATC5050_Black.jpg'}], [{'variant_sku': 'a', 'color': 'Black'}], 'ATC8001L')
        self.assertFalse(result[0].get('source_part_ids'))
    def test_marker_parts_expand_across_all_sizes(self):
        variants = [{'variant_sku': sku, 'color': colour, 'inventory': 0}
                    for sku, colour in [('23424-1', 'Athletic Grey'), ('23424-2', 'Athletic Grey*'),
                                        ('23424-3', 'Athletic Grey'), ('23424-4', 'Athletic Grey'),
                                        ('23424-5', 'Athletic Grey'), ('23425-1', 'Athletic Grey*'),
                                        ('23426-2', 'Athletic Grey'), ('23427-3', 'Athletic Grey*')]]
        original = {'source_part_ids': '["23424-2"]', 'source_color': 'Athletic Grey*'}
        result = media.associate_sanmar_images([original], variants, 'ATC8001L')[0]
        self.assertEqual(set(result['source_part_ids']), {v['variant_sku'] for v in variants})
        self.assertEqual(original['source_part_ids'], '["23424-2"]')
    def test_verified_colour_only_marker_expands(self):
        variants = [{'variant_sku': 'a', 'color': 'Athletic Grey'},
                    {'variant_sku': 'b', 'color': 'Athletic Grey*'}]
        image = {'source_color': 'Athletic Grey*'}
        self.assertEqual(set(media.associate_sanmar_images([image], variants, 'ATC8001L')[0]['source_part_ids']), {'a', 'b'})
    def test_deep_heather_marker_expands_verified_parts(self):
        variants = [{'variant_sku': '28398-3', 'color': 'Deep Heather'},
                    {'variant_sku': '28398-4', 'color': 'Deep Heather*'},
                    {'variant_sku': '28398-5', 'color': 'Deep Heather'}]
        image = {'source_part_ids': ['28398-4']}
        result = media.associate_sanmar_images([image], variants, 'ATC8001L')[0]
        self.assertEqual(set(result['source_part_ids']), {v['variant_sku'] for v in variants})
    def test_conflicting_part_colour_does_not_expand(self):
        variants = [{'variant_sku': 'a', 'color': 'Black'}, {'variant_sku': 'b', 'color': 'Athletic Grey'}]
        image = {'source_part_ids': ['a'], 'source_color': 'Athletic Grey*'}
        self.assertEqual(media.associate_sanmar_images([image], variants, 'ATC8001L')[0], image)
    def test_unknown_marker_is_not_stripped(self):
        self.assertNotEqual(media.sanmar_colour_alias('Black*'), media.sanmar_colour_alias('Black'))
    def test_default_resolver_preserves_exact_colour_contract(self):
        variants = [{'variant_sku': 'a', 'color': 'Athletic Grey*'},
                    {'variant_sku': 'b', 'color': 'Athletic Grey'}]
        self.assertEqual(media.resolved_links({'source_part_ids': ['a']}, variants)[1], ['a'])

    def test_runtime_fingerprint_present(self):
        result = media.matcher_runtime()
        self.assertEqual(result['version'], 'sanmar-colour-alias-v3')
        self.assertEqual(len(result['code_sha256']), 64)

if __name__ == '__main__': unittest.main()


