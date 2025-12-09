"""Единый интерфейс для работы с остатками и каталогом."""
from data.stock import load_city_stock
from data.stock_models import StockItemCatalog, StockItemCity


async def load_catalog(section: str) -> list[StockItemCatalog]:
    """
    Возвращает элементы каталога (ткань/фурнитура) из общих прайс-листов.
    Пока возвращает пустой список.
    """

    return []
