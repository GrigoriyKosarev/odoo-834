# -*- coding: utf-8 -*-

{
    "name": 'Biosphera - Account',
    "author": 'Biosphera',
    'category': 'Accounting/Accounting',
    'version': '16.0.6.13.0',
    'description': 'Biosphera. Accounting',
    'license': 'LGPL-3',
    'depends': ['account',
                'account_accountant',
                'selferp_l10n_ua_vat',
                'selferp_cashflow_analytic',
                'l10n_ro_account_edi_ubl',
                'us_account_report_invoice',
                'us_account_report_invoice_polska',
                'bio_extra',
                'selferp_l10n_ua_bank_statement_import'
                ],
    'data': ['security/account_security.xml',
             'security/ir.model.access.csv',
             'views/account_move_views.xml',
             'views/account_move_line_views.xml',
             'views/account_move_line_balance_views.xml',
             'views/bank_rec_widget_views.xml',
             'views/res_bank_views.xml',
             'views/partner_views.xml',
             'report/account_invoice_report_view.xml',
             'report/account_report.xml',
             'report/report_credit_note.xml',
             'report/report_invoice_document_template.xml',
             'report/report_invoice_polska_inherit_bio.xml',
             ],
    'assets': {
        'web.assets_backend': [
            'bio_accounting/static/src/css/bio.css', # ODOO-472
        ],
    },
    'post_init_hook': 'post_init_update_balances',
    'auto_install': False,
}
