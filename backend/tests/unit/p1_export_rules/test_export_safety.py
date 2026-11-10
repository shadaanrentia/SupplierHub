
"""
SupplierHub 2.0 - Size-Based Export Splitting Tests

Rules:
- Maximum 199 variants per export group
- Preserve whole sizes whenever possible
- Preserve every variant exactly once
- Maintain natural size order
- Produce deterministic groups"""

from collections import Counter

import pytest

from export_safety import grouped_variants


SIZES = [
    "3XS", "2XS", "XS", "S", "M",
    "L", "XL", "2XL", "3XL"
]


def make_variants(counts):
    """Create unique test variants for each size."""
    variants = []

    for size, quantity in counts.items():
        for i in range(quantity):
            variants.append({
                "id": f"{size}-{i:04d}",
                "variant_sku": f"TEST-{size}-{i:04d}",
                "size": size,
                "color": f"Color-{i:04d}",
                "price": 10.00,
                "inventory": 100,
                "is_active": True,
            })

    return variants


def flatten(groups):
    return [variant for group in groups for variant in group]


@pytest.mark.parametrize(
    "count,expected_groups",
    [
        (1, 1),
        (199, 1),
        (200, 2),
        (201, 2),
        (398, 2),
        (399, 3),
        (501, 3),
    ],
)
def test_variant_count_boundaries(count, expected_groups):
    variants = make_variants({"M": count})
    groups = grouped_variants(variants)

    assert len(groups) == expected_groups
    assert len(flatten(groups)) == count

    assert all(0 < len(g) <= 199 for g in groups)

def test_keep_whole_sizes_together():
    variants = make_variants({
        "S": 50,
        "M": 50,
        "L": 50,
        "XL": 50,
        "2XL": 50,
    })

    groups = grouped_variants(variants)

    assert len(groups) == 2
    assert len(groups[0]) == 150
    assert len(groups[1]) == 100

    assert {v["size"] for v in groups[0]} == {
        "S", "M", "L"
    }

    assert {v["size"] for v in groups[1]} == {
        "XL", "2XL"
    }

def test_do_not_split_size_that_fits():
    variants = make_variants({
        "S": 120,
        "M": 100,
        "L": 30,
    })

    groups = grouped_variants(variants)

    assert [len(g) for g in groups] == [120, 130]

    assert {v["size"] for v in groups[0]} == {"S"}
    assert {v["size"] for v in groups[1]} == {"M", "L"}


def test_oversized_single_size():
    variants = make_variants({"XL": 250})

    groups = grouped_variants(variants)

    assert [len(g) for g in groups] == [199, 51]

    assert all(
        v["size"] == "XL"
        for v in flatten(groups)
    )

    assert len(flatten(groups)) == 250


def test_no_missing_or_duplicate_variants():
    variants = make_variants({
        "XS": 30,
        "S": 60,
        "M": 80,
        "L": 90,
        "XL": 100,
        "2XL": 120,
    })

    groups = grouped_variants(variants)

    original_ids = [v["id"] for v in variants]
    exported_ids = [v["id"] for v in flatten(groups)]

    assert len(exported_ids) == len(original_ids)
    assert Counter(exported_ids) == Counter(original_ids)


def test_natural_size_order():
    variants = make_variants({
        "3XL": 1,
        "M": 1,
        "XS": 1,
        "XL": 1,
        "S": 1,
        "2XL": 1,
        "L": 1,
        "3XS": 1,
        "2XS": 1,
    })

    groups = grouped_variants(variants)

    actual_sizes = [
        v["size"] for v in flatten(groups)
    ]

    assert actual_sizes == SIZES


def test_grouping_is_deterministic():
    variants = make_variants({
        "S": 100,
        "M": 100,
        "L": 100,
    })

    first = grouped_variants(variants)
    second = grouped_variants(list(reversed(variants)))

    first_ids = [
        [v["id"] for v in group]
        for group in first
    ]
    second_ids = [
        [v["id"] for v in group]
        for group in second
    ]

    assert first_ids == second_ids


def test_empty_variants():
    assert grouped_variants([]) == []
