# pulsaris/config/__init__.py
from .celery import app as celery_app

__all__ = ("celery_app",)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
