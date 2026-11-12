import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class EinvoiceManualIrnWizard(models.TransientModel):
    _name = 'einvoice.manual.irn.wizard'
    _description = 'Manual E-Invoice IRN Entry'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        domain=[('move_type', 'in', ['out_invoice', 'out_refund']), ('state', '=', 'posted')],
        help='Search for the invoice by number, partner name, or IRN.',
    )
    move_name = fields.Char(related='move_id.name', string='Invoice Number', readonly=True)
    move_partner = fields.Char(related='move_id.partner_id.name', string='Customer', readonly=True)
    move_date = fields.Date(related='move_id.invoice_date', string='Invoice Date', readonly=True)
    move_amount = fields.Monetary(related='move_id.amount_total', string='Total Amount', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id', string='Currency', readonly=True)

    current_irn = fields.Char(related='move_id.x_einvoice_irn', string='Current IRN', readonly=True)
    # current_status = fields.Char(related='move_id.x_einvoice_status', string='Current Status', readonly=True)
    current_ack_date = fields.Datetime(related='move_id.x_einvoice_ack_date', string='Current Ack Date', readonly=True)
    current_doc_number = fields.Char(related='move_id.x_einvoice_document_number', string='Current Doc Number', readonly=True)

    entry_type = fields.Selection([
        ('invoice', 'Invoice (x_einvoice_irn)'),
        ('credit', 'Credit Note (x_einvoice_credit_irn)'),
        ('debit', 'Debit Note (x_einvoice_debit_irn)'),
        ('withholding', 'Withholding (x_withholding_invoice_irn)'),
    ], string='Entry Type', required=True, default='invoice',
       help='Select which IRN field to populate.')

    irn = fields.Char(
        string='IRN',
        help='Invoice Reference Number as shown on the MoR portal.',
    )
    status = fields.Char(
        string='Status',
        help='E-invoice status as returned by EIMS (e.g. REGISTERED).',
    )
    ack_date = fields.Datetime(
        string='Acknowledged Date/Time',
        help='The acknowledgement timestamp shown on the MoR portal.',
    )
    document_number = fields.Char(
        string='Document Number',
        help='The fiscal document number assigned by EIMS.',
    )
    signed_qr = fields.Binary(
        string='Signed QR Code',
        help='Optional: upload the QR code image from the MoR portal.',
    )
    signed_qr_filename = fields.Char()

    reason = fields.Text(
        string='Reason for Manual Entry',
        required=True,
        help='Briefly explain why this manual entry is needed (e.g. "Connection lost after EIMS accepted invoice 230").',
    )

    def action_apply(self):
        self.ensure_one()
        move = self.move_id
        if not move:
            raise UserError(_("Please select an invoice."))
        if not self.irn:
            raise UserError(_("IRN is required."))

        vals = {}
        qr_val = self.signed_qr or False

        if move.x_einvoice_irn:
            raise UserError(_("IRN number for this invoice already exists."))
        elif self.entry_type == 'invoice':
            vals['x_einvoice_irn'] = self.irn
            if self.status:
                vals['x_einvoice_status'] = self.status
            if self.ack_date:
                vals['x_einvoice_ack_date'] = self.ack_date
            if self.document_number:
                vals['x_einvoice_document_number'] = self.document_number
            if qr_val:
                vals['x_einvoice_signed_qr'] = qr_val

        elif self.entry_type == 'credit':
            vals['x_einvoice_credit_irn'] = self.irn
            if self.status:
                vals['x_einvoice_credit_status'] = self.status
            if self.ack_date:
                vals['x_einvoice_credit_ack_date'] = self.ack_date
            if self.document_number:
                vals['x_einvoice_credit_document_number'] = self.document_number
            if qr_val:
                vals['x_einvoice_credit_signed_qr'] = qr_val

        elif self.entry_type == 'debit':
            vals['x_einvoice_debit_irn'] = self.irn
            if self.status:
                vals['x_einvoice_debit_status'] = self.status
            if self.ack_date:
                vals['x_einvoice_debit_ack_date'] = self.ack_date
            if self.document_number:
                vals['x_einvoice_debit_document_number'] = self.document_number
            if qr_val:
                vals['x_einvoice_debit_signed_qr'] = qr_val

        elif self.entry_type == 'withholding':
            vals['x_withholding_invoice_irn'] = self.irn
            if qr_val:
                vals['x_withholding_qr'] = qr_val

        move.sudo().write(vals)

        move.message_post(
            body=_(
                "✏ Manual E-Invoice entry applied by %(user)s.<br/>"
                "<strong>Type:</strong> %(entry_type)s<br/>"
                "<strong>IRN:</strong> %(irn)s<br/>"
                "<strong>Status:</strong> %(status)s<br/>"
                "<strong>Ack Date:</strong> %(ack_date)s<br/>"
                "<strong>Document Number:</strong> %(doc_num)s<br/>"
                "<strong>Reason:</strong> %(reason)s"
            ) % {
                'user': self.env.user.name,
                'entry_type': self.entry_type,
                'irn': self.irn or '—',
                'status': self.status or '—',
                'ack_date': str(self.ack_date) if self.ack_date else '—',
                'doc_num': self.document_number or '—',
                'reason': self.reason,
            }
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Manual IRN Entry Applied'),
                'message': _(
                    'IRN %s has been saved on invoice %s.'
                ) % (self.irn, move.name),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'account.move',
                    'res_id': move.id,
                    'views': [[False, 'form']],
                },
            },
        }
