# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID
import logging
_logger = logging.getLogger(__name__)


def post_init_update_balances(cr, registry):
    """
    Post-install hook для початкового заповнення балансів.
    Викликається один раз після встановлення/оновлення модуля.

    Виконує:
    1. TRUNCATE таблиці bio_account_move_line_balance
    2. Розрахунок балансів через SQL window function
    3. UPDATE основної таблиці account_move_line для синхронізації

    ODOO-834
    """
    try:
        _logger.info(">>> bio_account_balance: post_init_update_balances START <<<")
        env = api.Environment(cr, SUPERUSER_ID, {'install_mode': True})

        result = env['bio.account.move.line.balance'].reset_and_update_balances()

        if result:
            _logger.info(">>> bio_account_balance: post_init_update_balances END (SUCCESS) <<<")
        else:
            _logger.warning(">>> bio_account_balance: post_init_update_balances END (FAILED - see reset_and_update_balances errors) <<<")
    except Exception as e:
        _logger.error(">>> bio_account_balance: post_init_update_balances FAIL: %s <<<", str(e), exc_info=True)


def pre_uninstall_cleanup(cr, registry):
    """
    Pre-uninstall hook для очищення views та метаданих.
    Викликається перед видаленням модуля.

    Це запобігає помилкам "Cannot read properties of undefined"
    в pivot view після видалення модуля.

    ODOO-834
    """
    try:
        _logger.info(">>> bio_account_balance: pre_uninstall_cleanup START <<<")
        env = api.Environment(cr, SUPERUSER_ID, {})

        # Видаляємо views модуля
        views = env['ir.ui.view'].search([
            ('name', 'ilike', 'bio.account.balance'),
        ])
        if views:
            _logger.info(f"Deleting {len(views)} views: {views.mapped('name')}")
            views.unlink()

        _logger.info(">>> bio_account_balance: pre_uninstall_cleanup END (SUCCESS) <<<")
    except Exception as e:
        _logger.error(">>> bio_account_balance: pre_uninstall_cleanup FAIL: %s <<<", str(e), exc_info=True)

