from copy import deepcopy


class Stockroom:
    def __init__(self, positions: dict[tuple[str, str], int]) -> None:
        if any(not isinstance(units, int) or units < 0 for units in positions.values()):
            raise ValueError('现货须为非负整数')
        self.on_hand = dict(positions)
        self.incoming: dict[str, dict] = {}

    def register_incoming(self, order_id: str, store: str, product: str, units: int, arrives_at: int) -> None:
        if not isinstance(units, int) or units <= 0:
            raise ValueError('在途数量须为正整数')
        shipment = {'store': store, 'product': product, 'units': units, 'arrives_at': arrives_at, 'received': False}
        previous = self.incoming.get(order_id)
        if previous is not None:
            if any(previous[field] != shipment[field] for field in ('store', 'product', 'units', 'arrives_at')):
                raise ValueError('在途单号已被使用')
            return
        self.incoming[order_id] = shipment

    def available_by(self, cutoff: int) -> dict[tuple[str, str], int]:
        positions = dict(self.on_hand)
        for shipment in self.incoming.values():
            if not shipment['received'] and shipment['arrives_at'] <= cutoff:
                key = (shipment['store'], shipment['product'])
                positions[key] = positions.get(key, 0) + shipment['units']
        return positions

    def receive(self, order_id: str, at: int) -> dict:
        shipment = self.incoming[order_id]
        if at < shipment['arrives_at']:
            raise ValueError('到货时间早于预计日期')
        if not shipment['received']:
            key = (shipment['store'], shipment['product'])
            self.on_hand[key] = self.on_hand.get(key, 0) + shipment['units']
            shipment['received'] = True
        return deepcopy(shipment)
