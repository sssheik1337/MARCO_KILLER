from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from config import ADMINS

class AdminOnly(BaseMiddleware):
    async def __call__(self, handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]], event, data):
        user_id = event.from_user.id if getattr(event, 'from_user', None) else 0
        if user_id in ADMINS:
            return await handler(event, data)
        return