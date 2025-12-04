from pydantic import BaseModel
from typing import Optional

class Product(BaseModel):
    id: int
    city: str  # "spb" | "msk"
    category: str
    subcategory: Optional[str] = None
    name: str
    article: str
    country: str | None = None
    fabric_type: str | None = None
    segment: str | None = None
    collection: str | None = None
    brand_country: str | None = None
    multiplicity: str | None = None
    unit: str | None = None
    currency: str | None = None
    status: str | None = None
    price_piece: float | None = None
    price_roll: float | None = None
    special: str | None = None  # произвольная отметка из прайс-листа
    in_stock: int | None = None
    image_url: str | None = None

class Settings(BaseModel):
    address: str = ""
    phone: str = ""
    worktime: str = ""
    email: str = ""
    requisites: str = ""
    map_image_url: str = ""