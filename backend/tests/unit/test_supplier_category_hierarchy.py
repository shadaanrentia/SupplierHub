from multi_supplier.connector import category_fields


def test_nested_supplier_path_keeps_first_node_as_parent():
    assert category_fields("Products > Acrylic Awards > Alpine Series Acrylic") == (
        "Products",
        "Acrylic Awards > Alpine Series Acrylic",
    )


def test_apparel_taxonomy_keeps_all_descendant_levels():
    assert category_fields("Apparel > Tops > T-Shirts") == (
        "Apparel",
        "Tops > T-Shirts",
    )


def test_explicit_parent_and_subcategory_are_preserved():
    assert category_fields("Apparel", "Short Sleeve Shirts") == (
        "Apparel",
        "Short Sleeve Shirts",
    )


def test_single_level_category_has_no_subcategory():
    assert category_fields("Basketball") == ("Basketball", "")
