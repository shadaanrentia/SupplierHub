import asyncio
import json
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import deps
from deps import get_admin_user, get_current_user
from sanmar_taxonomy import key, is_brand_category_path

router = APIRouter(
    prefix="/api/taxonomy",
    tags=["Category configuration"],
)


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


async def read_config(conn, supplier_id):
    row = await conn.fetchrow(
        """
        SELECT store_domain, parent_category_id
        FROM supplier_taxonomy_config
        WHERE supplier_id=$1
        """,
        supplier_id,
    )
    return dict(row) if row else None


async def lock_supplier(conn, supplier_id):
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1))",
        "taxonomy:" + supplier_id,
    )

    running = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM supplier_taxonomy_jobs
        WHERE supplier_id=$1 AND status='running'
        """,
        supplier_id,
    )
    if running:
        raise HTTPException(409, "Wait for the current category job to finish")


async def combined_nodes(conn, supplier_id):
    source_rows = await conn.fetch(
        "SELECT data FROM supplier_taxonomy_nodes WHERE supplier_id=$1",
        supplier_id,
    )
    custom_rows = await conn.fetch(
        "SELECT data FROM supplier_taxonomy_custom_nodes WHERE supplier_id=$1",
        supplier_id,
    )

    nodes = [decode(row["data"]) for row in source_rows]
    nodes += [decode(row["data"]) for row in custom_rows]

    parents = {node["parent_path"] for node in nodes if node["parent_path"]}
    for node in nodes:
        node["leaf"] = node["path"] not in parents

    return sorted(nodes, key=lambda node: node["path"])


async def checked_parent(conn, supplier_id, ls, remote):
    config = await read_config(conn, supplier_id)

    if not config:
        raise HTTPException(
            400,
            "Select and save the Lightspeed parent category first",
        )

    if config["store_domain"] != ls.domain_prefix:
        raise HTTPException(
            409,
            "Lightspeed store changed. Select the parent category again",
        )

    parent = next(
        (
            category
            for category in remote.values()
            if category["lightspeed_category_id"]
            == config["parent_category_id"]
        ),
        None,
    )

    if not parent:
        raise HTTPException(
            409,
            "The selected Lightspeed parent was deleted. Select it again",
        )

    if parent.get("parent_id"):
        raise HTTPException(
            400,
            "Select a level-one parent, such as Apparel",
        )

    return parent


def destination_tree(nodes, parent_path):
    """
    Build a maximum-three-level destination tree.

    Source:      T-Shirts > Core > Adult
    Destination: Apparel > T-Shirts > Core — Adult

    Return destination nodes and source-leaf -> destination-path mappings.
    """
    output = {}
    assignments = {}
    normalized_targets = {}

    def add_node(path, verified=True, source_path=None):
        parts = path.split(" > ")
        node = output.setdefault(
            path,
            {
                "path": path,
                "name": parts[-1],
                "parent_path": " > ".join(parts[:-1]) or None,
                "level": len(parts),
                "verified": True,
                "leaf": True,
                "source_paths": [],
            },
        )
        node["verified"] = node["verified"] and verified

        if source_path:
            node["source_paths"].append(source_path)

    add_node(parent_path)

    for node in nodes:
        if not node["leaf"]:
            continue

        parts = node["path"].split(" > ")
        if not 1 <= len(parts) <= 2 or is_brand_category_path(node['path']):
            raise HTTPException(400, "Refresh the catalogue: select a product category with at most two levels")

        suffix = [parts[0]]
        if len(parts) > 1:
            suffix.append(parts[1])

        target = " > ".join([parent_path, *suffix])
        normalized = tuple(key(part) for part in target.split(" > "))

        previous = normalized_targets.get(normalized)
        if previous and previous != node["path"]:
            raise HTTPException(
                409,
                f"Two source paths produce the same destination: {target}",
            )

        normalized_targets[normalized] = node["path"]
        assignments[node["path"]] = target

        target_parts = target.split(" > ")
        for depth in range(2, len(target_parts) + 1):
            add_node(
                " > ".join(target_parts[:depth]),
                node["verified"],
                node["path"] if depth == len(target_parts) else None,
            )

    parents = {
        node["parent_path"]
        for node in output.values()
        if node["parent_path"]
    }
    for node in output.values():
        node["leaf"] = node["path"] not in parents

    # A source leaf must not accidentally become a destination parent.
    for source, target in assignments.items():
        if not output[target]["leaf"]:
            raise HTTPException(
                409,
                f"Destination conflict for {source}: {target} is also a parent",
            )

    return (
        sorted(output.values(), key=lambda node: (node["level"], node["path"])),
        assignments,
    )


@router.get("/{supplier_id}/configuration")
async def configuration(supplier_id: str, user=Depends(get_current_user)):
    from routes.taxonomy import check_supplier, service, get_remote

    ls = await service()
    remote = await get_remote(ls)

    async with deps.pool.acquire() as conn:
        await check_supplier(conn, supplier_id)
        config = await read_config(conn, supplier_id)

    return {
        "config": config,
        "store_domain": ls.domain_prefix,
        "parents": sorted(
            [
                {
                    "id": category["lightspeed_category_id"],
                    "path": category["full_path"],
                }
                for category in remote.values()
                if not category.get("parent_id")
            ],
            key=lambda category: category["path"].lower(),
        ),
    }


class ParentRequest(BaseModel):
    parent_category_id: str = Field(min_length=1, max_length=200)


@router.put("/{supplier_id}/configuration")
async def save_configuration(
    supplier_id: str,
    body: ParentRequest,
    user=Depends(get_admin_user),
):
    from routes.taxonomy import check_supplier, service, get_remote

    ls = await service()
    remote = await get_remote(ls)

    parent = next(
        (
            category
            for category in remote.values()
            if category["lightspeed_category_id"] == body.parent_category_id
        ),
        None,
    )
    if not parent or parent.get("parent_id"):
        raise HTTPException(400, "Select an existing level-one category")

    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await check_supplier(conn, supplier_id)
            await lock_supplier(conn, supplier_id)

            old = await read_config(conn, supplier_id)
            changed = (
                not old
                or old["store_domain"] != ls.domain_prefix
                or old["parent_category_id"] != body.parent_category_id
            )

            await conn.execute(
                """
                INSERT INTO supplier_taxonomy_config
                    (supplier_id, store_domain, parent_category_id)
                VALUES ($1,$2,$3)
                ON CONFLICT(supplier_id) DO UPDATE SET
                    store_domain=EXCLUDED.store_domain,
                    parent_category_id=EXCLUDED.parent_category_id,
                    updated_at=NOW()
                """,
                supplier_id,
                ls.domain_prefix,
                body.parent_category_id,
            )

            if changed:
                # Prevent normal pushes from using the previous hierarchy.
                await conn.execute(
                    """
                    DELETE FROM supplier_taxonomy_destinations
                    WHERE supplier_id=$1
                    """,
                    supplier_id,
                )

    return {"success": True, "parent_path": parent["full_path"]}


class CustomCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_path: str | None = None


@router.post("/{supplier_id}/custom-categories")
async def create_custom_category(
    supplier_id: str,
    body: CustomCategoryRequest,
    user=Depends(get_admin_user),
):
    from routes.taxonomy import load_catalog

    name = unicodedata.normalize("NFKC", body.name).strip()

    if (
        not name
        or ">" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise HTTPException(
            400,
            "Use a category name without > or control characters",
        )

    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await lock_supplier(conn, supplier_id)
            catalog = await load_catalog(conn, supplier_id)

            if not catalog["digest"]:
                raise HTTPException(400, "Import the SanMar CSV first")

            nodes = catalog["nodes"]
            parent = next(
                (
                    node
                    for node in nodes
                    if node["path"] == body.parent_path
                ),
                None,
            )

            if body.parent_path and not parent:
                raise HTTPException(404, "Parent category not found")

            # Do not turn a product-assignment leaf into a parent.
            if parent and parent["leaf"]:
                raise HTTPException(
                    400,
                    "Choose an existing parent category, or create a new root",
                )

            if parent and parent["level"] >= 2:
                raise HTTPException(400, "Categories allow two levels")

            path = (
                body.parent_path + " > " + name
                if body.parent_path
                else name
            )
            normalized = tuple(key(part) for part in path.split(" > "))

            if is_brand_category_path(path):
                raise HTTPException(400, "Brands and collections are not product categories")

            if any(
                tuple(key(part) for part in node["path"].split(" > "))
                == normalized
                for node in nodes
            ):
                raise HTTPException(409, "This category already exists")

            node = {
                "path": path,
                "name": name,
                "parent_path": body.parent_path,
                "level": len(path.split(" > ")),
                "leaf": True,
                "verified": True,
                "custom": True,
                "source_paths": [],
                "product_count": 0,
                "primary_count": 0,
            }

            await conn.execute(
                """
                INSERT INTO supplier_taxonomy_custom_nodes
                    (supplier_id,path,data,created_by)
                VALUES ($1,$2,$3::jsonb,$4)
                """,
                supplier_id,
                path,
                json.dumps(node),
                str(user["id"]),
            )

    return {"success": True, "category": node}
