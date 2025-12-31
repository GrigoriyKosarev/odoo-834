from odoo import api, SUPERUSER_ID
import logging
_logger = logging.getLogger(__name__)


def post_init_update_balances(cr, registry):
    """
    Post-install hook для початкового заповнення балансів.
    Викликається один раз після встановлення/оновлення модуля.
    ODOO-834
    """
    try:
        _logger.info(">>> post_init_update_balances START <<<")
        env = api.Environment(cr, SUPERUSER_ID, {'install_mode': True})

        # reset_and_update_balances робить:
        # 1. TRUNCATE таблиці bio_account_move_line_balance
        # 2. Розрахунок балансів через SQL window function
        # 3. UPDATE основної таблиці account_move_line для синхронізації
        result = env['bio.account.move.line.balance'].reset_and_update_balances()

        if result:
            _logger.info(">>> post_init_update_balances END (SUCCESS) <<<")
        else:
            _logger.warning(">>> post_init_update_balances END (FAILED - see reset_and_update_balances errors) <<<")
    except Exception as e:
        _logger.error(">>> post_init_update_balances FAIL: %s <<<", str(e), exc_info=True)
