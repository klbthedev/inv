import base64
import json
import logging
import pprint
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

TIN_REGEX = r"^\d{10}$" 
DATE_REGEX = r"^\d{2}-\d{2}-\d{4}T\d{2}:\d{2}:\d{2}$" 
EMAIL_REGEX = r"^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$"
PHONE_REGEX = r"^\+?[0-9]{6,20}$"

class EinvoiceInvoiceService(models.AbstractModel):
    _inherit = 'einvoice.invoice.service'


         
    @api.model
    def send_sms(self, phone: str, message: str) -> bool:
        _logger.info("[SMS] Sending SMS to %s", phone)
        try:
            geezsms_token = self.env['ir.config_parameter'].sudo().get_param('geezsms.token')
            geezsms_shortcode_id = self.env['ir.config_parameter'].sudo().get_param('geezsms.shortcode_id')
            api_url = self.env['ir.config_parameter'].sudo().get_param('geezsms.sms_endpoint')
            if not geezsms_token:
                _logger.error("GeezSMS token is not configured in system parameters")
                return False
            normalized_phone = self._normalize_phone_number(phone)
            payload = {
                'token': geezsms_token,
                'phone': normalized_phone,
                'msg': message
            }
            if geezsms_shortcode_id:
                payload['shortcode_id'] = geezsms_shortcode_id
            _logger.info("[SMS] Sending SMS request")
            response = requests.post(api_url, json=payload, timeout=10)
            if response.status_code == 200:
                _logger.info(f"[SMS] Successfully sent SMS to {normalized_phone}")
                return True
            else:
                _logger.error(
                    f"[SMS] Failed to send SMS to {normalized_phone}. "
                    f"Status: {response.status_code}, Response: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            _logger.error(f"[SMS] Error sending SMS to {phone}: {str(e)}")
            return False
        except Exception as e:
            _logger.error(f"[SMS] Unexpected error sending SMS to {phone}: {str(e)}")
            return False
    def _normalize_phone_number(self, phone: str) -> str:
        """Normalize phone number to start with 2519"""
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("0"):
            phone = "251" + phone[1:]
        elif phone.startswith("+251"):
            phone = "251" + phone[4:]
        elif not phone.startswith("2519"):
            phone = "2519" + phone[-8:]
        return phone
    def _generate_report_pdf_and_attachment(self, move, *, report_ref, filename):
        pdf_bytes, _ = self.env['ir.actions.report']._render_qweb_pdf(report_ref, [move.id])
        attachment = self.env['einvoice.document'].create({
            'name': filename,
            'datas': base64.b64encode(pdf_bytes),
            'res_model': 'account.move',
            'res_id': move.id,
            'mimetype': 'application/pdf',
        })
        download_url = f"/einvoice/receipt/{attachment.id}/pdf"
        portal_url = False
        if move.x_einvoice_irn:
            portal_url = (f"https://portal.mor.gov.et/public/invoice?irn={move.x_einvoice_irn}")
        return attachment, download_url, portal_url

    def _generate_receipt_pdf_and_attachment(self, move, receipt_type="Sales Receipt"):
        if receipt_type == "Withholding Receipt":
            report_ref = "ethiopian_einvoice_core.action_report_withholding_receipt"
        else:
            report_ref = "ethiopian_einvoice_core.action_report_sales_receipt"
        return self._generate_report_pdf_and_attachment(
            move,
            report_ref=report_ref,
            filename=f"{receipt_type}_{move.name}.pdf",
        )

    def _generate_registered_einvoice_pdf_and_attachment(self, move):
        return self._generate_report_pdf_and_attachment(
            move,report_ref="ethiopian_einvoice_core.action_report_registered_einvoice",filename=f"E-Invoice_{move.name}.pdf",)

    def _send_link_sms(self, move, label, url):
        try:
            partner = move.partner_id
            phone = (partner and partner.phone) or getattr(move, "buyer_phone", None)
            if not phone:
                return False
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            if not base_url:
                return False
            message = _("Dear %s, your %s is ready. Download: %s%s") % (
                (partner.name if partner else "customer"),label,base_url,url,)
            sent = self.send_sms(phone, message)
            if sent:
                move.message_post(body=_("📩 SMS sent to %s<br/>Link: %s%s") % (phone, base_url, url))
            else:
                move.message_post(body=_("⚠ SMS sending failed for %s") % phone)
            return sent
        except Exception as e:
            move.message_post(body=_("❌ SMS error: %s") % str(e))
            return False
    def _send_receipt_sms(self, move, receipt_type, url):
        return self._send_link_sms(move, receipt_type, url)

    def _send_withholding_email(self, move):
        attachment, download_url, _ = self._generate_receipt_pdf_and_attachment(
            move, receipt_type="Withholding Receipt"
        )
        return self._send_receipt_email(
            move, attachment,
            "ethiopian_einvoice_core.email_template_withholding_receipt",
            download_url=download_url,
        )

    def _send_receipt_email(self, move, attachment, template_xmlid, download_url=None):
        try:
            partner = move.partner_id
            if not partner or not partner.email:
                return False
            template = self.env.ref(template_xmlid, raise_if_not_found=False)
            if not template:
                return False
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_download_url = (base_url + download_url) if download_url else ''
            email_values = {'attachment_ids': [(4, attachment.id)]}
            template.with_context(download_url=full_download_url).send_mail(move.id, email_values=email_values, force_send=True)
            move.message_post(body=_("📧 Receipt email sent to %s") % partner.email,attachment_ids=[attachment.id])
            return True
        except Exception as e:
            move.message_post(body=_("❌ Email sending failed: %s") % str(e))
            return False

    def _send_notification_email(self, move, template_xmlid, download_url=None):
        try:
            partner = move.partner_id
            if not partner or not partner.email:
                return False
            template = self.env.ref(template_xmlid, raise_if_not_found=False)
            if not template:
                return False
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_download_url = (base_url + download_url) if download_url else ''
            template.with_context(download_url=full_download_url).send_mail(move.id, force_send=True)
            move.message_post(body=_("📧 Notification email sent to %s") % partner.email)
            return True
        except Exception as e:
            move.message_post(body=_("❌ Email sending failed: %s") % str(e))
            return False

    def _send_invoice_registration_sms(self, move):
        phone = (move.partner_id and move.partner_id.phone) or getattr(move, "buyer_phone", None)
        if not phone:
            return False
        ack = move.x_einvoice_ack_date
        ack_str = ack.strftime("%Y-%m-%d %H:%M") if ack else "—"
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        attachment, download_url, portal_url = self._generate_registered_einvoice_pdf_and_attachment(move)
        full_download_url = (base_url + download_url) if download_url else ''
        portal_url = f"https://portal.mor.gov.et/public/invoice?irn={move.x_einvoice_irn}"
        msg = _(
            "Dear customer, your invoice %s has been registered.\n"
            "IRN: %s\nStatus: %s\nAck: %s\nPortal: %s\nDownload: %s"
        ) % (
            move.name,
            move.x_einvoice_irn or "—",
            move.x_einvoice_status or "—",
            ack_str,
            portal_url,
            full_download_url,
        )
        sent = self.send_sms(phone, msg)
        if sent:
            move.message_post(body=_("📩 Invoice registration SMS sent to %s") % phone)
        return sent

    def _send_invoice_registration_email(self, move):
        attachment, download_url, unused = self._generate_registered_einvoice_pdf_and_attachment(move)
        return self._send_notification_email(
            move,
            "ethiopian_einvoice_core.email_template_invoice_registration",
            download_url=download_url,
        )

    def _send_cancellation_sms(self, move):
        phone = (move.partner_id and move.partner_id.phone) or getattr(move, "buyer_phone", None)
        if not phone:
            return False
        dt = move.x_einvoice_cancel_date
        dt_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "—"
        msg = _("Dear customer, invoice %s has been cancelled.\nCancel status: %s\nDate: %s") % (move.name, move.x_einvoice_cancel_status or "—", dt_str)
        sent = self.send_sms(phone, msg)
        if sent:
            move.message_post(body=_("📩 Cancellation SMS sent to %s") % phone)
        return sent

    def _send_cancellation_email(self, move):
        return self._send_notification_email(move, "ethiopian_einvoice_core.email_template_cancellation")

    def _send_credit_note_sms(self, move):
        phone = (move.partner_id and move.partner_id.phone) or getattr(move, "buyer_phone", None)
        if not phone:
            return False
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        attachment, download_url, unused = self._generate_report_pdf_and_attachment(
            move,
            # report_ref="ethiopian_einvoice_core.action_report_registered_einvoice",
            report_ref="ethiopian_einvoice_core.action_report_credit_note_einvoice",
            filename=f"Credit_Note_{move.name}.pdf",
        )
        full_download_url = (base_url + download_url) if download_url else ''
        portal_url = f"https://portal.mor.gov.et/public/invoice?irn={move.x_einvoice_credit_irn}"
        msg = _("Dear customer, your credit note %s has been registered.\n"
                "IRN: %s\n"
                "Status: %s\n"
                "Portal: %s\n"
                "Download: %s") % (
            move.name,
            move.x_einvoice_credit_irn or "—",
            move.x_einvoice_credit_status or "—",
            portal_url or "",
            full_download_url or "",
        )
        sent = self.send_sms(phone, msg)
        if sent:
            move.message_post(body=_("📩 Credit note SMS sent to %s") % phone)
        return sent
    
    def _send_debit_note_sms(self, move):
        phone = (move.partner_id and move.partner_id.phone) or getattr(move, "buyer_phone", None)
        if not phone:
            return False
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        attachment, download_url, unused = self._generate_report_pdf_and_attachment(
            move,
            # report_ref="ethiopian_einvoice_core.action_report_registered_einvoice",
            report_ref="ethiopian_einvoice_core.action_report_debit_note_einvoice",
            filename=f"Debit_Note_{move.name}.pdf",
        )
        full_download_url = (base_url + download_url) if download_url else ''
        portal_url = f"https://portal.mor.gov.et/public/invoice?irn={move.x_einvoice_debit_irn}"
        msg = _("Dear customer, your debit note %s has been registered.\n""IRN: %s\nStatus: %s\nPortal: %s\nDownload: %s") % (
            move.name,
            move.x_einvoice_debit_irn or "—",
            move.x_einvoice_debit_status or "—",
            portal_url or "",
            full_download_url or "",
        )
        sent = self.send_sms(phone, msg)
        if sent:
            move.message_post(body=_("📩 Debit note SMS sent to %s") % phone)
        return sent

    def _send_credit_note_email(self, move):
        attachment, download_url, unused = self._generate_report_pdf_and_attachment(
            move,
            # report_ref="ethiopian_einvoice_core.action_report_registered_einvoice",
            report_ref="ethiopian_einvoice_core.action_report_credit_note_einvoice",
            filename=f"Credit_Note_{move.name}.pdf",
        )
        return self._send_notification_email(
            move,
            "ethiopian_einvoice_core.email_template_credit_note",
            download_url=download_url,
        )

    def _send_debit_note_email(self, move):
        attachment, download_url, unused = self._generate_report_pdf_and_attachment(
            move,
            # report_ref="ethiopian_einvoice_core.action_report_registered_einvoice",
            report_ref="ethiopian_einvoice_core.action_report_debit_note_einvoice",
            filename=f"Debit_Note_{move.name}.pdf",
        )
        return self._send_notification_email(
            move,
            "ethiopian_einvoice_core.email_template_debit_note",
            download_url=download_url,
        )