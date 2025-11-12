from math import ceil
from typing import Sequence

def slice_page(items: Sequence, page: int, page_size: int):
    total_pages = max(1, ceil(len(items) / page_size))
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], page, total_pages