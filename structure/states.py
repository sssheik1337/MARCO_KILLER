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


class PromoBroadcastState(StatesGroup):
    """Состояния для промо-рассылки по выбранному товару."""

    choose_city = State()
    choose_section = State()
    waiting_product = State()
    waiting_type = State()
    waiting_extra = State()
    waiting_url = State()
    waiting_confirm = State()


class AnnouncementState(StatesGroup):
    """Состояния для объявления без привязки к товару."""

    waiting_type = State()
    waiting_text = State()
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
