import json
import logging
import hashlib
import ipaddress
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

class EinvoiceWebhookController(http.Controller):
    # @http.route("/einvoice/webhook/mor", type="json", auth="public", methods=["POST"], csrf=False)
    # def mor_webhook(self, **kwargs):
    #     payload = request.jsonrequest
    #     _logger.info("Webhook Response %s", payload)

    #     # allow_ips = request.env["ir.config_parameter"].sudo().get_param(
    #     #     "ethiopian_einvoice_hardening.mor_webhook_allowed_ips") or ""
    #     # allow_ips = allow_ips.strip()
    #     # if allow_ips:
    #     #     xff = (request.httprequest.headers.get("X-Forwarded-For") or "").strip()
    #     #     client_ip = xff.split(",")[0].strip() if xff else (request.httprequest.remote_addr or "")
    #     #     try:
    #     #         ip_obj = ipaddress.ip_address(client_ip)
    #     #         allowed = False
    #     #         for token in allow_ips.split(","):
    #     #             token = token.strip()
    #     #             if not token:
    #     #                 continue
    #     #             if ip_obj in ipaddress.ip_network(token, strict=False):
    #     #                 allowed = True
    #     #                 break
    #     #         if not allowed:
    #     #             raise AccessError("Forbidden: webhook caller IP is not allowed.")
    #     #     except Exception:
    #     #         raise AccessError("Forbidden: webhook caller IP validation failed.")
    #     if not isinstance(payload, list):
    #         return {"status": "ignored"}
    #     conversion_id = None
    #     for item in payload:
    #         if "conversionId" in item:
    #             conversion_id = item["conversionId"]
    #             continue
    #         doc_number = item.get("documentNumber") or item.get("docNo")
    #         if not doc_number:
    #             _logger.warning("MoR webhook item omitted: no document identification found. Payload: %s", item)
    #             continue
    #         irn = item.get("irn")
    #         status = item.get("status")
    #         move = request.env["account.move"].sudo().search(
    #             ["|", ("name", "=", doc_number), ("ref", "=", doc_number)],
    #             limit=1,
    #         )
    #         if not move:
    #             _logger.warning("MoR webhook skipped: Odoo account.move not found for tracking reference '%s'", doc_number)
    #             continue

    #         existing_irn = move.x_einvoice_irn
    #         payload_hash = hashlib.sha256(
    #             json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    #         ).hexdigest()

    #         if existing_irn:
    #             if irn and existing_irn == irn:
    #                 continue
    #             try:
    #                 if "einvoice.fiscal.log" in request.env.registry.models:
    #                     request.env["einvoice.fiscal.log"].log_event(
    #                         move,
    #                         "webhook_mor_callback_conflict",
    #                         endpoint="/einvoice/webhook/mor",
    #                         status_code=409,
    #                         payload=item,
    #                         response={"action": "ignored_conflicting_irn"},
    #                         error_message="Conflicting IRN received in webhook callback.",
    #                         fingerprint=payload_hash,
    #                     )
    #             except Exception:
    #                 pass
    #             continue
    #         calculated_status = "success" if status == "A" else "failed"
    #         move.write(
    #             {
    #                 "x_einvoice_status": calculated_status,
    #                 "x_einvoice_irn": irn,
    #                 "x_einvoice_signed_qr": item.get("signedQR"),
    #                 "x_einvoice_signed_invoice": item.get("signedInvoice"),
    #                 "x_einvoice_ack_date": item.get("ackDate"),
    #                 "x_einvoice_response_raw": json.dumps(item),
    #             }
    #         )

    #         try:
    #             if "einvoice.fiscal.log" in request.env.registry.models:
    #                 request.env["einvoice.fiscal.log"].log_event(
    #                     move,
    #                     "webhook_mor_callback",
    #                     endpoint="/einvoice/webhook/mor",
    #                     status_code=200,
    #                     payload=item,
    #                     response={"action": "invoice_updated"},
    #                     error_message=None if calculated_status == "success" else "Validation rules rejected by MoR.",
    #                     fingerprint=payload_hash,
    #                 )
    #         except Exception:
    #             pass
    #     if conversion_id:
    #         _logger.info("MoR callback processing sequence completed for conversionId=%s", conversion_id)
    #     return {"status": "ok"}



    @http.route("/einvoice/webhook/mor",type="json",auth="public",methods=["POST"],csrf=False)
    def einvoice_callback(self, **kwargs):
        data = request.jsonrequest
        _logger.info("Webhook Response %s", data)

        _logger.info("E-Invoice Callback Received: %s", data)
        if not isinstance(data, list):
            return {"result": "IGNORED"}
        conversion_id = None
        for item in data:
            if "conversionId" in item:
                conversion_id = item["conversionId"]
                continue
            irn = item.get("irn")
            doc_number = item.get("documentNumber")
            conversion_id = item.get("conversionId")
            # move = request.env['account.move'].sudo().search([
            #     ('x_einvoice_document_number', '=', doc_number)
            # ], limit=1)
            move = request.env['account.move'].sudo().search([
                ('x_einvoice_bulk_conversation_id', '=', conversion_id)
            ], limit=1)
            if not move:
                _logger.warning("No move found for document %s", doc_number)
                continue
            qr_base64 = item.get("signedQR")
            # qr_binary = base64.b64decode(qr_base64) if qr_base64 else False
            move.write({
                "x_einvoice_irn": irn,
                "x_einvoice_status": item.get("status"),
                "x_einvoice_ack_date": item.get("ackDate"),
                "x_einvoice_signed_invoice": item.get("signedInvoice"),
                "x_einvoice_signed_qr": qr_base64,
                "x_einvoice_response_raw": item,
                # "x_einvoice_error_message": False,
            })
        if conversion_id:
            _logger.info("Bulk Conversion ID: %s", conversion_id)
        return {"result": "OK"}

