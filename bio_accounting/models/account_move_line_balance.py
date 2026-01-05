from odoo import models, fields, api


class AccountMoveLineBalance(models.Model):
    _name = 'bio.account.move.line.balance'
    _description = 'Stored balances for account.move.line'

    move_line_id = fields.Many2one(
        comodel_name='account.move.line',
        string='Journal Item',
        required=True,
        ondelete='cascade',
        index=True
    )
    company_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
    )
    bio_initial_balance = fields.Monetary(
        string='Initial Balance',
        currency_field='company_currency_id',
        readonly=True,
        store=True,
        group_operator='min',  # При групуванні бере мінімум
    )
    bio_end_balance = fields.Monetary(
        string='End Balance',
        currency_field='company_currency_id',
        readonly=True,
        store=True,
        group_operator='max',  # При групуванні бере максимум
    )

    _sql_constraints = [
        ('move_line_unique', 'unique(move_line_id)', 'Move line must be unique!'),
    ]

    @api.model
    def update_balances_sql(self):
        query = """
        INSERT INTO bio_account_move_line_balance (
            move_line_id,
            bio_initial_balance,
            bio_end_balance,
            company_currency_id
        )
        SELECT
            aml.id AS move_line_id,
            
            COALESCE(
                SUM(aml.debit - aml.credit) OVER (
                    PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                    ORDER BY aml.date, aml.id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0
            ) AS bio_initial_balance,
            
            COALESCE(
                SUM(aml.debit - aml.credit) OVER (
                    PARTITION BY aml.account_id, COALESCE(aml.partner_id,0)
                    ORDER BY aml.date, aml.id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ), 0
            ) AS bio_end_balance,
            
            aml.company_currency_id
        FROM account_move_line aml
        WHERE aml.parent_state = 'posted'
        ON CONFLICT (move_line_id) DO UPDATE
        SET 
            bio_initial_balance = EXCLUDED.bio_initial_balance,
            bio_end_balance = EXCLUDED.bio_end_balance,
            company_currency_id = EXCLUDED.company_currency_id;
        """
        self.env.cr.execute(query)

    @api.model
    def reset_and_update_balances(self):
        """
        Повне перерахування балансів для всіх проводок.
        1. Очищує таблицю bio_account_move_line_balance
        2. Розраховує баланси через SQL window function
        3. Синхронізує дані в основну таблицю account_move_line
        ODOO-834
        """
        import logging
        _logger = logging.getLogger(__name__)

        try:
            # Крок 1: Очищення таблиці балансів
            _logger.info("Truncating bio_account_move_line_balance table...")
            self.env.cr.execute("TRUNCATE TABLE bio_account_move_line_balance RESTART IDENTITY;")
            self.env.invalidate_all()

            # Крок 2: Розрахунок балансів через window function
            _logger.info("Calculating balances via SQL window function...")
            self.update_balances_sql()
            self.env.invalidate_all()

            # Крок 3: Синхронізація в основну таблицю
            _logger.info("Synchronizing balances to account_move_line table...")
            self.env.cr.execute("""
               UPDATE account_move_line aml
               SET bio_initial_balance = bal.bio_initial_balance,
                   bio_end_balance     = bal.bio_end_balance
               FROM bio_account_move_line_balance bal
               WHERE bal.move_line_id = aml.id;
            """)
            self.env.invalidate_all()

            # Крок 4: Розрахунок bio_closing_by_account_partner для pivot view
            _logger.info("Calculating bio_closing_by_account_partner for pivot view...")
            self.env.cr.execute("""
                WITH ranked AS (
                    SELECT
                        id,
                        bio_end_balance,
                        ROW_NUMBER() OVER (
                            PARTITION BY account_id, COALESCE(partner_id,0)
                            ORDER BY date DESC, id DESC
                        ) AS rn
                    FROM account_move_line
                    WHERE parent_state='posted'
                )
                UPDATE account_move_line aml
                SET bio_closing_by_account_partner = CASE
                    WHEN ranked.rn = 1 THEN ranked.bio_end_balance
                    ELSE 0
                END
                FROM ranked
                WHERE ranked.id = aml.id;
            """)
            self.env.invalidate_all()

            # Крок 5: Розрахунок bio_closing_by_partner для pivot view
            _logger.info("Calculating bio_closing_by_partner for pivot view...")
            self.env.cr.execute("""
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
                    WHERE parent_state='posted'
                    ORDER BY COALESCE(partner_id,0), date DESC, id DESC
                )
                UPDATE account_move_line aml
                SET bio_closing_by_partner = CASE
                    WHEN llpp.id IS NOT NULL THEN COALESCE(pt.total_balance, 0)
                    ELSE 0
                END
                FROM last_line_per_partner llpp
                LEFT JOIN partner_totals pt ON pt.partner_key = llpp.partner_key
                WHERE aml.id = llpp.id OR aml.parent_state='posted';
            """)
            self.env.invalidate_all()

            # Крок 6: Розрахунок bio_opening_by_account_partner для pivot view з фільтром по даті
            _logger.info("Calculating bio_opening_by_account_partner for pivot view...")
            self.env.cr.execute("""
                WITH ranked AS (
                    SELECT
                        id,
                        bio_initial_balance,
                        ROW_NUMBER() OVER (
                            PARTITION BY account_id, COALESCE(partner_id,0)
                            ORDER BY date ASC, id ASC
                        ) AS rn
                    FROM account_move_line
                    WHERE parent_state='posted'
                )
                UPDATE account_move_line aml
                SET bio_opening_by_account_partner = CASE
                    WHEN ranked.rn = 1 THEN ranked.bio_initial_balance
                    ELSE 0
                END
                FROM ranked
                WHERE ranked.id = aml.id;
            """)
            self.env.invalidate_all()

            # Крок 7: Розрахунок bio_opening_by_partner для pivot view
            _logger.info("Calculating bio_opening_by_partner for pivot view...")
            self.env.cr.execute("""
                WITH first_lines_per_account AS (
                    -- Знаходимо перший рядок для кожного account+partner
                    SELECT DISTINCT ON (account_id, COALESCE(partner_id,0))
                        id,
                        partner_id,
                        bio_initial_balance,
                        date
                    FROM account_move_line
                    WHERE parent_state='posted'
                    ORDER BY account_id, COALESCE(partner_id,0), date ASC, id ASC
                ),
                partner_opening_totals AS (
                    -- Сумуємо початкові баланси по партнерам
                    SELECT
                        COALESCE(partner_id,0) as partner_key,
                        SUM(bio_initial_balance) as total_opening_balance
                    FROM first_lines_per_account
                    GROUP BY COALESCE(partner_id,0)
                ),
                first_line_per_partner AS (
                    -- Знаходимо самий перший рядок для кожного партнера
                    SELECT DISTINCT ON (COALESCE(partner_id,0))
                        id,
                        COALESCE(partner_id,0) as partner_key
                    FROM account_move_line
                    WHERE parent_state='posted'
                    ORDER BY COALESCE(partner_id,0), date ASC, id ASC
                )
                UPDATE account_move_line aml
                SET bio_opening_by_partner = CASE
                    WHEN flpp.id IS NOT NULL THEN COALESCE(pot.total_opening_balance, 0)
                    ELSE 0
                END
                FROM first_line_per_partner flpp
                LEFT JOIN partner_opening_totals pot ON pot.partner_key = flpp.partner_key
                WHERE aml.id = flpp.id OR aml.parent_state='posted';
            """)
            self.env.invalidate_all()

            _logger.info("Balance reset and update completed successfully!")
            return True

        except Exception as e:
            _logger.error("Failed to reset and update balances: %s", str(e), exc_info=True)
            return False