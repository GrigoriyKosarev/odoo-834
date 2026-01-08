# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Stored balance fields (зберігаються в БД)
    bio_initial_balance = fields.Monetary(
        string="Initial Balance",
        currency_field="company_currency_id",
        store=True,
        compute="_compute_bio_balances",
        help="Balance BEFORE the current line (excluding current transaction). "
             "Calculated using SQL window functions with PARTITION BY account+partner."
    )  # ODOO-834

    bio_end_balance = fields.Monetary(
        string="End Balance",
        currency_field="company_currency_id",
        store=True,
        compute="_compute_bio_balances",
        help="Balance AFTER the current line (including current transaction). "
             "Calculated using SQL window functions with PARTITION BY account+partner."
    )  # ODOO-834

    # Dynamic balance fields (НЕ зберігаються, розраховуються в read_group)
    # Використовуються в pivot view для коректного відображення балансів з урахуванням фільтрів
    bio_opening_by_partner = fields.Monetary(
        string="Opening Balance",
        currency_field="company_currency_id",
        readonly=True,
        help="Dynamic opening balance for partner grouping based on pivot filters. "
             "Calculated in read_group() method. "
             "Shows balance at the START of the filtered period. "
             "Formula: bio_opening_by_partner + sum(balance) = bio_closing_by_partner"
    )  # ODOO-834

    bio_closing_by_partner = fields.Monetary(
        string="Closing Balance",
        currency_field="company_currency_id",
        readonly=True,
        help="Dynamic closing balance for partner grouping based on pivot filters. "
             "Calculated in read_group() method. "
             "Shows balance at the END of the filtered period. "
             "Formula: bio_opening_by_partner + sum(balance) = bio_closing_by_partner"
    )  # ODOO-834

    @api.depends('debit', 'credit', 'date', 'account_id', 'partner_id', 'parent_state')
    def _compute_bio_balances(self):
        """
        Compute method для отримання балансів з таблиці bio.account.move.line.balance.
        Реальні розрахунки виконуються в SQL через _update_balances_incremental().
        ODOO-834
        """
        Balance = self.env['bio.account.move.line.balance']
        for line in self:
            bal = Balance.search([('move_line_id', '=', line.id)], limit=1)
            if bal:
                line.bio_initial_balance = bal.bio_initial_balance
                line.bio_end_balance = bal.bio_end_balance
            else:
                line.bio_initial_balance = 0
                line.bio_end_balance = 0

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """
        Override read_group для динамічного розрахунку opening/closing полів.

        Поля bio_opening_by_partner і bio_closing_by_partner розраховуються динамічно
        на основі domain (фільтрів) в pivot view для будь-якого групування.

        Це дозволяє коректно відображати баланси при фільтрації по даті:
        - opening = баланс на початок періоду
        - closing = баланс на кінець періоду

        ODOO-834
        """
        # Список полів які треба розрахувати динамічно
        dynamic_fields = ['bio_opening_by_partner', 'bio_closing_by_partner']

        # Перевіряємо чи запитують хоча б одне динамічне поле
        requested_dynamic_fields = [f for f in fields if any(df in f for df in dynamic_fields)]

        if not requested_dynamic_fields:
            # Якщо не запитують динамічні поля - викликаємо стандартний read_group
            return super().read_group(domain, fields, groupby, offset, limit, orderby, lazy)

        # Викликаємо стандартний read_group для всіх інших полів
        other_fields = [f for f in fields if not any(df in f for df in dynamic_fields)]
        result = super().read_group(domain, other_fields, groupby, offset, limit, orderby, lazy)

        # Для кожної групи розраховуємо динамічні поля
        for group in result:
            # Створюємо domain для цієї конкретної групи
            group_domain = domain.copy() if domain else []

            # Додаємо умови групування до domain
            if groupby and '__domain' in group:
                group_domain = group_domain + group['__domain']

            # Розраховуємо кожне запитане динамічне поле
            for field_spec in requested_dynamic_fields:
                field_name = field_spec.split(':')[0]  # Видаляємо агрегацію якщо є

                if field_name == 'bio_opening_by_partner':
                    group[field_name] = self._calc_opening_by_partner(group_domain)
                elif field_name == 'bio_closing_by_partner':
                    group[field_name] = self._calc_closing_by_partner(group_domain)

        return result

    def _calc_opening_by_partner(self, domain):
        """
        Розрахунок opening balance для групування по partner
        з урахуванням фільтрів (особливо по даті).
        Оптимізований - використовує прямий SQL без search().

        Логіка:
        1. Конвертуємо Odoo domain в SQL WHERE clause
        2. Знаходимо ПЕРШІ рядки для кожного account+partner в межах фільтру
        3. Сумуємо їх bio_initial_balance

        ODOO-834
        """
        # Конвертуємо Odoo domain в SQL WHERE clause
        query_obj = self._where_calc(domain)
        from_clause, where_clause, where_params = query_obj.get_sql()

        # Якщо немає WHERE умов - значить немає фільтрів
        if not where_clause:
            where_clause = "1=1"

        # SQL запит який знаходить перші рядки по кожному account+partner і сумує їх opening balance
        query = f"""
            WITH filtered_lines AS (
                SELECT
                    account_id,
                    partner_id,
                    bio_initial_balance,
                    date,
                    id
                FROM {from_clause}
                WHERE parent_state='posted' AND ({where_clause})
            ),
            first_lines_per_account AS (
                SELECT DISTINCT ON (account_id, COALESCE(partner_id,0))
                    bio_initial_balance
                FROM filtered_lines
                ORDER BY account_id, COALESCE(partner_id,0), date ASC, id ASC
            )
            SELECT COALESCE(SUM(bio_initial_balance), 0) as total
            FROM first_lines_per_account;
        """

        self.env.cr.execute(query, where_params)
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _calc_closing_by_partner(self, domain):
        """
        Розрахунок closing balance для групування по partner
        з урахуванням фільтрів (особливо по даті).
        Оптимізований - використовує прямий SQL без search().

        Логіка:
        1. Конвертуємо Odoo domain в SQL WHERE clause
        2. Знаходимо ОСТАННІ рядки для кожного account+partner в межах фільтру
        3. Сумуємо їх bio_end_balance

        ODOO-834
        """
        # Конвертуємо Odoo domain в SQL WHERE clause
        query_obj = self._where_calc(domain)
        from_clause, where_clause, where_params = query_obj.get_sql()

        # Якщо немає WHERE умов - значить немає фільтрів
        if not where_clause:
            where_clause = "1=1"

        # SQL запит який знаходить останні рядки по кожному account+partner і сумує їх closing balance
        query = f"""
            WITH filtered_lines AS (
                SELECT
                    account_id,
                    partner_id,
                    bio_end_balance,
                    date,
                    id
                FROM {from_clause}
                WHERE parent_state='posted' AND ({where_clause})
            ),
            last_lines_per_account AS (
                SELECT DISTINCT ON (account_id, COALESCE(partner_id,0))
                    bio_end_balance
                FROM filtered_lines
                ORDER BY account_id, COALESCE(partner_id,0), date DESC, id DESC
            )
            SELECT COALESCE(SUM(bio_end_balance), 0) as total
            FROM last_lines_per_account;
        """

        self.env.cr.execute(query, where_params)
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        """
        Hook для автоматичного оновлення балансів при створенні нових рядків.
        ODOO-834
        """
        lines = super().create(vals_list)
        lines._update_balances_incremental()
        return lines

    def write(self, vals):
        """
        Hook для автоматичного оновлення балансів при зміні рядків.
        ODOO-834
        """
        res = super().write(vals)
        self._update_balances_incremental()
        return res

    def unlink(self):
        """
        Hook для видалення балансів перед видаленням рядків.
        ODOO-834
        """
        # Видаляємо рядки з таблиці balances перед видаленням
        self.env['bio.account.move.line.balance'].search([('move_line_id', 'in', self.ids)]).unlink()
        return super().unlink()

    def _update_balances_incremental(self):
        """
        Інкрементальне оновлення балансів для рядків self та всіх наступних рядків
        в тих же партиціях (account_id + partner_id).

        Використовує SQL window function для ефективного перерахунку.

        Алгоритм:
        1. Визначаємо унікальні партиції (account_id, partner_id) та мінімальну дату в кожній
        2. Знаходимо ВСІ рядки від min_date в кожній партиції (бо всі наступні потребують перерахунку)
        3. Виконуємо SQL window function для перерахунку балансів

        ODOO-834
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
