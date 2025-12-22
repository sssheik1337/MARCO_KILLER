from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from data.admins import is_admin

class AdminOnly(BaseMiddleware):
    async def __call__(self, handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]], event, data):
        user_id = event.from_user.id if getattr(event, 'from_user', None) else 0
        if await is_admin(user_id):
            return await handler(event, data)
        return
