"""Проверяет XLSX и обновляет учебную базу одной транзакцией."""
from __future__ import annotations

import argparse
from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
import sys

from openpyxl import load_workbook

HEADERS = ['Артикул', 'Название', 'Состав', 'Цена, руб.', 'Остаток, шт.']


def integer(value, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value) or value < minimum:
        raise ValueError(f'{label}: нужно целое число не меньше {minimum}')
    return int(value)


def read_catalog(source: Path) -> list[tuple]:
    with source.open('rb') as stream:
        workbook = load_workbook(stream, read_only=True, data_only=False)
        try:
            if workbook.sheetnames != ['Каталог']:
                raise ValueError('Нужен единственный лист «Каталог»')
            sheet = workbook['Каталог']
            rows = list(sheet.iter_rows())
            if not rows or [c.value for c in rows[0]] != HEADERS:
                raise ValueError('Заголовки должны точно совпадать с учебным образцом')
            data, seen = [], set()
            for number, row in enumerate(rows[1:], start=2):
                if all(c.value is None for c in row):
                    continue
                if len(row) != 5 or any(c.data_type == 'f' for c in row):
                    raise ValueError(f'Строка {number}: формулы и лишние столбцы не допускаются')
                sku, name, composition, price, stock = [c.value for c in row]
                if any(not isinstance(v, str) or not v.strip() for v in (sku, name, composition)):
                    raise ValueError(f'Строка {number}: заполните артикул, название и состав текстом')
                sku, name, composition = [v.strip() for v in (sku, name, composition)]
                if not re.fullmatch(r'[BH][0-9]{3,5}', sku) or sku in seen:
                    raise ValueError(f'Строка {number}: неверный или повторный артикул {sku}')
                if sku != f'{sku[0]}{int(sku[1:]):03d}' or not 1 <= int(sku[1:]) <= 10000:
                    raise ValueError(f'Строка {number}: номер артикула вне учебного диапазона')
                if len(name) > 120 or len(composition) > 200:
                    raise ValueError(f'Строка {number}: слишком длинное название или состав')
                data.append((sku, name, composition, integer(price, f'Строка {number}, цена', 1), integer(stock, f'Строка {number}, остаток', 0)))
                seen.add(sku)
            if not data:
                raise ValueError('Каталог не содержит товаров')
            return data
        finally:
            workbook.close()


def import_catalog(source: Path, destination: Path) -> int:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError('База не может заменять исходный XLSX')
    # Validate the entire input before touching the old database.
    rows = read_catalog(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(destination)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT NOT NULL, composition TEXT NOT NULL, price INTEGER NOT NULL CHECK(price > 0), stock INTEGER NOT NULL CHECK(stock >= 0))')
            db.execute('DELETE FROM products')
            db.executemany('INSERT INTO products VALUES (?, ?, ?, ?, ?)', rows)
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Загрузка XLSX в учебную SQLite')
    parser.add_argument('source', type=Path)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parent / 'data/catalog.db')
    args = parser.parse_args()
    try:
        count = import_catalog(args.source, args.db)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f'Импорт не выполнен: {error}', file=sys.stderr)
        sys.exit(1)
    print(f'Загружено товаров: {count}. База: {args.db}')
