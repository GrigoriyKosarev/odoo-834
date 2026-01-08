# -*- coding: utf-8 -*-
{
    'name': 'Biosphera - Account Balance',
    'version': '16.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Calculate and display opening/closing balances for account move lines',
    'description': """
        ODOO-834
    """,
    'author': 'Biosphera',
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
    # ODOO-834: Post-init hook disabled - run "Reset and Update" manually after installation
    # 'post_init_hook': 'post_init_update_balances',
}
