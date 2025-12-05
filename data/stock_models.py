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
class StockItemRow:
    """Единичная запись остатка."""

    id: int
    code: str | None
    article: str | None
    name: str
    quantity: float
    unit: str
    extra_info: str | None
    date_in: str | None


@dataclass
class StockItemCity:
    """Коллекция остатков по городу и разделу."""

    city: Literal["msk", "spb"]
    section: Literal["fabrics", "hardware"]
    items: list[StockItemRow]

