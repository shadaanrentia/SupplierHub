from media_links import colour_key, resolved_links, sanmar_colour_alias


def test_colour_key_removes_leading_apostrophe_and_backtick_only():
    assert colour_key("'Ash") == "ash"
    assert colour_key("’Azure") == "azure"
    assert colour_key("`Black") == "black"
    assert colour_key("  'Black/White  ") == "black/white"


def test_colour_key_preserves_internal_apostrophe():
    assert colour_key("Women's Black") == "women's black"


def test_two_colour_combination_remains_one_colour_value():
    value = "Black/White"
    assert sanmar_colour_alias(value) == "black/white"
    assert colour_key(value) == "black/white"


def test_image_matching_uses_normalized_combined_colour_without_splitting():
    variants = [
        {"variant_sku": "STYLE-BW-S", "color": "'Black/White", "size": "S"},
        {"variant_sku": "STYLE-BW-M", "color": "Black/White", "size": "M"},
        {"variant_sku": "STYLE-BR-S", "color": "Black/Red", "size": "S"},
    ]
    image = {"source_color": "Black/White", "source_part_ids": ["STYLE-BW-S"]}
    colour, part_ids, linked = resolved_links(image, variants, colour_normalizer=sanmar_colour_alias)

    assert linked is True
    assert colour == "Black/White"
    assert set(part_ids) == {"STYLE-BW-S", "STYLE-BW-M"}
    assert "STYLE-BR-S" not in part_ids
