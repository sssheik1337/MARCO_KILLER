"""Ключи настроек для хранения загруженных файлов."""

CATALOG_FILE_KEYS = {
    "fabrics": "file_catalog_fabrics",
    "hardware": "file_catalog_hardware",
}

STOCK_FILE_KEYS = {
    "msk": {
        "fabrics": "file_stock_fabrics_msk",
        "hardware": "file_stock_hardware_msk",
    },
    "spb": {
        "fabrics": "file_stock_fabrics_spb",
        "hardware": "file_stock_hardware_spb",
    },
}

ADMIN_IMPORT_KEYS = {
    "fabrics_catalog": CATALOG_FILE_KEYS["fabrics"],
    "hardware_catalog": CATALOG_FILE_KEYS["hardware"],
    "stock_fabrics_msk": STOCK_FILE_KEYS["msk"]["fabrics"],
    "stock_hardware_msk": STOCK_FILE_KEYS["msk"]["hardware"],
    "stock_fabrics_spb": STOCK_FILE_KEYS["spb"]["fabrics"],
    "stock_hardware_spb": STOCK_FILE_KEYS["spb"]["hardware"],
}
