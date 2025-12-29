
from odoo import fields, models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    bio_factoring = fields.Boolean(string='Factoring')
