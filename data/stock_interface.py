"""Единый интерфейс для работы с остатками и каталогом."""
from data.stock_models import StockItemCatalog, StockItemCity


async def load_city_stock(city: str, section: str) -> list[StockItemCity]:
    """
    Возвращает остатки для города (msk/spb) и раздела (fabrics/hardware).
    Пока возвращает пустой список. Логика парсинга будет добавлена позже.
    """

    return []


async def load_catalog(section: str) -> list[StockItemCatalog]:
    """
    Возвращает элементы каталога (ткань/фурнитура) из общих прайс-листов.
    Пока пустая заглушка.
    """

    return []
