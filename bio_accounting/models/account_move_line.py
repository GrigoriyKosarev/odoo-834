
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
        group_operator="min",  # При групуванні бере мінімум = початковий баланс першого рядка
    ) # ODOO-834
    bio_end_balance = fields.Monetary(
        string="End Balance",
        currency_field="company_currency_id",
        store=True,
        compute="_compute_bio_balances",
        group_operator="max",  # При групуванні бере максимум = кінцевий баланс останнього рядка
    ) # ODOO-834

    # Поля для pivot view - містять баланс тільки для останнього рядка в партиції
    # Розраховуються через SQL в _update_balances_incremental
    bio_closing_by_account_partner = fields.Monetary(
        string="Balance by Account+Partner",
        currency_field="company_currency_id",
        store=True,
        readonly=True,
        help="Contains balance only for the last line in each account+partner partition. "
             "Use in pivot view when grouping by account and partner. "
             "Sum of this field gives balance per account per partner."
    ) # ODOO-834

    bio_closing_by_partner = fields.Monetary(
        string="Balance by Partner",
        currency_field="company_currency_id",
        store=True,
        readonly=True,
        help="Contains total partner balance (sum of all accounts) only for the very last line of the partner. "
             "Use in pivot view when grouping only by partner. "
             "Sum of this field gives total balance per partner."
    ) # ODOO-834


    @api.depends('debit', 'credit', 'date', 'account_id', 'partner_id', 'parent_state')
    def _compute_bio_balances(self):
        ''' ODOO-834 '''
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
        Масове оновлення таблиці balances для рядків self та всіх наступних рядків
        в тих же партиціях (account_id + partner_id).
        Використовує SQL window function.
        """
        if not self:
            return

        # Збираємо унікальні партиції та мінімальні дати
        partitions = {}  # {(account_id, partner_id): min_date}
        for line in self:
            key = (line.account_id.id, line.partner_id.id if line.partner_id else False)
            if key not in partitions or line.date < partitions[key]:
                partitions[key] = line.date

        # Будуємо domain для пошуку всіх рядків які потрібно оновити
        domain_parts = []
        for (account_id, partner_id), min_date in partitions.items():
            domain_parts.append([
                ('account_id', '=', account_id),
                ('partner_id', '=', partner_id),
                ('date', '>=', min_date),
                ('parent_state', '=', 'posted'),
            ])

        if not domain_parts:
            return

        # Об'єднуємо всі domain через OR
        lines_to_update = self.env['account.move.line']
        for domain in domain_parts:
            lines_to_update |= self.env['account.move.line'].search(domain)

        if not lines_to_update:
            return

        # Виконуємо оновлення через SQL window function
        query = """
            INSERT INTO bio_account_move_line_balance (move_line_id, bio_initial_balance, bio_end_balance, company_currency_id)
            SELECT
                aml.id,
                COALESCE(
                    SUM(aml.debit - aml.credit) OVER (
                        PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                        ORDER BY aml.date, aml.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS initial_balance,
                COALESCE(
                    SUM(aml.debit - aml.credit) OVER (
                        PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                        ORDER BY aml.date, aml.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ), 0
                ) AS end_balance,
                aml.company_currency_id
            FROM account_move_line aml
            WHERE aml.parent_state='posted' AND aml.id IN %s
            ON CONFLICT (move_line_id) DO UPDATE
            SET bio_initial_balance = EXCLUDED.bio_initial_balance,
                bio_end_balance = EXCLUDED.bio_end_balance,
                company_currency_id = EXCLUDED.company_currency_id;
            """
        self.env.cr.execute(query, (tuple(lines_to_update.ids),))

        # Розраховуємо bio_closing_by_account_partner для pivot view
        # Тільки останній рядок в кожній партиції (account+partner) отримує bio_end_balance
        account_partner_query = """
            WITH ranked AS (
                SELECT
                    id,
                    bio_end_balance,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id, COALESCE(partner_id,0)
                        ORDER BY date DESC, id DESC
                    ) AS rn
                FROM account_move_line
                WHERE parent_state='posted' AND id IN %s
            )
            UPDATE account_move_line aml
            SET bio_closing_by_account_partner = CASE
                WHEN ranked.rn = 1 THEN ranked.bio_end_balance
                ELSE 0
            END
            FROM ranked
            WHERE ranked.id = aml.id;
        """
        self.env.cr.execute(account_partner_query, (tuple(lines_to_update.ids),))

        # Розраховуємо bio_closing_by_partner для pivot view
        # Тільки самий останній рядок партнера отримує загальний баланс всіх accounts
        partner_query = """
            WITH last_lines_per_account AS (
                -- Знаходимо останній рядок для кожного account+partner
                SELECT DISTINCT ON (account_id, COALESCE(partner_id,0))
                    id,
                    partner_id,
                    bio_end_balance,
                    date
                FROM account_move_line
                WHERE parent_state='posted'
                ORDER BY account_id, COALESCE(partner_id,0), date DESC, id DESC
            ),
            partner_totals AS (
                -- Сумуємо баланси по партнерам
                SELECT
                    COALESCE(partner_id,0) as partner_key,
                    SUM(bio_end_balance) as total_balance
                FROM last_lines_per_account
                GROUP BY COALESCE(partner_id,0)
            ),
            last_line_per_partner AS (
                -- Знаходимо самий останній рядок для кожного партнера
                SELECT DISTINCT ON (COALESCE(partner_id,0))
                    id,
                    COALESCE(partner_id,0) as partner_key
                FROM account_move_line
                WHERE parent_state='posted' AND id IN %s
                ORDER BY COALESCE(partner_id,0), date DESC, id DESC
            )
            UPDATE account_move_line aml
            SET bio_closing_by_partner = COALESCE(pt.total_balance, 0)
            FROM last_line_per_partner llpp
            LEFT JOIN partner_totals pt ON pt.partner_key = llpp.partner_key
            WHERE aml.id = llpp.id;
        """
        self.env.cr.execute(partner_query, (tuple(lines_to_update.ids),))

        # Обнулюємо bio_closing_by_partner для всіх інших рядків
        self.env.cr.execute("""
            UPDATE account_move_line
            SET bio_closing_by_partner = 0
            WHERE id IN %s
              AND bio_closing_by_partner IS NULL;
        """, (tuple(lines_to_update.ids),))

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