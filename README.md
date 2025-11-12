### Запуск
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py


### Импорт прайса
В админке: отправьте `city spb` или `city msk`, затем XLSX. Колонки сопоставляются в `data/importer.py`.


### Правка контактов
Отправьте в /admin JSON, который сохраняется в `data/settings.json`.