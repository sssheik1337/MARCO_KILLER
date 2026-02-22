from aiogram.fsm.state import State, StatesGroup

class CityState(StatesGroup):
    choosing = State()

class AdminEditState(StatesGroup):
    waiting_json = State()
    waiting_xlsx_city = State()
    waiting_xlsx_file = State()

class AdminTextEditState(StatesGroup):
    """Состояния редактирования текстовых полей в админ-панели."""

    waiting_text = State()
    waiting_confirm = State()


class SupportRequestState(StatesGroup):
    """Состояния для пользовательских обращений из главного меню."""

    waiting_text = State()


class BroadcastState(StatesGroup):
    """Состояния для универсальной рассылки всем пользователям."""

    waiting_content = State()
    waiting_url = State()
    waiting_confirm = State()


class ReadyCatalogState(StatesGroup):
    """Состояния управления каталогами готовых изделий."""

    waiting_title = State()
    waiting_file = State()
    rename_title = State()
    replace_file = State()


class GetAdminState(StatesGroup):
    """Состояния авторизации администратора по логину/паролю."""

    waiting_login = State()
    waiting_password = State()
