"""Biosfera"""
# -*- encoding: utf-8 -*-

from . import models
from . import report

# Імпорт post_init_hook для доступності в __manifest__.py
import logging
_logger = logging.getLogger(__name__)
_logger.info("bio_accounting __init__.py loading hooks...")

from .hooks import post_init_update_balances

_logger.info("bio_accounting __init__.py loaded successfully, post_init_hook available")
