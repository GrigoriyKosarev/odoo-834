from odoo import fields, models


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'

    bio_cash_flow_analytic_account_id = fields.Many2one(
        comodel_name="account.analytic.account", string="Cash Flow Analytic Account",
        domain="[('cash_flow_article', '=', True)]")

