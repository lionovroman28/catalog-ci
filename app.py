"""Учебный каталог Ромашки. Данные читаются из SQLite на каждый запрос."""
from __future__ import annotations

import argparse
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3

from flask import Flask, abort, render_template, request

BASE = Path(__file__).resolve().parent


def create_app(database: str | Path | None = None, title: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config['DATABASE'] = str(Path(database or os.environ.get('CATALOG_DB', BASE / 'data/catalog.db')).resolve())
    app.config['MAX_CONTENT_LENGTH'] = 1024
    app.config['CATALOG_TITLE'] = title or os.environ.get('CATALOG_TITLE', 'Каталог букетов Ромашки')

    @app.template_filter('rubles')
    def rubles(value: int) -> str:
        return f'{value:,}'.replace(',', ' ') + ' руб.'

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def catalog():
        available = request.args.get('available', '0')
        query = request.args.get('q', '').strip()
        page_text = request.args.get('page', '1')
        if (available not in ('0', '1') or set(request.args) - {'available', 'q', 'page'}
                or any(len(request.args.getlist(key)) > 1 for key in request.args)
                or len(query) > 80 or not page_text.isascii() or not page_text.isdecimal()
                or len(page_text) > 6 or int(page_text) < 1):
            abort(400)
        page = int(page_text)
        per_page = 24
        uri = Path(app.config['DATABASE']).as_uri() + '?mode=ro'
        try:
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.row_factory = sqlite3.Row
                db.create_function('CASEFOLD', 1, str.casefold, deterministic=True)
                condition = 'WHERE (? = 0 OR stock > 0) AND (instr(CASEFOLD(sku), ?) > 0 OR instr(CASEFOLD(name), ?) > 0)'
                params = (int(available), query.casefold(), query.casefold())
                found = db.execute('SELECT COUNT(*) FROM products ' + condition, params).fetchone()[0]
                pages = max(1, (found + per_page - 1) // per_page)
                if page > pages:
                    abort(404)
                rows = db.execute(
                    'SELECT sku, name, composition, price, stock FROM products ' + condition + ' ORDER BY CAST(substr(sku, 2) AS INTEGER), sku LIMIT ? OFFSET ?',
                    (*params, per_page, (page - 1) * per_page),
                ).fetchall()
                total = db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
        except sqlite3.Error:
            app.logger.exception('Не удалось прочитать учебный каталог')
            return render_template('error.html', message='Каталог временно недоступен. Сообщите преподавателю.'), 503
        return render_template('catalog.html', products=rows, total=total, found=found,
                               only_available=available == '1', query=query, page=page, pages=pages,
                               first=(page-1)*per_page+1 if found else 0,
                               last=min(page*per_page, found), title=app.config['CATALOG_TITLE'])

    @app.get('/about')
    def about():
        try:
            uri = Path(app.config['DATABASE']).as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True)) as db:
                total = db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
            report_path = BASE / 'report.json'
            report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        except (sqlite3.Error, ValueError, OSError):
            return render_template('error.html', message='Описание временно недоступно.'), 503
        return render_template('about.html', total=total, title=app.config['CATALOG_TITLE'], report=report)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template('error.html', message='Неизвестный режим каталога. Откройте главную страницу.'), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template('error.html', message='Такой страницы нет. Откройте каталог.'), 404

    return app


app = create_app()

if __name__ == '__main__':
    from waitress import serve
    parser = argparse.ArgumentParser(description='Запуск учебного каталога Ромашки')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    print(f'Каталог: http://{args.host}:{args.port}', flush=True)
    serve(app, host=args.host, port=args.port, threads=4, max_request_body_size=1024, expose_tracebacks=False)
