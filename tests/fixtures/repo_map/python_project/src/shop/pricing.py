import decimal

from shop.models import Item


def subtotal(items: list[Item]) -> decimal.Decimal:
    return sum((decimal.Decimal(str(i.price)) for i in items), decimal.Decimal(0))
