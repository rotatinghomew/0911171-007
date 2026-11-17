from copy import deepcopy


class Stockroom:
    """现货、在途单与已占用采购预算的台账。

    在途单不可改货品或数量，重复登记同单号只允许完全相同的内容（幂等）；
    到货只把在途转入现货一次，重试不重复加库存。每条在途单可附带确认时
    占用的预算 ``committed_cost``，无论是否到货，该笔支出始终计入已用预算。
    """

    def __init__(self, positions: dict[tuple[str, str], int]) -> None:
        if any(not isinstance(units, int) or units < 0 for units in positions.values()):
            raise ValueError('现货须为非负整数')
        self.on_hand = dict(positions)
        self.incoming: dict[str, dict] = {}

    def register_incoming(
        self,
        order_id: str,
        store: str,
        product: str,
        units: int,
        arrives_at: int,
        committed_cost: float | None = None,
    ) -> None:
        if not isinstance(units, int) or units <= 0:
            raise ValueError('在途数量须为正整数')
        if committed_cost is not None and float(committed_cost) < 0:
            raise ValueError('占用预算不能为负')
        shipment = {
            'store': store,
            'product': product,
            'units': units,
            'arrives_at': arrives_at,
            'received': False,
            'committed_cost': None if committed_cost is None else float(committed_cost),
        }
        previous = self.incoming.get(order_id)
        if previous is not None:
            if any(previous[field] != shipment[field] for field in
                   ('store', 'product', 'units', 'arrives_at', 'committed_cost')):
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

    def committed_cost(self) -> float:
        """已确认采购占用的预算总和（含已到货部分，支出不因到货消失）。"""
        return sum(
            shipment['committed_cost'] or 0.0
            for shipment in self.incoming.values()
        )
