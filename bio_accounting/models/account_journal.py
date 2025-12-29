from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _parse_bank_statement_file_prepare_result(self, data):
        res = super(AccountJournal, self)._parse_bank_statement_file_prepare_result(data)
        for el in res[2][0].get('transactions'):
            if el.get('partner_id'):
                partner = self.env['res.partner'].with_context(active_test=False).sudo().browse(el.get('partner_id'))
                if partner and partner.bio_cash_flow_analytic_account_id:
                    el['cash_flow_analytic_account_id'] = partner.bio_cash_flow_analytic_account_id.id
        return res