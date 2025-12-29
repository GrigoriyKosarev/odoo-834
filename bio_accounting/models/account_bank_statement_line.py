from odoo import models, api, _


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'


    @api.onchange('partner_id')
    def _onchange_partner(self):
        if self.partner_id and self.partner_id.bio_cash_flow_analytic_account_id:
            cash_flow_analytic_account = self.partner_id.bio_cash_flow_analytic_account_id
            self.cash_flow_analytic_account_id = cash_flow_analytic_account

    def action_edit_record_from_kanban(self):
        return {
            'name': _("Edit transaction"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line',
            'res_id': self.id,
            'views': [[False, 'form']],
            'view_id': 'view_account_bank_statement_line_form_edit',
            'target': 'new',
        }
