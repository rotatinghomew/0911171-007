def slope(rows: list[dict]) -> float | None:
    if len(rows) < 2:
        return None
    mean_x = sum(float(row["price"]) for row in rows) / len(rows)
    mean_y = sum(float(row["units"]) for row in rows) / len(rows)
    denominator = sum((float(row["price"]) - mean_x) ** 2 for row in rows)
    if denominator == 0:
        return None
    return sum((float(row["price"]) - mean_x) * (float(row["units"]) - mean_y) for row in rows) / denominator
