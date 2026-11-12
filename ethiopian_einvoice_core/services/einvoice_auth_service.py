import logging
import requests
import ssl
from datetime import timedelta
from requests.adapters import HTTPAdapter

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

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


class EinvoiceAuthService(models.AbstractModel):
    _name = 'einvoice.auth.service'
    _description = 'E-Invoice Authentication Service'

    def authenticate(self, company, config=None):
        if config:
            config = config.sudo()
        else:
            config = self.env['einvoice.config'].sudo().search([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ], limit=1)
        if not config:
            raise UserError(
                _("No active E-Invoice configuration found for company %s.") % company.name
            )

        # Read credentials via secure accessors, not DB fields
        raw_payload = {
            "clientId": config.get_client_id().strip(),
            "clientSecret": config.get_client_secret().strip(),
            "apikey": config.get_api_key().strip(),
            "tin": config.seller_tin.strip(),
        }

        signed_envelope = self.env['einvoice.signature.service'].sign_request(
            source_number=config.system_number,
            payload_dict=raw_payload,
        )

        url = f"{config.get_base_url()}/auth/login"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        _logger.info("E-Invoice auth %s", url)
        _logger.info("E-Invoice auth %s", headers)
        _logger.info("E-Invoice auth %s", signed_envelope)


        icp = self.env["ir.config_parameter"].sudo()
        enforce_tls13 = (
            str(icp.get_param("ethiopian_einvoice_hardening.enforce_tls13_outbound") or "")
            .strip().lower() in {"1", "true", "yes", "on"}
        )

        try:
            if enforce_tls13:
                session = requests.Session()
                session.mount("https://", _TLS13Adapter())
                response = session.post(
                    url=url, json=signed_envelope, headers=headers, timeout=60, verify=True,
                )
            else:
                response = requests.post(
                    url=url, json=signed_envelope, headers=headers, timeout=60, verify=True,
                )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise UserError(
                _("E-Invoice authentication server unreachable: %s") % exc
            ) from exc

        _logger.info("E-Invoice auth response ← HTTP %s", response.status_code)

        if response.status_code != 200:
            raise UserError(_("Authentication failed: %s") % response.text)

        data = response.json().get('data')
        if not data:
            raise UserError(_("Invalid authentication response format — 'data' key missing."))

        # Deactivate previous tokens
        self.env['einvoice.token'].sudo().search([
            ('company_id', '=', company.id),
            ('config_id', '=', config.id),
            ('active', '=', True),
        ]).write({'active': False})

        # Create new token sensitive values routed to .env via ORM override
        self.env['einvoice.token'].sudo().create({
            'company_id': company.id,
            'config_id': config.id,
            'access_token': data['accessToken'],
            'refresh_token': data['refreshToken'],
            'encryption_key': data.get('encryptionKey'),
            'expiry_datetime': fields.Datetime.now() + timedelta(
                seconds=int(data['expiresIn'])
            ),
            'active': True,
        })



# import logging
# import pprint
# import requests
# import ssl
# from datetime import timedelta
# from requests.adapters import HTTPAdapter

# from odoo import models, fields, _
# from odoo.exceptions import UserError

# _logger = logging.getLogger(__name__)

# class _TLS13Adapter(HTTPAdapter):
#     def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
#         try:
#             ctx = ssl.create_default_context()
#             if hasattr(ssl, "TLSVersion"):
#                 ctx.minimum_version = ssl.TLSVersion.TLSv1_3
#             pool_kwargs["ssl_context"] = ctx
#         except Exception:
#             pass
#         return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


# class EinvoiceAuthService(models.AbstractModel):
#     _name = 'einvoice.auth.service'
#     _description = 'E-Invoice Authentication Service'

#     def authenticate(self, company, config=None):
#         if config:
#             config = config.sudo()
#         else:
#             config = self.env['einvoice.config'].sudo().search([
#                 ('company_id', '=', company.id),
#                 ('active', '=', True),
#             ], limit=1)
#         if not config:
#             raise UserError(
#                 _("No active E-Invoice configuration found for company %s.") % company.name
#             )

#         raw_payload = {
#             "clientId": config.client_id.strip(),
#             "clientSecret": config.client_secret.strip(),
#             "apikey": config.api_key.strip(),
#             "tin": config.seller_tin.strip(),
#         }
#         # _logger.info("Company Config: %s ", pprint.pformat(raw_payload))
#         # _logger.info("Company Config SourceNumber %s", config.system_number.strip(),)

#         signed_envelope = self.env['einvoice.signature.service'].sign_request(
#             source_number=config.system_number,
#             payload_dict=raw_payload,
#         )

#         # _logger.info("Signed Config: %s ", pprint.pformat(signed_envelope))


#         url = f"{config.get_base_url()}/auth/login"
#         headers = {
#             "Content-Type": "application/json",
#             "Accept": "application/json",
#         }

#         icp = self.env["ir.config_parameter"].sudo()
#         enforce_tls13 = (
#             str(icp.get_param("ethiopian_einvoice_hardening.enforce_tls13_outbound") or "")
#             .strip().lower() in {"1", "true", "yes", "on"})

#         try:
#             if enforce_tls13:
#                 session = requests.Session()
#                 session.mount("https://", _TLS13Adapter())
#                 response = session.post(
#                     url=url, json=signed_envelope, headers=headers, timeout=60, verify=True,
#                 )
#             else:
#                 response = requests.post(
#                     url=url, json=signed_envelope, headers=headers, timeout=60, verify=True,
#                 )
#         except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
#             raise UserError(
#                 _("E-Invoice authentication server unreachable: %s") % exc
#             ) from exc

#         _logger.info("E-Invoice auth response ← HTTP %s", response.status_code)

#         if response.status_code != 200:
#             raise UserError(_("Authentication failed: %s") % response.text)

#         data = response.json().get('data')
#         if not data:
#             raise UserError(_("Invalid authentication response format — 'data' key missing."))

#         self.env['einvoice.token'].sudo().search([
#             ('company_id', '=', company.id),
#             ('config_id', '=', config.id),
#             ('active', '=', True),
#         ]).write({'active': False})

#         self.env['einvoice.token'].sudo().create({
#             'company_id': company.id,
#             'config_id': config.id,
#             'access_token': data['accessToken'],
#             'refresh_token': data['refreshToken'],
#             'encryption_key': data.get('encryptionKey'),
#             'expiry_datetime': fields.Datetime.now() + timedelta(
#                 seconds=int(data['expiresIn'])
#             ),
#             'active': True,
#         })
