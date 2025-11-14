from aiogram.fsm.state import State, StatesGroup

class CityState(StatesGroup):
    choosing = State()

class AdminEditState(StatesGroup):
    waiting_json = State()
    waiting_xlsx_city = State()
    waiting_xlsx_file = State()


class SupportRequestState(StatesGroup):
    """Состояния для пользовательских обращений из главного меню."""

    waiting_text = State()
