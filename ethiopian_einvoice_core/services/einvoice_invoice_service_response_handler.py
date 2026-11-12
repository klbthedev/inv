import base64
import json
import logging
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

class EinvoiceInvoiceServiceInherit(models.AbstractModel):
    _inherit = 'einvoice.invoice.service'

    def _fiscal_log(self, move, event_type, *, endpoint=None, status_code=None, payload=None, response=None, error_message=None):
        try:
            self.env['einvoice.fiscal.log'].log_event(
                move,
                event_type,
                endpoint=endpoint,
                status_code=status_code,
                payload=payload,
                response=response,
                error_message=error_message,
            )
        except Exception:
            return False

    
    def _parse_mor_datetime(self, value):
        if not value:
            return False
        clean = value.replace("Z", "").split(".")[0].replace("T", " ")
        return fields.Datetime.from_string(clean)
    def _handle_response(self, move, response_json):
        status_code = response_json.get("statusCode") if isinstance(response_json, dict) else None
        _logger.info("E-Invoice response received statusCode=%s", status_code)
        move.einvoice_submission_count += 1
        if response_json.get("statusCode") != 200:
            status_code = response_json.get("statusCode")
            main_message = response_json.get("message", "Unknown E-Invoice error")
            body = response_json.get("body")
            detailed_errors = []
            if isinstance(body, list):
                for err in body:
                    if isinstance(err, dict):
                        if "errorMessage" in err:
                            portion = err.get("portion")
                            messages = err.get("errorMessage", [])
                            if isinstance(messages, list):
                                for m in messages:
                                    if portion:
                                        detailed_errors.append(f"[{portion}] {m}")
                                    else:
                                        detailed_errors.append(m)
                        else:
                            msg = err.get("message")
                            if msg:
                                detailed_errors.append(msg)
            elif isinstance(body, dict):
                msg = body.get("message")
                if msg:
                    detailed_errors.append(msg)
                else:
                    detailed_errors.append(str(body))
            elif isinstance(body, str):
                detailed_errors.append(body)
            else:
                detailed_errors.append(str(body))
            if detailed_errors:
                full_message = "%s (Code %s):\n\n%s" % (main_message,status_code,"\n".join(detailed_errors))
            else:
                full_message = "%s (Code %s)" % (main_message, status_code)
            move.message_post(body=_("E-Invoice registration failed: %s") % full_message)
            self._fiscal_log(move, 'einvoice_register_failed', endpoint='/v1/register', status_code=status_code, response=response_json, error_message=full_message)
            raise UserError(full_message)
        response = response_json.get("body", {})
        move.write({
            "x_einvoice_irn": response.get("irn"),
            "x_einvoice_status": response.get("status"),
            "x_einvoice_document_number": response.get("documentNumber"),
            "x_einvoice_signed_invoice": response.get("signedInvoice"),
            "x_einvoice_signed_qr": response.get("signedQR"),
            "x_einvoice_error_message": response.get("errorMessage"),
            "x_einvoice_response_raw": response_json,
            "x_einvoice_ack_date": self._parse_mor_datetime(response.get("ackDate")),
        })
        move.message_post(body=_(
            "E-Invoice registered successfully. IRN: %s, Document#: %s"
        ) % (response.get("irn", ""), response.get("documentNumber", "")))
        self._fiscal_log(move, 'einvoice_register_success', endpoint='/v1/register', status_code=200, response=response_json)
        try:
            attachment, url = self._generate_registered_einvoice_pdf_and_attachment(move)
            sent = self._send_link_sms(move, "E-Invoice", url)
            if not sent:
                self._send_invoice_registration_sms(move)
        except Exception:
            self._send_invoice_registration_sms(move)
        self._send_invoice_registration_email(move)
        # if response.get("signedQR"):
        #     self.env["einvoice.document"].create({
        #         "name": f"EInvoice_QR_{move.name}.png",
        #         "datas": response["signedQR"],
        #         "res_model": "account.move",
        #         "res_id": move.id,
        #         "mimetype": "image/png",
        #     })
        # move._check_lock_date()

    def _handle_credit_debit_response(self, move, response_json):
        status_code = response_json.get("statusCode") if isinstance(response_json, dict) else None
        _logger.info("E-Invoice credit/debit response received statusCode=%s", status_code)
        move.einvoice_submission_count += 1
        if response_json.get("statusCode") != 200:
            status_code = response_json.get("statusCode")
            main_message = response_json.get("message", "Unknown E-Invoice error")
            body = response_json.get("body")
            detailed_errors = []
            if isinstance(body, list):
                for err in body:
                    if isinstance(err, dict):
                        if "errorMessage" in err:
                            portion = err.get("portion")
                            messages = err.get("errorMessage", [])
                            if isinstance(messages, list):
                                for m in messages:
                                    detailed_errors.append(f"[{portion}] {m}" if portion else m)
                            else:
                                detailed_errors.append(str(messages))
                        else:
                            msg = err.get("message")
                            if msg:
                                detailed_errors.append(msg)
                    else:
                        detailed_errors.append(str(err))
            elif isinstance(body, dict):
                msg = body.get("message")
                detailed_errors.append(msg if msg else str(body))
            elif isinstance(body, str):
                detailed_errors.append(body)
            else:
                detailed_errors.append(str(body))
            full_message = "%s (Code %s):\n\n%s" % (
                main_message,
                status_code,
                "\n".join(detailed_errors),
            ) if detailed_errors else "%s (Code %s)" % (main_message, status_code)
            move.message_post(body=_("E-Invoice Credit/Debit registration failed: %s") % full_message)
            self._fiscal_log(move, 'einvoice_credit_debit_failed', endpoint='/v1/register', status_code=status_code, response=response_json, error_message=full_message)
            raise UserError(full_message)
        response = response_json.get("body", {})
        vals = {
            "x_einvoice_cn_irn": response.get("irn"),
            "x_einvoice_cn_status": response.get("status"),
            "x_einvoice_cn_document_number": response.get("documentNumber"),
            "x_einvoice_cn_signed_invoice": response.get("signedInvoice"),
            "x_einvoice_cn_signed_qr": response.get("signedQR"),
            "x_einvoice_cn_error_message": response.get("errorMessage"),
            "x_einvoice_cn_response_raw": response_json,
            "x_einvoice_cn_ack_date": self._parse_mor_datetime(response.get("ackDate")),
        }
        if move.move_type == "out_refund":
            vals.update({
                "x_einvoice_credit_irn": response.get("irn"),
                "x_einvoice_credit_status": response.get("status"),
                "x_einvoice_credit_document_number": response.get("documentNumber"),
                "x_einvoice_credit_signed_invoice": response.get("signedInvoice"),
                "x_einvoice_credit_signed_qr": response.get("signedQR"),
                "x_einvoice_credit_error_message": response.get("errorMessage"),
                "x_einvoice_credit_response_raw": response_json,
                "x_einvoice_credit_ack_date": self._parse_mor_datetime(response.get("ackDate")),
            })
        # elif move.move_type == "out_debit":
        else:
            vals.update({
                "x_einvoice_debit_irn": response.get("irn"),
                "x_einvoice_debit_status": response.get("status"),
                "x_einvoice_debit_document_number": response.get("documentNumber"),
                "x_einvoice_debit_signed_invoice": response.get("signedInvoice"),
                "x_einvoice_debit_signed_qr": response.get("signedQR"),
                "x_einvoice_debit_error_message": response.get("errorMessage"),
                "x_einvoice_debit_response_raw": response_json,
                "x_einvoice_debit_ack_date": self._parse_mor_datetime(response.get("ackDate")),
            })
        move.write(vals)
        move.message_post(body=_(
            "E-Invoice Credit/Debit registered successfully. IRN: %s, Document#: %s"
        ) % (response.get("irn", ""), response.get("documentNumber", "")))
        self._fiscal_log(move, 'einvoice_credit_debit_success', endpoint='/v1/register', status_code=200, response=response_json)
        self._send_credit_note_sms(move)
        if move.move_type != "out_refund":
            self._send_debit_note_sms(move)
        self._send_credit_note_email(move)

    def _parse_cancel_date(self, date_str):
        if not date_str:
            return False
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S GMT %Y")
        return dt 
    def _handle_cancel_response(self, move, response_json):
        status_code = response_json.get("statusCode") if isinstance(response_json, dict) else None
        _logger.info("E-Invoice cancel response received statusCode=%s", status_code)
        status = response_json.get("statusCode")
        if status != 200:
            message = response_json.get("message") or _("Cancellation failed")
            move.message_post(body=_("E-Invoice cancellation failed: %s") % message)
            self._fiscal_log(move, 'einvoice_cancel_failed', endpoint='/v1/cancel', status_code=status, response=response_json, error_message=message)
            raise UserError(message)
        body = response_json.get("body", {})
        self._fiscal_log(move, 'einvoice_cancel_success', endpoint='/v1/cancel', status_code=200, response=response_json)
        cancel_date = body.get("cancellationDate")
        move.write({
            "x_einvoice_cancel_status": "cancelled",
            "x_einvoice_cancel_date": self._parse_cancel_date(cancel_date),
            "x_einvoice_cancel_response": response_json,
        })
        move.message_post(body=_("E-Invoice cancelled successfully on %s.") % (cancel_date or 'N/A'))
        self._send_cancellation_sms(move)
        self._send_cancellation_email(move)
    def _handle_verify_response(self, move, response_json):
        status_code = response_json.get("statusCode") if isinstance(response_json, dict) else None
        _logger.info("E-Invoice verification response received statusCode=%s", status_code)
        status = response_json.get("statusCode")
        body = response_json.get("body") or {}
        if "statusCode" in response_json:
            status_code = response_json["statusCode"]
            body = response_json.get("body") or {}
            if status_code == 200:
                move.x_einvoice_verified_status = "active"
                move.x_einvoice_verified_details = body
            elif status_code == 400:
                if isinstance(body, dict) and body.get("message") == "Invoice is not registered":
                    move.x_einvoice_verified_status = "not_registered"
                    move.x_einvoice_verified_details = body
                else:
                    move.x_einvoice_verified_status = "error"
                    move.x_einvoice_verified_details = response_json
                    raise UserError(_("Verification failed: %s") % response_json.get("message"))
            else:
                move.x_einvoice_verified_status = "error"
                move.x_einvoice_verified_details = response_json
                raise UserError(_("Unexpected verification response: %s") % response_json.get("message"))
        elif "status" in response_json and "message" in response_json:
            msg = response_json["message"]
            if msg.lower() == "invoice is cancelled":
                move.x_einvoice_verified_status = "cancelled"
                move.x_einvoice_verified_details = response_json
            elif msg.lower() == "invoice is not registered":
                move.x_einvoice_verified_status = "not_registered"
                move.x_einvoice_verified_details = response_json
            else:
                move.x_einvoice_verified_status = "error"
                move.x_einvoice_verified_details = response_json
                raise UserError(_("Verification failed: %s") % msg)
        else:
            move.x_einvoice_verified_status = "error"
            move.x_einvoice_verified_details = response_json
            raise UserError(_("Unexpected verification response format"))
    def _handle_withholding_response(self, move, response_json, payload):
        status_code = response_json.get("statusCode") if isinstance(response_json, dict) else None
        _logger.info("Withholding response received statusCode=%s", status_code)
        status_code = response_json.get("statusCode")
        main_message = response_json.get("message")
        body = response_json.get("body", {}) or {}
        def _collect_messages():
            messages = []
            if status_code:
                messages.append(f"Status Code: {status_code}")
            if main_message:
                messages.append(f"Message: {main_message}")
            if body.get("status"):
                messages.append(f"Body Status: {body.get('status')}")
            if body.get("unknownIrn"):
                messages.append("Unknown IRN: %s" % ", ".join(body.get("unknownIrn")))
            for item in body.get("dataMissMuch", []):
                tag = item.get("tag", "")
                for msg in item.get("errorMessage", []):
                    messages.append(f"{tag}: {msg}")
            for rule in body.get("ruleErrorDto", []):
                msgs = rule.get("errorMessage", [])
                if isinstance(msgs, list):
                    messages.extend(msgs)
                elif msgs:
                    messages.append(msgs)
            return messages
        if status_code != 200:
            error_messages = _collect_messages()
            full_error = "\n".join(error_messages) or _("Unknown withholding error")
            move.message_post(body=_("Withholding receipt registration failed:<br/>%s") % full_error)
            raise UserError(full_error)
        if body.get("status") == "F":
            error_messages = _collect_messages()
            full_error = "\n".join(error_messages) or _("Withholding rejected by server")
            move.message_post(body=_("Withholding receipt rejected:<br/>%s") % full_error)
            raise UserError(full_error)
        values = {
            "x_withholding_external_id": body.get("id"),
            "x_withholding_status": body.get("status"),
            "x_withholding_rrn": body.get("rrn"),
            "x_withholding_invoice_irn": ((payload or {}).get("InvoiceDetail") or {}).get("InvoiceIRN"),
            "x_withholding_qr": body.get("qr"),}
        _logger.info("Processed withholding status=%s", values.get("x_withholding_status"))
        move.write(values)
        move.message_post(body=_("Withholding receipt registered successfully. RRN: %s") %(body.get("rrn", "")))
        # try:
        #     attachment, url = self._generate_receipt_pdf_and_attachment(move, "Withholding Receipt")
        #     self._send_receipt_sms(move, "Withholding Receipt", url)
        #     self._send_receipt_email(move,attachment,"ethiopian_einvoice_core.email_template_sales_receipt",)
        # except Exception as e:_logger.exception("Withholding PDF/SMS/Email failed for move %s: %s",move.name,str(e),)
        try:
            attachment, download_url, unused = self._generate_receipt_pdf_and_attachment(
                move, "Withholding Receipt")
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_download_url = (base_url + download_url) if download_url else ''
            self._send_receipt_sms(move, "Withholding Receipt", download_url)
            self._send_receipt_email(
                move, attachment,
                "ethiopian_einvoice_core.email_template_withholding_receipt",
                download_url=download_url,
            )
        except Exception as e:
            _logger.exception("Withholding PDF/SMS/Email failed for move %s: %s", move.name, str(e))
        
    def _safe_json_response(self, response):
        try:
            return response.json()
        except ValueError:
            _logger.error("Failed to decode JSON response: %s", response.text)
            raise UserError(_("Invalid response from E-Invoice API"))   
    
    def _handle_receipt_response_from_payment(self, move, payment, response_json, payload, receipt_type):
        status = response_json.get("statusCode") if isinstance(response_json, dict) else None
        body = response_json.get("body") if isinstance(response_json, dict) else response_json
        if status == 200 and isinstance(body, dict):
            receipt_vals = {
                "x_einvoice_receipt_status": "sent",
                "x_einvoice_receipt_id": body.get("id"),
                "x_einvoice_receipt_status_code": body.get("status"),
                "x_einvoice_receipt_rrn": body.get("rrn"),
                "x_einvoice_receipt_qr": body.get("qr"),
                "x_einvoice_receipt_response_raw": response_json,
            }
            payment.write(receipt_vals)
            move.write(receipt_vals)
            # move.x_einvoice_sales_paid_total = (move.x_einvoice_sales_paid_total or 0.0) + float(payload["Invoices"][0]["InvoicePaidAmount"])
            move.x_einvoice_sales_paid_total = float((move.x_einvoice_sales_paid_total or 0.0) + float(payload["Invoices"][0]["InvoicePaidAmount"]))
            move.message_post(body=_("%s registered successfully. RRN: %s") % (receipt_type, body.get("rrn", "")))
            try:
                attachment, download_url, unused = self._generate_receipt_pdf_and_attachment(
                    move, "Sales Receipt")
                self._send_receipt_sms(move, "Sales Receipt", download_url)
                self._send_receipt_email(
                    move, attachment,
                    "ethiopian_einvoice_core.email_template_sales_receipt",
                    download_url=download_url,
                )
            except Exception as e:
                _logger.exception("Sales Receipt PDF/SMS/Email failed for move %s: %s", move.name, str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Sales receipt sent successfully.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

        raise UserError(_("%s API Error: %s") % (receipt_type, body))