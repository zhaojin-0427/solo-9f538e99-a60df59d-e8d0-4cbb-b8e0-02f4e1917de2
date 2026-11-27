# -*- coding: utf-8 -*-
"""Gunicorn / WSGI 入口：gunicorn --bind 0.0.0.0:5000 wsgi:application"""

from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=5000, debug=False)
