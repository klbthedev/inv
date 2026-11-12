import logging

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key
import base64
import json

from odoo import models
from odoo.exceptions import UserError
from ..utils import env_config

_logger = logging.getLogger(__name__)


class SignatureService(models.AbstractModel):
    _name = 'einvoice.signature.service'
    _description = 'E-Invoice Signature Service'

    def sign_request(self, source_number, payload_dict):
        cert_rec = self._get_certificate(source_number)
        private_key = self._load_private_key(source_number)
        certificate_b64 = self._get_certificate_b64(source_number)

        serialised = json.dumps(payload_dict, separators=(',', ':'), ensure_ascii=False)
        payload_bytes = serialised.encode('utf-8')

        try:
            raw_signature = private_key.sign(
                payload_bytes,
                padding.PKCS1v15(),
                hashes.SHA512(),
            )
        except Exception as exc:
            _logger.exception("Failed to sign payload for source_number=%s", source_number)
            raise UserError( f"E-Invoice signing failed for source number {source_number}: {exc}" ) from exc

        signature_b64 = base64.b64encode(raw_signature).decode('ascii')
        _logger.debug("Signed payload for source_number=%s  cert_serial=%s",source_number, cert_rec.serial_number,)

        return {
            "request": payload_dict,
            "signature": signature_b64,
            "certificate": certificate_b64,
        }

    def _get_certificate(self, source_number):
        cert = self.env['einvoice.certificate'].sudo().search([
            ('source_number', '=', source_number),
            ('active', '=', True),
        ], limit=1)
        if not cert:
            raise UserError( f"No active e-invoice certificate found for source number '{source_number}'. Please upload the certificate in E-Invoicing → Certificate Management.")
        return cert

    def _load_private_key(self, source_number):
        """Load the private key directly from the .env file."""
        key_bytes = env_config.get_private_key_pem(source_number)
        if not key_bytes:
            raise UserError(
                f"Private key not found in secure storage for source number '{source_number}'. "
                "Please re-upload the certificate and key."
            )
        try:
            password_str = env_config.get_private_key_password(source_number)
            password = password_str.encode() if password_str else None
            return load_pem_private_key(key_bytes, password=password, backend=default_backend())
        except Exception as exc:
            _logger.exception("Cannot load private key for source_number=%s", source_number)
            raise UserError(
                f"Cannot load private key for source number '{source_number}': {exc}"
            ) from exc

    def _get_certificate_b64(self, source_number):
        """Return the certificate as base64 for the signed envelope."""
        raw_pem = env_config.get_certificate_pem(source_number)
        if not raw_pem:
            raise UserError(
                f"Certificate not found in secure storage for source number '{source_number}'. "
                "Please re-upload the certificate."
            )
        return base64.b64encode(raw_pem).decode('ascii')




# import base64
# import json
# import logging

# from cryptography.hazmat.backends import default_backend
# from cryptography.hazmat.primitives import hashes
# from cryptography.hazmat.primitives.asymmetric import padding
# from cryptography.hazmat.primitives.serialization import load_pem_private_key

# from odoo import models
# from odoo.exceptions import UserError

# _logger = logging.getLogger(__name__)


# class SignatureService(models.AbstractModel):
#     _name = 'einvoice.signature.service'
#     _description = 'E-Invoice Signature Service'

#     def sign_request(self, source_number, payload_dict):
#         cert_rec = self._get_certificate(source_number)
#         private_key = self._load_private_key(cert_rec)
#         certificate_b64 = self._get_certificate_b64(cert_rec)

#         serialised = json.dumps(payload_dict, separators=(',', ':'), ensure_ascii=False)
#         payload_bytes = serialised.encode('utf-8')

#         try:
#             raw_signature = private_key.sign(
#                 payload_bytes,
#                 padding.PKCS1v15(),
#                 hashes.SHA512(), # SHA512RSA
#             )
#         except Exception as exc:
#             _logger.exception("Failed to sign payload for source_number=%s", source_number)
#             raise UserError(f"E-Invoice signing failed for source number {source_number}: {exc}") from exc

#         signature_b64 = base64.b64encode(raw_signature).decode('ascii')

#         _logger.debug("Signed payload for source_number=%s  cert_serial=%s",source_number, cert_rec.serial_number,)

#         return {
#             "request": payload_dict,
#             "signature": signature_b64,
#             "certificate": certificate_b64,
#         }

#     def _get_certificate(self, source_number):
#         cert = self.env['einvoice.certificate'].sudo().search([
#             ('source_number', '=', source_number),
#             ('active', '=', True),
#         ], limit=1)

#         if not cert:
#             raise UserError(
#                 f"No active e-invoice certificate found for source number '{source_number}'. "
#                 "Please upload the certificate in E-Invoicing → Certificate Management."
#             )
#         return cert

#     def _load_private_key(self, cert_rec):
#         try:
#             key_bytes = base64.b64decode(cert_rec.private_key_pem)
#             password = (
#                 cert_rec.private_key_password.encode()
#                 if cert_rec.private_key_password
#                 else None
#             )
#             return load_pem_private_key(key_bytes, password=password, backend=default_backend())
#         except Exception as exc:
#             _logger.exception("Cannot load private key for source_number=%s", cert_rec.source_number)
#             raise UserError(
#                 f"Cannot load private key for source number '{cert_rec.source_number}': {exc}"
#             ) from exc

#     def _get_certificate_b64(self, cert_rec):
#         raw_pem = base64.b64decode(cert_rec.certificate_pem)
#         return base64.b64encode(raw_pem).decode('ascii')
