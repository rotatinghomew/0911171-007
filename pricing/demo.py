from .purchasing import PurchaseDesk


def main() -> None:
    rows = [{"store": "s1", "product": "p1", "price": 10, "units": 20}, {"store": "s1", "product": "p1", "price": 12, "units": 16}, {"store": "s1", "product": "p1", "price": 14, "units": 14, "stockout": True}]
    desk = PurchaseDesk([{"product": "p1", "pack_size": 6, "unit_cost": 3}], 100)
    quote = desk.quote(rows, 11, {("s1", "p1"): 5})
    print(desk.approve("order1", quote))


if __name__ == "__main__":
    main()
