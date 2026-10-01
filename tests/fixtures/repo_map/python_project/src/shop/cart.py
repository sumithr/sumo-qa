import requests

from . import pricing
from .models import Item


def total(items: list[Item]) -> float:
    from shop.tax import RATE

    return float(pricing.subtotal(items)) * (1 + RATE)


def publish(items: list[Item]) -> None:
    requests.post("https://example.invalid/totals", json={"total": total(items)})
