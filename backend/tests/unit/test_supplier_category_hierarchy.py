from multi_supplier.connector import category_fields


def test_caldwell_products_wrapper_is_removed_from_hierarchy():
    assert category_fields(
        "Products > Acrylic Awards > Alpine Series Acrylic",
        strip_products_root=True,
    ) == ("Acrylic Awards", "Alpine Series Acrylic")


def test_caldwell_clearance_keeps_real_parent_and_nested_subcategory():
    assert category_fields(
        "Products > Clearance > Acrylic, Glass & Crystal > Acrylic",
        strip_products_root=True,
    ) == ("Clearance", "Acrylic, Glass & Crystal > Acrylic")


def test_products_root_is_preserved_for_other_suppliers_by_default():
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
