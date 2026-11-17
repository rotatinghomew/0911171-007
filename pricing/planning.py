from .estimate import slope
from .observations import by_store_product


def scenarios(rows: list[dict], proposed_price: float) -> list[dict]:
    result = []
    for (store, product), history in sorted(by_store_product(rows).items()):
        response = slope(history)
        baseline = float(history[-1]["units"])
        expected = None if response is None else max(0.0, baseline + response * (proposed_price - float(history[-1]["price"])))
        result.append({"store": store, "product": product, "slope": response, "expected_units": expected})
    return result
