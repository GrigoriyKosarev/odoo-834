
import datetime
import json

from odoo import fields, models, _, api
from odoo.exceptions import UserError

from odoo.tools import float_round
from odoo.tools import float_is_zero

import logging
import pprint

_logger = logging.getLogger(__name__)


class DotDict(dict):
    def __getattr__(self, key):
        return self[key]

    # def __setattr__(self, key, value):
    #     self[key] = value


class AccountMove(models.Model):
    _inherit = "account.move"

    date_of_receipt_by_buyer = fields.Date(string='Date of Receipt by Buyer', copy=False)
    bio_payments = fields.Text(compute='_compute_bio_payments', store=False)  # ODOO-462
    bio_factoring = fields.Boolean(string='Factoring') # ODOO-476
    # ODOO-693 begin
    bio_reverse_account_move = fields.Many2one(comodel_name='account.move', string='Credit Note')
    bio_reverse_entry_ids = fields.One2many(comodel_name='account.move', inverse_name='bio_reverse_account_move', string='Reverse Entries')
    bio_reverse_entry_count = fields.Integer(string="Reverse Entries", compute="_compute_bio_reverse_entry_count")
    # ODOO-693 end

    @api.depends('bank_partner_id', 'bio_factoring')
    def _compute_partner_bank_id(self): # ODOO-476
        super(AccountMove, self)._compute_partner_bank_id()

        for move in self:
            if move.move_type == 'out_invoice':
                move.partner_bank_id = self._get_invoice_partner_bank(move)

    def _get_invoice_partner_bank(self, move):
        if not move.company_id or not move.company_id.partner_id:
            return False
        if move.bio_factoring:
            factoring_bank = move.company_id.partner_id.bank_ids.filtered(lambda bank: bank.bio_factoring)
            if not factoring_bank:
                bank_ids = move.bank_partner_id.bank_ids.filtered(
                    lambda bank: not bank.company_id or bank.company_id == move.company_id)
                factoring_bank = bank_ids[0] if bank_ids else False
        else:
            bank_ids = move.bank_partner_id.bank_ids.filtered(
                lambda bank: not bank.company_id or bank.company_id == move.company_id)
            factoring_bank = bank_ids[0] if bank_ids else False
        return factoring_bank or False
        # ODOO-476
        # if not self.bio_factoring:
        #     return self.partner_bank_id
        #
        # if not self.company_id or not self.company_id.partner_id:
        #     return self.partner_bank_id
        #
        # factoring_bank = self.company_id.partner_id.bank_ids.filtered(lambda bank: bank.bio_factoring)
        # return factoring_bank[:1] or self.partner_bank_id

    @api.onchange('invoice_payments_widget')  # ODOO-462
    def _compute_bio_payments(self):
        date_format = self.env['res.lang'].search([('code', '=', self.env.user.lang)], limit=1).date_format
        for rec in self:
            rec.bio_payments = ''
            if type(rec.invoice_payments_widget) == dict:
                for paying in rec.invoice_payments_widget['content']:
                    if rec.bio_payments:
                        rec.bio_payments += ';\n'
                    currency_symbol = self.env['res.currency'].browse(paying['currency_id']).symbol
                    if paying['journal_name'] == 'Exchange rate differences':
                        rec.bio_payments += f"{paying['amount']:.2f}" + ' ' + currency_symbol + ' Exchange Difference'
                    else:
                        rec.bio_payments += 'Paid on ' + paying['date'].strftime(
                            date_format) + '  ' + f"{paying['amount']:.2f}" + ' ' + currency_symbol

    def _get_group_tax_line(self):
        tax_dict = {}
        for line in self.line_ids:
            if line.price_subtotal != 0 and line.tax_ids:
                tax_amount = float_round(line.tax_ids.amount * line.price_subtotal / 100, 2)
                tax_current = tax_dict.get(line.tax_ids)
                if tax_current is None:
                    tax_dict[line.tax_ids] = [line.price_subtotal, tax_amount]
                else:
                    tax_dict[line.tax_ids] = [float_round(tax_current[0] + line.price_subtotal, 2), float_round(tax_current[1] + tax_amount, 2)]

        new_list = []
        for tax, sum in tax_dict.items():
            group = {'tax': tax,
                     'tax_amount': tax.amount,
                     'price_subtotal': sum[0],
                     'tax_sum': sum[1]}
            new_list.append(group)

        return new_list

    def _get_values_from_sale_order(self):
        data = super()._get_values_from_sale_order()

        # company_id.id == 1   'S.C. Alufix S.R.L.'
        if self.company_id.id == 1 and self.invoice_date and self.invoice_date > datetime.date(2024, 6, 30):
            # partsname = self.name.split("/")
            # if len(partsname) == 3 and len(partsname[1]) == 4:
            #     partsname[1] = partsname[1][2:]
            #     data['invoice_number'] = "/".join(partsname)
            # else:
            #     data['invoice_number'] = self.name
            data['invoice_number'] = self.name

        return data

    def _bio_get_partner_shipping_info(self, doc):
        partner_shipping = DotDict()
        country_id = DotDict()
        parent_id = DotDict()
        partner_shipping['vat'] = doc.partner_shipping_id.vat
        partner_shipping['display_name'] = doc.partner_shipping_id.display_name
        parent_id['display_name'] = doc.partner_shipping_id.parent_id.display_name
        partner_shipping['parent_id'] = parent_id
        partner_shipping['street'] = doc.partner_shipping_id.street
        partner_shipping['zip'] = doc.partner_shipping_id.zip
        partner_shipping['city'] = doc.partner_shipping_id.city
        country_id['display_name'] = doc.partner_shipping_id.country_id.display_name
        partner_shipping['country_id'] = country_id
        partner_shipping['gln_code'] = doc.partner_shipping_id.gln_code
        partner_shipping['ref'] = doc.partner_shipping_id.ref

        if doc.partner_id.bio_print_delivery_address_in_invoice_from_parametr or doc.partner_shipping_id.bio_print_delivery_address_in_invoice_from_parametr:
            partner_shipping['display_name'] = doc.partner_shipping_id.name
            partner_shipping['parent_id']['display_name'] = doc.partner_shipping_id.name

            parameter_type = self.env['bio.type.partner.additional.parameters'].sudo().search([('name', '=', 'Delivery Address name for Invoice')], limit=1)
            if parameter_type:
                parameter = self.env['bio.partner.additional.parameters'].sudo().search([('company_id', '=', doc.company_id.id),
                                                                                         ('partner_id', '=', doc.partner_shipping_id.id),
                                                                                         ('additional_parameter_type_id', '=', parameter_type.id)], limit=1)
                if parameter.id and parameter.parameter_str:
                    words = parameter.parameter_str.split("/")

                    if len(words) > 0:
                        partner_shipping['display_name'] = words[0]
                    else:
                        partner_shipping['display_name'] = ''
                    partner_shipping['parent_id']['display_name'] = partner_shipping.display_name

                    if len(words) > 1:
                        partner_shipping['street'] = words[1]
                    else:
                        partner_shipping['street'] = ''

                    if len(words) > 2:
                        partner_shipping['zip'] = words[2]
                    else:
                        partner_shipping['zip'] = ''

                    if len(words) > 3:
                        partner_shipping['city'] = words[3]
                    else:
                        partner_shipping['city'] = ''

                    if len(words) > 4:
                        partner_shipping['country_id']['display_name'] = words[4]
                    else:
                        partner_shipping['country_id']['display_name'] = ''

                    if len(words) > 5:
                        partner_shipping['gln_code'] = words[5]
                    else:
                        partner_shipping['gln_code'] = ''

        return partner_shipping

    @api.onchange('invoice_line_ids', 'reversed_entry_id', 'state')
    def _onchange_invoice_line_ids(self):
        # if self.move_type == 'out_refund' and self.state == 'draft':
            # self._credit_note_check_correct_invoice_price_qty(self, False)
        pass

    def button_draft(self):
        # ODOO-477
        for rec in self:
            self._check_prohibit_change(rec)

        res = super(AccountMove, self).button_draft()
        # for move in self:
            # self._credit_note_check_correct_invoice_price_qty(move, False)
        return res

    def action_post(self):
        for move in self:
            if move.date_of_receipt_by_buyer is False:
                move.date_of_receipt_by_buyer = move.invoice_date
            self._credit_note_check_correct_invoice_price_qty(move, True)
        return super(AccountMove, self).action_post()

    def _credit_note_check_correct_invoice_price_qty(self, credit_note, is_user_error=True):
        if credit_note.move_type == 'out_refund':
            if not credit_note.price_change_mode and self.reversed_entry_id:
                for line in credit_note.invoice_line_ids:
                    invoice_line = credit_note.reversed_entry_id.invoice_line_ids.filtered(
                        lambda invoice_line: invoice_line.product_id == line.product_id
                    )
                    if not invoice_line:
                        message = _("Attempting to return an item that did not ship on invoice!!!")
                        self._handle_credit_note_error(message, is_user_error)
                        return

                    invoice = invoice_line[0]
                    if invoice.product_id.detailed_type != 'product':
                        continue
                    if line.quantity > invoice.quantity:
                        message = _("Attempting to return a larger quantity than was shipped on the invoice!!!")
                        self._handle_credit_note_error(message, is_user_error)
                        return
                    elif line.price_unit != invoice.price_unit:
                        message = _("Attempting to return a different price than was shipped on the invoice!!!")
                        self._handle_credit_note_error(message, is_user_error)
                        return

    def _handle_credit_note_error(self, message, is_user_error):
        if is_user_error:
            raise UserError(message)
        else:
            self._show_notification_credit_note(message)

    def _show_notification_credit_note(self, message):
        self.env['bus.bus']._sendone(self.env.user.partner_id,
                                     "simple_notification",
                                     {
                                         "title": "Warning",
                                         "message": message,
                                         "sticky": True,
                                         # "warning": True,
                                     })
        return True

    def _credit_note_reversal_lines(self):
        if not self.reversed_entry_id:
            return []
        account_move_line_ids = self.reversed_entry_id.invoice_line_ids.sorted(key=lambda l: (-l.sequence, l.date, l.move_name, -l.id), reverse=True)
        return account_move_line_ids

    def _credit_note_info(self, line_id, credit_note_invoice_line_ids):
        res = {
            'po_kor_quantity': 0,
            'po_kor_product_uom_name': '',
            'po_kor_discount': 0,
            'po_kor_price_netto': 0,
            'po_kor_price_subtotal': 0,
            'po_kor_tax_ids_amount': 0,
            'po_kor_kwota_vat': 0,
            'po_kor_wartost_brutto': 0,
            'kor_quantity': 0,
            'kor_product_uom_name': '',
            'kor_discount': 0,
            'kor_price_netto': 0,
            'kor_price_subtotal': 0,
            'kor_tax_ids_amount': 0,
            'kor_kwota_vat': 0,
            'kor_wartost_brutto': 0,
            'credit_note_line_id': 0,
            'sum_kor_price_netto': 0,
            'sum_kor_kwota_vat': 0,
            'sum_kor_wartost_brutto': 0,
        }

        invoice_line_id = self.env['account.move.line'].browse(line_id)
        if not invoice_line_id.exists():
            return res

        matching_line = self.invoice_line_ids.filtered(lambda l: l.product_id == invoice_line_id.product_id)
        if matching_line:
            if matching_line.id in credit_note_invoice_line_ids:
                credit_note_invoice_line_ids.remove(matching_line.id)
            res['credit_note_line_id'] = matching_line[0].id
            if self.price_change_mode:
                res['kor_quantity'] = 0
            else:
                res['kor_quantity'] = 0 if matching_line[0].quantity == 0 else -1 * matching_line[0].quantity
            res['kor_product_uom_name'] = matching_line[0].product_uom_id.name
            res['kor_discount'] = 0 if matching_line[0].discount == 0 else -1 * matching_line[0].discount
            kor_price_netto = matching_line[0].price_unit * (1 - (matching_line[0].discount or 0.0) / 100.0)
            res['kor_price_netto'] = 0 if kor_price_netto == 0 else -1 * kor_price_netto
            res['kor_price_subtotal'] = 0 if matching_line[0].price_subtotal == 0 else -1 * matching_line[0].price_subtotal
            res['kor_tax_ids_amount'] = matching_line[0].tax_ids.amount
            # kor_kwota_vat = matching_line[0].price_subtotal * matching_line[0].tax_ids.amount / 100
            kor_kwota_vat = matching_line[0].tax_amount
            res['kor_kwota_vat'] = 0 if kor_kwota_vat == 0 else -1 * kor_kwota_vat
            # kor_wartost_brutto = matching_line[0].price_subtotal * (1 + (matching_line[0].tax_ids.amount or 0.0) / 100.0)
            kor_wartost_brutto = matching_line[0].price_total
            res['kor_wartost_brutto'] = 0 if kor_wartost_brutto == 0 else -1 * kor_wartost_brutto

            res['po_kor_quantity'] = invoice_line_id.quantity if res['kor_quantity'] == 0 else res['kor_quantity'] + invoice_line_id.quantity
            res['po_kor_product_uom_name'] = invoice_line_id.product_uom_id.name
            res['po_kor_discount'] = invoice_line_id.discount if res['kor_discount'] == 0 else res['kor_discount'] + invoice_line_id.discount
            po_kor_price_netto = (invoice_line_id.price_unit * (1 - (invoice_line_id.discount or 0.0) / 100.0))
            res['po_kor_price_netto'] = po_kor_price_netto if res['kor_price_netto'] == 0 else res['kor_price_netto'] + po_kor_price_netto
            res['po_kor_price_subtotal'] = invoice_line_id.price_subtotal if res['kor_price_subtotal'] == 0 else res['kor_price_subtotal'] + invoice_line_id.price_subtotal
            res['po_kor_tax_ids_amount'] = invoice_line_id.tax_ids.amount if res['kor_tax_ids_amount'] == 0 else res['kor_tax_ids_amount'] + invoice_line_id.tax_ids.amount
            # po_kor_kwota_vat = (invoice_line_id.price_subtotal * invoice_line_id.tax_ids.amount / 100)
            po_kor_kwota_vat = invoice_line_id.tax_amount
            res['po_kor_kwota_vat'] = po_kor_kwota_vat if res['kor_kwota_vat'] == 0 else res['kor_kwota_vat'] + po_kor_kwota_vat
            # kor_wartost_brutto = (invoice_line_id.price_subtotal * (1 + (invoice_line_id.tax_ids.amount or 0.0) / 100.0))
            kor_wartost_brutto = invoice_line_id.price_total
            res['po_kor_wartost_brutto'] = kor_wartost_brutto if res['kor_wartost_brutto'] == 0 else res['kor_wartost_brutto'] + kor_wartost_brutto
        else:
            res['po_kor_quantity'] = invoice_line_id.quantity
            res['po_kor_product_uom_name'] = invoice_line_id.product_uom_id.name
            res['po_kor_discount'] = invoice_line_id.discount
            res['po_kor_price_netto'] = (invoice_line_id.price_unit * (1 - (invoice_line_id.discount or 0.0) / 100.0))
            res['po_kor_price_subtotal'] = invoice_line_id.price_subtotal
            res['po_kor_tax_ids_amount'] = invoice_line_id.tax_ids.amount
            res['po_kor_kwota_vat'] = invoice_line_id.tax_amount
            # res['po_kor_kwota_vat'] = (invoice_line_id.price_subtotal * invoice_line_id.tax_ids.amount / 100)
            res['po_kor_wartost_brutto'] = invoice_line_id.price_total
            # res['po_kor_wartost_brutto'] = (invoice_line_id.price_subtotal * (1 + (invoice_line_id.tax_ids.amount or 0.0) / 100.0))

        return res

    def _credit_note_group_tax_line(self, move_id):
        grouped_data = self.env['account.move.line'].read_group(
            domain=[('move_id', '=', move_id)],
            fields=['group_tax_id', 'tax_ids', 'price_subtotal:sum'],
            groupby=['tax_ids'], lazy=True)
        new_list = []
        for group in grouped_data:
            if group['price_subtotal'] != 0 and group['tax_ids']:
                tax = self.env['account.tax'].search([('id', '=', group['tax_ids'][0])])
                group['tax'] = tax
                group['tax_amount'] = tax.amount
                new_list.append(group)

        return new_list

    def _credit_note_tax_values(self):
        invoice_tax_ids = []
        sum_inv_ids = {
            'price_subtotal': 0,
            'kwota_vat': 0,
            'vartost_brutto': 0,
        }
        if self.reversed_entry_id:
            for val in self._credit_note_group_tax_line(self.reversed_entry_id.id):
                sum_inv_ids['price_subtotal'] += val['price_subtotal']
                sum_inv_ids['kwota_vat'] += val['price_subtotal'] * val['tax_amount'] / 100
                sum_inv_ids['vartost_brutto'] += val['price_subtotal'] * (1 + (val['tax_amount'] or 0.0) / 100.0)

                invoice_tax_ids.append({
                    'tax_amount': val['tax_amount'],
                    'price_subtotal': val['price_subtotal'],
                    'kwota_vat': val['price_subtotal'] * val['tax_amount'] / 100,
                    'vartost_brutto': val['price_subtotal'] * (1 + (val['tax_amount'] or 0.0) / 100.0),
                })
        po_kor_ids = {
            'price_subtotal': 0,
            'kwota_vat': 0,
            'vartost_brutto': 0,
        }
        for val in self._credit_note_group_tax_line(self.id):
            po_kor_ids['price_subtotal'] += val['price_subtotal']
            po_kor_ids['kwota_vat'] += val['price_subtotal'] * val['tax_amount'] / 100
            po_kor_ids['vartost_brutto'] += val['price_subtotal'] * (1 + (val['tax_amount'] or 0.0) / 100.0)

        kor_ids = {
            'price_subtotal': po_kor_ids['price_subtotal'] - sum_inv_ids['price_subtotal'],
            'kwota_vat': po_kor_ids['kwota_vat'] - sum_inv_ids['kwota_vat'],
            'vartost_brutto': po_kor_ids['vartost_brutto'] - sum_inv_ids['vartost_brutto'],
        }

        return {
            'invoice_tax_ids': invoice_tax_ids,
            'po_kor_ids': po_kor_ids,
            'kor_ids': kor_ids,
        }

    def _credit_note_w_termine(self):
        res = ''
        if self.reversed_entry_id:
            term_id = self.reversed_entry_id.invoice_payment_term_id
            if term_id:
                days_qty = sum(term_id.line_ids.mapped('days'))
                res = f"{term_id.name} = {self.invoice_date + datetime.timedelta(days=days_qty)}"
        return res

    def _get_comment_for_factoring(self):
        # sale_order = self._get_sale_order_data(self.invoice_origin)
        # if sale_order and sale_order.bio_factoring:
        #     return self.env['bio.partner.additional.parameters'].get_comment_for_factoring_in_the_invoice(self.company_id.id, self.invoice_date)
        # ODOO-476
        if self.bio_factoring:
            return self.env['bio.partner.additional.parameters'].get_comment_for_factoring_in_the_invoice(
                self.company_id.id, self.invoice_date)
        return ""

    def _get_sale_order_data(self, invoice_origin):
        if invoice_origin:
            sale_order = self.env['sale.order'].search([('name', '=', invoice_origin)], limit=1)
            return sale_order if sale_order else False
        return False

    def write(self, vals):
        # ODOO-477
        for rec in self:
            self._check_prohibit_change(rec, vals)

        res = super().write(vals)

        if 'invoice_line_ids' in vals.keys():     # ODOO-472
            price_precision = self.env['decimal.precision'].precision_get('Product Price')
            for rec in self:
                for line in rec.invoice_line_ids:
                    text_line = ''
                    if float_is_zero(line.price_unit, precision_digits=price_precision):
                        text_line += 'price not specified'
                    # if not line.product_packaging_qty.is_integer():
                    #     text_line += '' if text_line == '' else ', '
                    #     text_line += 'not a whole number of packages'
                    if ((len(line.tax_ids.ids) == 0 and line.currency_id == line.company_id.currency_id) or
                            (len(line.tax_ids.ids) == 0 and line.move_id.type_name == 'Vendor Bill')):
                        text_line += '' if text_line == '' else ', '
                        text_line += 'no tax specified'
                    if text_line != '':
                        account_name = f'(* {rec.id})' if rec.name == '/' else rec.name
                        message = _("In %s: the line with the product %s:   %s") % (account_name, line.product_id.display_name, text_line)
                        self.env['bus.bus']._sendone(self.env.user.partner_id, "simple_notification", {"title": "Warning line filling",
                                                                                                       "message": message,
                                                                                                       "sticky": True, })
        return res

    def _get_invoice_status(self, move_id):
        if not move_id:
            return ""
        with self.pool.cursor() as new_cr:
            new_cr.execute(
                "SELECT state FROM account_move WHERE id = %s",
                (move_id,)
            )
            result = new_cr.fetchone()
            if result and result[0]:
                return result[0]
        return ""

    @api.model
    def _check_prohibit_change(self, rec, vals=None): # ODOO-477
        if rec.move_type == 'out_invoice':
            if vals is None:
                vals = []
            technical_fields = ['needed_terms_dirty', 'message_main_attachment_id', 'access_token', 'is_move_sent',
                                'bio_factoring', 'date_of_receipt_by_buyer']

            if any(field in vals for field in technical_fields):
                return

            param = self.env['ir.config_parameter'].sudo().get_param('bio_prohibit_invoice_change_company_ids',
                                                                                default='[]')
            company_ids = json.loads(param)
            if (
                    self.env.user.has_group('bio_accounting.group_prohibit_changing_invoices_after_approval')
                    and (rec.company_id.id in company_ids)
                    and self._get_invoice_status(rec.id) == 'posted'
            ):
                raise UserError(_("Prohibit changing invoices after approval."))

    def get_vat_to_display(self):
        # ODOO-596
        self.ensure_one()
        quotation = self.env['sale.order'].search([('name', '=', self.invoice_origin)], limit=1)
        if quotation and quotation.warehouse_id.bio_VAT_alt:
            if self.company_id and self.company_id.partner_id.vat_alt_bio:
                return self.company_id.partner_id.vat_alt_bio
        return self.company_id.vat

    # ODOO-693 begin
    @api.depends('bio_reverse_entry_ids')
    def _compute_bio_reverse_entry_count(self):
        for move in self:
            move.bio_reverse_entry_count = len(move.bio_reverse_entry_ids)

    def action_bio_reverse_entry(self):
        self.ensure_one()

        journal = self.env['account.journal'].search(
            [('type', '=', 'general'),('company_id', '=', self.company_id.id),('active', '=', True)], limit=1
        )
        if not journal:
            raise UserError(_("There is no Miscellaneous journal type (general)."))

        line_vals = []
        move_vals = {
            'bio_reverse_account_move': self.id,
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': _('Reverse Entry from %s') % self.name,
            'move_type': 'entry',
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': line_vals,
        }

        for line in self.line_ids:
            new_debit = -line.debit if line.debit else 0.0
            new_credit = -line.credit if line.credit else 0.0
            new_amount_currency = -line.amount_currency if line.amount_currency else 0.0
            new_price_unit = -line.price_unit if line.price_unit else 0.0

            line_vals.append((0, 0, {
                'account_id': line.account_id.id,
                'journal_id': journal.id,
                'name': line.name or '/',
                'quantity': line.quantity,
                'debit': new_debit,
                'credit': new_credit,
                'partner_id': line.partner_id.id,
                'analytic_account_id': line.analytic_account_id.id if line.analytic_account_id else False,
                # 'analytic_line_ids': [(6, 0, line.analytic_line_ids.ids)],
                'currency_id': line.currency_id.id,
                'amount_currency': new_amount_currency,
                'company_id': line.company_id.id,
                'product_id': line.product_id.id if line.product_id else False,
                'linked_sale_order_id': line.linked_sale_order_id.id if line.linked_sale_order_id else False,
                'linked_purchase_order_id': line.linked_purchase_order_id.id if line.linked_purchase_order_id else False,
                'price_unit': new_price_unit,
                # 'display_type': line.display_type,
                # 'tax_ids': [(6, 0, line.tax_ids.ids)],
                # 'tax_tag_ids': [(6, 0, line.tax_tag_ids.ids)],
            }))
        move_id = self.env['account.move'].create(move_vals)

        for line, orig_line in zip(move_id.line_ids, self.line_ids):
            if orig_line.linked_sale_order_id:
                line.linked_sale_order_id = orig_line.linked_sale_order_id.id

        return {
            'name': _('Reverse Journal Entry'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move_id.id,
            'target': 'current',
        }

    def action_bio_view_reverse_entryes(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_journal_line")
        action.update({
            "name": _("Reverse Entries"),
            "domain": [("id", "in", self.bio_reverse_entry_ids.ids)],
            "context": {
                "default_bio_reverse_account_move": self.id,
            },
        })
        return action
    # ODOO-693 end


class AccountInvoiceReport(models.Model):
    _inherit = "account.invoice.report"

    date_of_receipt_by_buyer = fields.Date(readonly=True, string="Date of Receipt by Buyer")

    _depends = {'account.move': ['date_of_receipt_by_buyer']}

    def _select(self):
        return super()._select() + ", move.date_of_receipt_by_buyer"