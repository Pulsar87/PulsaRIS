"""Lightweight app hosting the module-picker page ("app launcher").

No models, no migrations – it just renders the enabled modules from
``core.module_registry``.  Add new pages here (e.g. an admin-facing
module status screen) without touching feature apps.
"""
