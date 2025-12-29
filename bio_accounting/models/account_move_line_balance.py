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
    )
    bio_end_balance = fields.Monetary(
        string='End Balance',
        currency_field='company_currency_id',
        readonly=True,
        store=True,
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
        try:
            self.env.cr.execute("TRUNCATE TABLE bio_account_move_line_balance RESTART IDENTITY;")
            self.env.invalidate_all()

            self.update_balances_sql()
            self.env.invalidate_all()

            self.env.cr.execute("""
               UPDATE account_move_line aml
               SET bio_initial_balance = bal.bio_initial_balance,
                   bio_end_balance     = bal.bio_end_balance 
               FROM bio_account_move_line_balance bal
               WHERE bal.move_line_id = aml.id;
            """)
            self.env.invalidate_all()
        except:
            return False
        return True