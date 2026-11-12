import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EinvoiceConfirmWizard(models.TransientModel):
    _name = 'einvoice.confirm.wizard'
    _description = 'Confirm E-Invoice Submission'

    move_id = fields.Many2one('account.move', required=True, readonly=True)
    amount_total = fields.Monetary(related='move_id.amount_total')
    currency_id = fields.Many2one(related='move_id.currency_id')
    partner_id = fields.Many2one(related='move_id.partner_id')

    transaction_type = fields.Selection([
        ("B2B","B2B - Business to Business"),
        ("B2C","B2C - Business to Customer"),
        ("B2G","B2G - Business to Government"),
    ], string="Transaction Type", help="Note: Tin Number is required for B2B transactions.")
    buyer_tin = fields.Char(string='Buyer TIN')
    buyer_name = fields.Char(string='Buyer Name')
    buyer_phone = fields.Char(string='Buyer Phone')
    buyer_email = fields.Char(string='Buyer Email')
    buyer_region = fields.Selection([
        ('3', 'Tigray'), ('4', 'Afar'), ('11', 'Amhara'),
        ('2', 'Oromia'), ('6', 'Somali'), ('5', 'Benishangul Gumuz'),
        ('7', 'Gambella'), ('9', 'SNNPRS'), ('13', 'Addis Ababa'),
        ('10', 'DireDawa'), ('17', 'Central Ethiopia'),
        ('14', 'Sidama'), ('15', 'South West'),
    ], string='Buyer Region')
    buyer_city = fields.Char(string='Buyer City')
    buyer_wereda = fields.Char(string='Buyer Wereda')
    mode_of_payment = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        ('CREDIT', 'CREDIT'),
        # ('CHEQUE', 'Cheque'),
        # ('CPO', 'CPO'),
        # ('Local Bank Transfer', 'Local Bank Transfer'),
        # ('SWIFT', 'SWIFT'),
        # ('Wire Transfer', 'Wire Transfer'),
        # ('Letter of Credit', 'Letter of Credit'),
        # ('Card', 'Card'),
    ], string='Mode of Payment')
    payment_term = fields.Selection([
        ('IMMEDIATE', 'Immediate'),
    ], string='Payment Term')
    system_type = fields.Selection([
        ('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS'),
    ], string='System Type')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get('move_id')
        if move_id:
            move = self.env['account.move'].browse(move_id)
            res.update({
                'transaction_type': move.transaction_type or 'B2B',
                'buyer_tin': move.buyer_vat or '',
                'buyer_name': move.partner_id.name or '',
                'buyer_phone': move.partner_id.phone or move.buyer_phone or '',
                'buyer_email': move.partner_id.email or move.buyer_email or '',
                'buyer_region': move.buyer_region or False,
                'buyer_city': move.buyer_city or '',
                'buyer_wereda': move.buyer_wereda or '',
                'mode_of_payment': move.mode_of_payment or False,
                'payment_term': move.payment_term or 'IMMEDIATE',
                'system_type': move.system_type or 'ERP',
            })
        return res

    def action_confirm(self):
        self.ensure_one()
        self.move_id.write({
            'transaction_type': self.transaction_type,
            'buyer_vat': self.buyer_tin,
            'buyer_city': self.buyer_city,
            'buyer_wereda': self.buyer_wereda,
            'buyer_region': self.buyer_region,
            'mode_of_payment': self.mode_of_payment,
            'payment_term': self.payment_term,
        })
        if self.buyer_phone:
            self.move_id.buyer_phone = self.buyer_phone
        if self.buyer_email:
            self.move_id.buyer_email = self.buyer_email

        service = self.env['einvoice.invoice.service']
        try:
            service.register_single_invoice(self.move_id)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Invoice registered successfully. IRN: %s') % (self.move_id.x_einvoice_irn or ''),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        except UserError:
            raise
        except Exception as e:
            _logger.info("E-Invoice registration error: %s", str(e))
            raise UserError(_("E-Invoice registration error: %s") % str(e))


class EinvoiceCreditDebitConfirmWizard(models.TransientModel):
    _name = 'einvoice.credit.debit.confirm.wizard'
    _description = 'Confirm Credit/Debit Note E-Invoice Submission'

    move_id = fields.Many2one('account.move', required=True, readonly=True)
    amount_total = fields.Monetary(related='move_id.amount_total')
    currency_id = fields.Many2one(related='move_id.currency_id')
    partner_id = fields.Many2one(related='move_id.partner_id')

    transaction_type = fields.Selection([
        ('B2B', 'B2B'), ('B2C', 'B2C'),
    ], string='Transaction Type')
    buyer_tin = fields.Char(string='Buyer TIN')
    buyer_name = fields.Char(string='Buyer Name')
    buyer_phone = fields.Char(string='Buyer Phone')
    buyer_email = fields.Char(string='Buyer Email')
    buyer_region = fields.Selection([
        ('3', 'Tigray'), ('4', 'Afar'), ('11', 'Amhara'),
        ('2', 'Oromia'), ('6', 'Somali'), ('5', 'Benishangul Gumuz'),
        ('7', 'Gambella'), ('9', 'SNNPRS'), ('13', 'Addis Ababa'),
        ('10', 'DireDawa'), ('17', 'Central Ethiopia'),
        ('14', 'Sidama'), ('15', 'South West'),
    ], string='Buyer Region')
    buyer_city = fields.Char(string='Buyer City')
    buyer_wereda = fields.Char(string='Buyer Wereda')
    mode_of_payment = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        ('CREDIT', 'CREDIT'),
        # ('CHEQUE', 'Cheque'),
        # ('CPO', 'CPO'),
        # ('Local Bank Transfer', 'Local Bank Transfer'),
        # ('SWIFT', 'SWIFT'),
        # ('Wire Transfer', 'Wire Transfer'),
        # ('Letter of Credit', 'Letter of Credit'),
        # ('Card', 'Card'),
    ], string='Mode of Payment')
    payment_term = fields.Selection([
        ('IMMEDIATE', 'Immediate'),
    ], string='Payment Term')
    system_type = fields.Selection([
        ('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS'),
    ], string='System Type')
    re_einvoice_reason = fields.Selection([
        ('1', 'Duplicate'),
        ('2', 'Data Entry Mistake'),
        ('3', 'Order Canceled'),
        ('4', 'Others'),
    ], string='Reason', required=True)
    reason = fields.Char(string='Reason for Credit/Debit Note')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get('move_id')
        if move_id:
            move = self.env['account.move'].browse(move_id)
            res.update({
                'transaction_type': move.transaction_type or 'B2B',
                'buyer_tin': move.buyer_vat or '',
                'buyer_name': move.partner_id.name or '',
                'buyer_phone': move.partner_id.phone or move.buyer_phone or '',
                'buyer_email': move.partner_id.email or move.buyer_email or '',
                'buyer_region': move.buyer_region or False,
                'buyer_city': move.buyer_city or '',
                'buyer_wereda': move.buyer_wereda or '',
                'mode_of_payment': move.mode_of_payment or False,
                'payment_term': move.payment_term or 'IMMEDIATE',
                'system_type': move.system_type or 'ERP',
                're_einvoice_reason': move.re_einvoice_reason or False,
                'reason': move.reason or '',
            })
        return res

    def action_confirm(self):
        self.ensure_one()
        move = self.move_id
        move.write({
            'transaction_type': self.transaction_type,
            'buyer_vat': self.buyer_tin,
            'buyer_city': self.buyer_city,
            'buyer_wereda': self.buyer_wereda,
            'buyer_region': self.buyer_region,
            'mode_of_payment': self.mode_of_payment,
            'payment_term': self.payment_term,
            're_einvoice_reason': self.re_einvoice_reason,
            'reason': self.reason,
        })
        if self.buyer_phone:
            move.buyer_phone = self.buyer_phone
        if self.buyer_email:
            move.buyer_email = self.buyer_email
        service = self.env['einvoice.invoice.service']
        # try:
        service.register_credit_debit_note(move)
        label = _('Credit Note') if move.move_type == 'out_refund' else _('Debit Note')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('%s registered successfully. IRN: %s') % (label, move.x_einvoice_cn_irn or ''),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
        # except UserError:
        #     raise
        # except Exception as e:
        #     _logger.info("E-Invoice Credit/Debit registration error: %s", str(e))
        #     raise UserError(_("E-Invoice Credit/Debit registration error: %s") % str(e))

class EinvoiceCancelWizard(models.TransientModel):
    _name = 'einvoice.cancel.wizard'
    _description = 'Confirm E-Invoice Cancellation'

    move_id = fields.Many2one('account.move', required=True, readonly=True)
    reason_code = fields.Selection([
        ('1', 'Duplicate'),
        ('2', 'Data Error'),
        ('3', 'Customer Request'),
        ('4', 'Goods Returned'),
        ('5', 'Payment Error'),
        ('6', 'Calculation Error (Bulk Only)'),
    ], required=True)
    remark = fields.Char()

    def action_confirm_cancel(self):
        self.ensure_one()
        _logger.info("Cancel wizard triggered for move %s | reason=%s | remark=%s",
                      self.move_id.id, self.reason_code, self.remark)
        try:
            self.env['einvoice.invoice.service'].cancel_single_invoice(
                self.move_id,
                reason_code=self.reason_code,
                remark=self.remark,
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('E-Invoice cancelled successfully.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        except UserError:
            raise
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }


class EinvoiceVerifyWizard(models.TransientModel):
    _name = 'einvoice.verify.wizard'
    _description = 'Verify E-Invoice'

    move_id = fields.Many2one('account.move', required=True, readonly=True)

    def action_verify(self):
        self.ensure_one()
        try:
            self.env['einvoice.invoice.service'].verify_invoice(self.move_id)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('E-Invoice verified successfully. Status: %s') % (self.move_id.x_einvoice_verified_status or ''),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        except UserError:
            raise
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }


class EinvoiceReceiptWizard(models.TransientModel):
    _name = 'einvoice.receipt.wizard'
    _description = 'Receipt E-Invoice'

    move_id = fields.Many2one('account.move', string="Invoice")
    receipt_response = fields.Text(string="Receipt API Response", readonly=True)

    mode_of_payment = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        # ('CREDIT', 'CREDIT'),
        ('CHEQUE', 'Cheque'),
        ('CPO', 'CPO'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('SWIFT', 'SWIFT'),
        ('WIRE', 'Wire Transfer'),
        ('LETTER_OF_CREDIT', 'Letter of Credit'),
        ('CARD', 'Card'),
    ], string='Mode of Payment')
    payment_service_provider = fields.Selection([
        ("BANK","Bank"),
        ("TELEBIRR","TeleBirr"),
    ], string="Payment Service Provider")
    account_number = fields.Char(string='Account Number')
    transaction_number = fields.Char(string='Transaction Number')
    payment_coverage = fields.Selection([
        ('FULL', 'Full'), ('PARTIAL', 'Partial'),
    ], string='Payment Coverage')
    remaining_amount = fields.Float(string='Remaining Amount')
    collected_amount = fields.Float(string='Collected Amount', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get('move_id')
        if move_id:
            move = self.env['account.move'].browse(move_id)
            # Auto-detect payment coverage
            if move.payment_state in ('paid', 'in_payment'):
                coverage = 'FULL'
                remaining = 0.0
            elif move.payment_state == 'partial':
                coverage = 'PARTIAL'
                remaining = float(move.amount_residual)
            else:
                coverage = False
                remaining = float(move.amount_residual)
            res.update({
                'mode_of_payment': move.mode_of_payment or '',
                'payment_service_provider': move.payment_service_provider or '',
                'account_number': move.account_number or '',
                'transaction_number': move.transaction_number or '',
                'payment_coverage': coverage,
                'remaining_amount': remaining,
                'collected_amount': float(move.amount_total - move.amount_residual),
            })
        return res

    # def action_send_receipt(self):
    #     if not self.move_id:
    #         raise UserError(_("Please select an invoice to send receipt."))
    #     # Write wizard values back to move
    #     self.move_id.write({
    #         'mode_of_payment_receipt': self.mode_of_payment,
    #         'payment_service_provider': self.payment_service_provider,
    #         'account_number': self.account_number,
    #         'transaction_number': self.transaction_number,
    #         'payment_coverage': self.payment_coverage,
    #         'remaining_amount': self.remaining_amount,
    #     })
    #     try:
    #         self.env['einvoice.invoice.service'].send_receipt(self.move_id)
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': _('Success'),
    #                 'message': _('Sales receipt sent successfully.'),
    #                 'type': 'success',
    #                 'sticky': False,
    #                 'next': {'type': 'ir.actions.act_window_close'},
    #             }
    #         }
    #     except UserError:
    #         raise
    #     except Exception as e:
    #         self.move_id.message_post(body=_("Sales receipt error: %s") % str(e))
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': _('Error'),
    #                 'message': str(e),
    #                 'type': 'danger',
    #                 'sticky': True,
    #                 'next': {'type': 'ir.actions.act_window_close'},
    #             }
    #         }
        # try:
        #     results = self.env['einvoice.invoice.service'].send_receipt(self.move_id)
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'display_notification',
        #         'params': {
        #             'title': _('Success'),
        #             'message': _('Sales receipt sent successfully.'),
        #             'type': 'success',
        #             'sticky': False,
        #             'next': {'type': 'ir.actions.act_window_close'},
        #         }
        #     }
        # except UserError:
        #     raise
        # except Exception as e:
        #     self.move_id.message_post(body=_("Sales receipt error: %s") % str(e))
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'display_notification',
        #         'params': {
        #             'title': _('Error'),
        #             'message': str(e),
        #             'type': 'danger',
        #             'sticky': True,
        #             'next': {'type': 'ir.actions.act_window_close'},
        #         }
        #     }


class EinvoiceWithholdingWizard(models.TransientModel):
    _name = 'einvoice.withholding.wizard'
    _description = 'Withholding E-Invoice'

    move_id = fields.Many2one('account.move', string="Invoice")
    currency_id = fields.Many2one(related='move_id.currency_id', readonly=True)
    withholding_irn = fields.Char(string="Invoice IRN")
    pretax_amount = fields.Monetary(string="Pre-Tax Amount", currency_field="currency_id")
    withholding_amount = fields.Monetary(string="Withholding Amount", currency_field="currency_id")
    withholding_response = fields.Text(string="Withholding API Response", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get('move_id')
        if move_id:
            move = self.env['account.move'].browse(move_id)
            service = self.env['einvoice.invoice.service']
            try:
                totals = service._compute_einvoice_totals(move)
                res.setdefault('withholding_amount', float(totals.get('total_wht', 0.0)))
            except Exception:
                res.setdefault('withholding_amount', 0.0)
            res.setdefault('pretax_amount', move.amount_untaxed or 0.0)
            res.setdefault('withholding_irn' or '')
        return res

    def action_send_withholding(self):
        if not self.move_id:
            raise UserError(_("Please select an invoice to send withholding receipt."))
        try:
            results = self.env['einvoice.invoice.service'].send_withholding(
                self.move_id,
                withholding_irn=self.withholding_irn,
                pretax_amount=self.pretax_amount,
                withholding_amount=self.withholding_amount,
            )
            # return {
            #     'type': 'ir.actions.client',
            #     'tag': 'display_notification',
            #     'params': {
            #         'title': _('Success'),
            #         'message': _('Withholding receipt sent successfully.'),
            #         'type': 'success',
            #         'sticky': False,
            #         'next': {'type': 'ir.actions.act_window_close'},
            #     }
            # }
        except UserError:
            raise
        except Exception as e:
            self.move_id.message_post(body=_("Withholding receipt error: %s") % str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
