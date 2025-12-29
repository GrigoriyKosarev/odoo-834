
from odoo import models, fields, api


class AccountInvoiceReport(models.Model):
    _inherit = "account.invoice.report"

    product_barcode = fields.Char(string='Barcode', readonly=True)
    code_sku = fields.Char(string='code SKU', readonly=True)
    bio_headquarter = fields.Many2one(comodel_name='res.partner', string='Headquarter')
    bio_factoring = fields.Boolean(string='Factoring', readonly=True) # ODOO-476
    # ODOO-664 begin
    bio_general_code_id = fields.Many2one(
        comodel_name='product.product',
        string='General code'
    )
    bio_product_site_id = fields.Many2one(
        comodel_name="product.production.site",
        string="Production site"
    )
    bio_production_code = fields.Char(
        string="Production code"
    )
    # ODOO-664 end
    bio_untaxed_price_total = fields.Float(string='Untaxed Total in Currency', readonly=True) # ODOO-569
    # ODOO-867 begin
    # detailed_type = fields.Char(string="Product Type")
    detailed_type = fields.Selection([
        ('product', 'Storable Product'),
        ('consu', 'Consumable'),
        ('service', 'Service')], string='Product Type', default='consu', required=True)
    # ODOO-867 end


    @api.model
    def _select(self):
        res = super()._select()
        res += ''',
                product.barcode                 AS product_barcode,
                product.default_code            AS code_sku,
                account_partner.bio_headquarter,
                move.bio_factoring
                , template.bio_general_code_id as bio_general_code_id
                , template.bio_product_site_id as bio_product_site_id
                , template.bio_production_code as bio_production_code
                , line.price_subtotal * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                                                                            AS bio_untaxed_price_total   
                '''
                # account_partner.bio_headquarter # ODOO-444
        # ODOO-867 begin
        res += '''
                , template.detailed_type as detailed_type
               '''
        # ODOO-867 end
        return res

    @api.model
    def _from(self):
        res = super()._from()
        res += 'LEFT JOIN res_partner account_partner ON account_partner.id = move.partner_id'  # ODOO-444
        return res

    @api.model
    def _group_by(self):
        group_by = super(AccountInvoiceReport, self)._group_by()
        group_by = f"""
                {group_by}
                , template.bio_general_code_id
                , template.bio_product_site_id
                , template.bio_production_code
                """
        # ODOO-867 begin
        group_by += '''
                 , template.detailed_type
                 '''
        # ODOO-867 end
        return group_by
