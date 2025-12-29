
from odoo import api, fields, models
from odoo.tools import float_is_zero


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    price_unit_is_zero = fields.Boolean(compute='_compute_price_unit_is_zero', store=False)  # ODOO-231
    tax_amount = fields.Float(string="Tax Amount", compute="_compute_tax_amount")
    bio_product_barcode = fields.Char(related='product_id.barcode', string='Product Barcode')  # ODOO-820
    bio_product_packaging_barcode = fields.Char(related='product_id.bio_product_packaging_box_barcode',
                                                string='Packaging Barcode')  # ODOO-820
    bio_initial_balance = fields.Monetary(
        string="Initial Balance",
        currency_field="company_currency_id",
        store=True,
        compute="_compute_bio_balances",
        group_operator="max",
    ) # ODOO-834
    bio_end_balance = fields.Monetary(
        string="End Balance",
        currency_field="company_currency_id",
        store=True,
        compute="_compute_bio_balances",
        group_operator="max",
    ) # ODOO-834


    @api.depends('debit', 'credit', 'date', 'account_id', 'partner_id', 'parent_state')
    def _compute_bio_balances(self):
        ''' ODOO-834 '''

        # if (self.env.context.get('skip_bio_compute') or
        #     self.env.context.get('install_mode') or
        #     self.env.context.get('module')
        # ):
        #     return

        Balance = self.env['bio.account.move.line.balance']
        for line in self:
            bal = Balance.search([('move_line_id', '=', line.id)], limit=1)
            if bal:
                line.bio_initial_balance = bal.bio_initial_balance
                line.bio_end_balance = bal.bio_end_balance
            else:
                line.bio_initial_balance = 0
                line.bio_end_balance = 0

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._update_balances_incremental()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self._update_balances_incremental()
        return res

    def unlink(self):
        # видаляємо рядки з таблиці balances перед видаленням
        self.env['bio.account.move.line.balance'].search([('move_line_id', 'in', self.ids)]).unlink()
        return super().unlink()

    def _update_balances_incremental(self):
        """
        Масове оновлення таблиці balances тільки для рядків self.
        Використовує SQL window function для цих рядків і їх "партнера + рахунок".
        """
        if not self:
            return

        # Отримуємо унікальні комбінації account_id + partner_id
        account_partner_ids = [(line.account_id.id, line.partner_id.id or 0) for line in self]

        query_parts = []
        for account_id, partner_id in account_partner_ids:
            partner_clause = 'COALESCE(partner_id,0) = %s' % partner_id
            query_parts.append(f"(account_id = {account_id} AND {partner_clause})")

        domain_sql = " OR ".join(query_parts)
        if not domain_sql:
            return

        query = f"""
            INSERT INTO bio_account_move_line_balance (move_line_id, bio_initial_balance, bio_end_balance, company_currency_id)
            SELECT
                aml.id,
                SUM(aml2.debit - aml2.credit)
                    OVER (PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                          ORDER BY aml.date, aml.id
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS initial_balance,
                SUM(aml2.debit - aml2.credit)
                    OVER (PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                          ORDER BY aml.date, aml.id
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS end_balance,
                aml.company_currency_id
            FROM account_move_line aml
            LEFT JOIN account_move_line aml2
                ON aml2.account_id = aml.account_id
                AND COALESCE(aml2.partner_id,0) = COALESCE(aml.partner_id,0)
                AND aml2.date <= aml.date
            WHERE aml.parent_state='posted' AND ({domain_sql})
            ON CONFLICT (move_line_id) DO UPDATE
            SET bio_initial_balance = EXCLUDED.bio_initial_balance,
                bio_end_balance = EXCLUDED.bio_end_balance,
                company_currency_id = EXCLUDED.company_currency_id;
            """
        self.env.cr.execute(query)

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