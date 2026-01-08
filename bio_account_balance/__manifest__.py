# -*- coding: utf-8 -*-
{
    'name': 'Bio Account Balance',
    'version': '16.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Calculate and display opening/closing balances for account move lines',
    'description': """
Calculate cumulative balances using SQL window functions.
Display initial and end balance for each journal item.
Dynamic opening/closing balance calculation in pivot view.
Optimized for large datasets with incremental updates.
Support for date filtering in pivot view.

Technical: PostgreSQL window functions, separate balance table, read_group override, direct SQL queries.

ODOO-834
    """,
    'author': 'Bio',
    'website': 'https://bio.com',
    'license': 'LGPL-3',
    'depends': [
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_line_views.xml',
        'views/account_move_line_balance_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_update_balances',
}
