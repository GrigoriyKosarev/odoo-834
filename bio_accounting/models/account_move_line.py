
from odoo import api, fields, models
from odoo.tools import float_is_zero


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # ODOO-231: Price unit zero check
    price_unit_is_zero = fields.Boolean(compute='_compute_price_unit_is_zero', store=False)

    # Tax amount calculation
    tax_amount = fields.Float(string="Tax Amount", compute="_compute_tax_amount")

    # ODOO-820: Product barcodes
    bio_product_barcode = fields.Char(related='product_id.barcode', string='Product Barcode')
    bio_product_packaging_barcode = fields.Char(related='product_id.bio_product_packaging_box_barcode',
                                                string='Packaging Barcode')

    @api.depends('price_unit', 'tax_ids', 'currency_id', 'company_id')
    def _compute_price_unit_is_zero(self):  # ODOO-231  # ODOO-472
        price_precision = self.env['decimal.precision'].precision_get('Product Price')
        for line in self:
            # line.move_id.type_name = 'Invoice'
            # line.move_id.type_name = 'Vendor Bill'
            if (float_is_zero(line.price_unit, precision_digits=price_precision) or
                    # not line.product_packaging_qty.is_integer() or
                    (len(line.tax_ids.ids) == 0 and line.currency_id == line.company_id.currency_id) or
                    (len(line.tax_ids.ids) == 0 and line.move_id.type_name == 'Vendor Bill')):
                line.price_unit_is_zero = True
            else:
                line.price_unit_is_zero = False

    @api.depends("quantity", "tax_ids", "price_unit")
    def _compute_tax_amount(self):
        for move_line_id in self:
            taxes = move_line_id.tax_ids.compute_all(
                move_line_id.price_unit,
                currency=move_line_id.move_id.company_currency_id,
                quantity=move_line_id.quantity,
                product=move_line_id.product_id,
                partner=move_line_id.partner_id,
            )
            move_line_id.tax_amount = sum(t['amount'] for t in taxes['taxes'])