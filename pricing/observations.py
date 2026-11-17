def eligible(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not row.get("stockout") and row.get("price") is not None and row.get("units") is not None]


def by_store_product(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in eligible(rows):
        groups.setdefault((row["store"], row["product"]), []).append(row)
    return groups
