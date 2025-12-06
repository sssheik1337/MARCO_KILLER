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
    city: str
    section: str
    kind: str | None
    item_type: str | None
    collection: str | None
    code: str | None
    article: str | None
    name: str
    quantity: float | str | None
    free_quantity: float | str | None
    unit: str | None
    extra_info: str | None
    date_in: str | None


@dataclass
class StockItemCity:
    """Коллекция остатков по городу и разделу."""

    city: Literal["msk", "spb"]
    section: Literal["fabrics", "hardware"]
    items: list[StockItemRow]
    kind: str | None = None
    item_type: str | None = None
    kind_slug: str | None = None
    type_slug: str | None = None
    back_callback: str | None = None

