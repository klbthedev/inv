import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    x_einvoice_receipt_status = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('error', 'Error'),
        ('pending', 'Pending'),
    ], string="E-Invoice Receipt Status", default='draft')
    x_einvoice_receipt_id = fields.Char(string="E-Invoice Receipt ID")
    x_einvoice_receipt_status_code = fields.Char(string="E-Invoice Receipt Status Code")
    x_einvoice_receipt_rrn = fields.Char(string="E-Invoice Receipt RRN")
    x_einvoice_receipt_qr = fields.Binary(string="E-Invoice Receipt QR Code")
    x_einvoice_receipt_response_raw = fields.Json(string="E-Invoice Receipt Raw Response")
    x_einvoice_sales_paid_total = fields.Monetary(
        string="E-Invoice Sales Paid Total",currency_field="currency_id",copy=False,
        help="Running total of amounts already sent to EIMS via sales receipts for this invoice. Used to compute incremental partial receipts.",)

    x_payment_coverage = fields.Selection([
        ('PARTIAL', "Partial Payment"),
        ('FULL', "Full Payment")
    ], string='Payment Coverage', default = 'FULL')

    receipt_response = fields.Text(string="Receipt API Response", readonly=True)

    mode_of_payment_receipt = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        ('CREDIT', 'CREDIT'),
        ('CHEQUE', 'Cheque'),
        ('CPO', 'CPO'),
        ('BANK', 'Bank Transfer'),
        ('SWIFT', 'SWIFT'),
        ('WIRE', 'Wire Transfer'),
        ('LC', 'Letter of Credit'),
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

    x_clicked_by_id = fields.Many2one('res.users',string='Clicked By',readonly=True)

    x_einvoice_irn = fields.Char(
        string="Linked Invoice IRN",
        compute="_compute_payment_invoice_irn",
        store=False,
    )
    # mode_of_payment = fields.Char(
    #     string="Mode of Payment (display)",
    #     compute="_compute_mode_of_payment_display",
    #     store=False,
    # )

    @api.depends("reconciled_invoice_ids")
    def _compute_payment_invoice_irn(self):
        for rec in self:
            inv = rec.reconciled_invoice_ids[:1]
            rec.x_einvoice_irn = inv.x_einvoice_irn if inv else False

    # @api.depends("mode_of_payment_receipt")
    # def _compute_mode_of_payment_display(self):
    #     for rec in self:
    #         rec.mode_of_payment = rec.mode_of_payment_receipt or "CASH"



    def action_sales_receipt(self):
        self.ensure_one()
        self.write({'x_clicked_by_id': self.env.user.id,})

        invoice = self.reconciled_invoice_ids[:1]
        if not invoice:
            raise UserError(_("No invoice found for this payment."))
        service = self.env['einvoice.invoice.service']
        return service.send_receipt_from_payment(self, invoice)
    
    # def action_sales_receipt(self):
    #     self.ensure_one()

    #     return {
    #         'name': _('Send Receipt'),
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'einvoice.receipt.wizard',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'context': {
    #             'default_move_id': self.id,
    #         },
    #     }
    
    def action_sms_sales_receipt(self):
        self.ensure_one()
        self._check_sales_receipt_registered()
        service = self.env['einvoice.invoice.service']
        attachment, download_url = service._generate_receipt_pdf_and_attachment(self, "Sales Receipt")
        # Send SMS
        phone = self.partner_id.phone or self.buyer_phone
        if phone:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_url = base_url + download_url if download_url else ''
            message = "Your Sales Receipt for %s is ready. Download: %s" % (self.name, full_url)
            service.send_sms(phone, message)
        else:
            _logger.warning("No phone number for partner %s, skipping SMS", self.partner_id.name)
        # Also return the PDF report action
        # return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt").report_action(self)
        return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt_payment").report_action(self)
    
    def action_send_sales_receipt_email(self):
        self.ensure_one()
        self._check_sales_receipt_registered()
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        service = self.env['einvoice.invoice.service']
        attachment, _url = service._generate_receipt_pdf_and_attachment(self, "Sales Receipt")
        service._send_receipt_email(
            self,
            attachment,
            "ethiopian_einvoice_core.email_template_sales_receipt")
        return True
