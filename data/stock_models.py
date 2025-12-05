"""Структуры данных для каталога и остатков."""
from dataclasses import dataclass
from typing import Literal


@dataclass
class StockItemCatalog:
    """Элемент каталога для прайс-листов тканей и фурнитуры."""

    article: str | None
    name: str
    collection: str | None
    unit: str | None
    currency: str | None
    price_rrc: float | None
    price_opt: float | None
    multiplicity: str | None
    brand_country: str | None
    status: str | None  # Новинка, спеццена, распродажа
    image_url: str | None


@dataclass
class StockItemCity:
    """Элемент остатков по городу."""

    city: Literal["msk", "spb"]
    article: str | None
    name: str
    category: str | None
    type: str | None
    quantity: float | None
    free_quantity: float | None
    unit: str | None
    program: str | None
    extra: str | None
    arrival_date: str | None  # без нормализации
