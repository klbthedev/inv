import json
import logging
import ssl
import pprint
import requests
from requests.adapters import HTTPAdapter

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
_AUTH_ENDPOINTS = frozenset({'/auth/login'})

class _TLS13Adapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        try:
            ctx = ssl.create_default_context()
            if hasattr(ssl, "TLSVersion"):
                ctx.minimum_version = ssl.TLSVersion.TLSv1_3
            pool_kwargs["ssl_context"] = ctx
        except Exception:
            pass
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


class EinvoiceApiBase(models.AbstractModel):
    _name = "einvoice.api.base"
    _description = "E-Invoice API Base Service"

    def _get_company_config(self, company, config=None):
        if config:
            return config
        configs = self.env["einvoice.config"].sudo().search([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ])
        if not configs:
            raise UserError(
                _("No active E-Invoice configuration found for company %s.") % company.name
            )
        return configs[0]

    # def _get_auth_headers(self, company, config=None):
    #     config = self._get_company_config(company, config=config)
    #     token_domain = [("active", "=", True)]
    #     if config:
    #         token_domain.append(("config_id", "=", config.id))
    #     else:
    #         token_domain.append(("company_id", "=", company.id))
    #     token = self.env["einvoice.token"].sudo().search(
    #         token_domain, order="expiry_datetime desc", limit=1,
    #     )
    #     if not token:
    #         token = self.env["einvoice.token"].sudo().search(
    #             [("company_id", "=", company.id), ("active", "=", True)],
    #             order="expiry_datetime desc", limit=1,
    #         )
    #     # if not token or token.is_expired():
    #     #     raise UserError(_("No valid E-Invoice token found. Authentication required."))
    #     if not token or token.is_expired():
    #         self.env["einvoice.auth.service"].sudo().authenticate(company)
    #         token = self.env["einvoice.token"].sudo().search(
    #             token_domain,
    #             order="expiry_datetime desc",
    #             limit=1,
    #         )
    #         if not token or token.is_expired():
    #             raise UserError(_("Unable to obtain a valid E-Invoice token."))

    #     return {
    #         "Content-Type": "application/json",
    #         "SYSTEM_NUMBER": config.system_number or "",
    #         "TIN": config.seller_tin or (company.vat or ""),
    #         "Authorization": f"Bearer {token.access_token}",
    #     }
    def _get_auth_headers(self, company, config=None):
        config = self._get_company_config(company, config=config)
        token_domain = [("active", "=", True)]
        if config:
            token_domain.append(("config_id", "=", config.id))
        else:
            token_domain.append(("company_id", "=", company.id))
        token = self.env["einvoice.token"].sudo().search(
            token_domain, order="expiry_datetime desc", limit=1,
        )
        if not token:
            token = self.env["einvoice.token"].sudo().search(
                [("company_id", "=", company.id), ("active", "=", True)],
                order="expiry_datetime desc", limit=1,
            )
        if not token or token.is_expired():
            self.env["einvoice.auth.service"].sudo().authenticate(company)
            token = self.env["einvoice.token"].sudo().search(
                token_domain, order="expiry_datetime desc", limit=1,
            )
            if not token or token.is_expired():
                raise UserError(_("Unable to obtain a valid E-Invoice token."))

        return {
            "Content-Type": "application/json",
            "SYSTEM_NUMBER": config.system_number or "",
            "TIN": config.seller_tin or (company.vat or ""),
            "Authorization": f"Bearer {token.get_access_token()}", 
        }

    def _validate_json_payload(self, payload):
        try:
            json.dumps(payload)
        except Exception as exc:
            raise UserError(_("Invalid JSON payload: %s") % exc)

    def _sign_payload(self, config, payload):
        s_payload = self.env['einvoice.signature.service'].sign_request(
            source_number=config.system_number,
            payload_dict=payload,
        )
        # _logger.info("Signed Payload: %s", pprint.pformat(s_payload))
        return self.env['einvoice.signature.service'].sign_request(
            source_number=config.system_number,
            payload_dict=payload,
        )

    def _request(self, company, method, endpoint, payload=None, config=None):
        config = self._get_company_config(company, config=config)
        base_url = config.get_base_url()
        url = f"{base_url}{endpoint}"
        headers = self._get_auth_headers(company, config=config)
        if endpoint in ("/v1/cancel", "/v1/bulkCancel"):
            headers["TIN"] = config.seller_tin or (company.vat or "")
        if endpoint == "/v1/bulkRegister":
            headers.update({
                "TIN": config.seller_tin or (company.vat or ""),
                "SYSTEM_NUMBER": config.system_number or "",
                "callback": config.einvoice_callback_url,
            })
        if endpoint in ("/v1/receipt/withholding", "/v1/receipt/sales"):
            headers.update({
                "TIN": config.seller_tin or (company.vat or ""),
                "SYSTEM_NUMBER": config.system_number or "",
            })

        if payload is not None:
            self._validate_json_payload(payload)

            if endpoint not in _AUTH_ENDPOINTS:
                body = self._sign_payload(config, payload)
                _logger.debug("Signed request envelope for endpoint=%s source_number=%s", endpoint, config.system_number,)
            else:
                body = payload
        else:
            body = None

        _logger.info("E-Invoice API Request → %s %s", method, endpoint)

        try:
            icp = self.env["ir.config_parameter"].sudo()
            enforce_tls13 = (
                str(icp.get_param("ethiopian_einvoice_hardening.enforce_tls13_outbound") or "")
                .strip().lower()
                in {"1", "true", "yes", "on"}
            )
            if enforce_tls13:
                session = requests.Session()
                session.mount("https://", _TLS13Adapter())
                response = session.request(
                    method=method, url=url, headers=headers, json=body, timeout=60,
                )
            else:
                response = requests.request(
                    method=method, url=url, headers=headers, json=body, timeout=60,
                )

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            _logger.warning("E-Invoice API connection error (offline). Queuing request for %s", endpoint)
            if (not self.env.context.get('skip_offline_queue') and endpoint in ('/v1/register', '/v1/bulkRegister')):
                move_ids = []
                if endpoint == '/v1/register' and payload:
                    doc_num = payload.get('DocumentDetails', {}).get('DocumentNumber')
                    move = self.env['account.move'].search([
                        ('x_einvoice_reserved_document_number', '=', str(doc_num)),
                    ], limit=1)
                    if not move and doc_num:
                        move = self.env['account.move'].search(
                            [('name', '=', doc_num)], limit=1
                        )
                    if move:
                        if move.x_einvoice_irn:
                            raise UserError(_(
                                "Invoice %s is already registered (IRN: %s). "
                                "No offline queue entry created."
                            ) % (move.name, move.x_einvoice_irn))
                        move_ids = [move.id]
                elif endpoint == '/v1/bulkRegister' and payload and isinstance(payload, list):
                    doc_nums = [
                        str(p.get('DocumentDetails', {}).get('DocumentNumber'))
                        for p in payload
                    ]
                    moves = self.env['account.move'].search([
                        ('x_einvoice_reserved_document_number', 'in', doc_nums),
                    ])
                    # move_ids = moves.ids

            raise UserError(_(
                "E-Invoice server is unreachable (offline or timeout). "
            )) from exc

        _logger.info("E-Invoice API Response ← %s %s", endpoint, response.status_code)
        return response
