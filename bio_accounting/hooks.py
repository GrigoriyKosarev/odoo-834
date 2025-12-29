from odoo import api, SUPERUSER_ID
import logging
_logger = logging.getLogger(__name__)


def post_init_update_balances(cr, registry):
    try:
        _logger.info(">>> post_init_update_balances START <<<")
        env = api.Environment(cr, SUPERUSER_ID, {'skip_bio_compute': True, 'install_mode': True})
        env['bio.account.move.line.balance'].update_balances_sql()
        _logger.info(">>> post_init_update_balances END <<<")
    except:
        _logger.info(">>> post_init_update_balances FAIL <<<")
