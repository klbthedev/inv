import base64
import math
import logging

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from ..utils import env_config

_logger = logging.getLogger(__name__)


class EInvoiceCertificate(models.Model):
    _name = 'einvoice.certificate'
    _description = 'E-Invoice Certificate'
    _rec_name = 'display_name'
    _order = 'source_number'

    name = fields.Char(
        string='Label',
        required=True,
        help='Human-readable label, e.g. "HQ – SourceNumber".',
    )
    source_number = fields.Char(
        string='Source Number',
        required=True,
        index=True,
        help='Must match the System Number in the corresponding E-Invoice configuration.',
    )

    # Sensitive fields — NOT stored in the database (store=False).
    # Values are written to the .env file on save and never persisted in any Odoo table or attachment.
    certificate_pem = fields.Binary(
        string='Certificate (.pem / .crt)',
        attachment=False,
        store=False,
        help='Upload the .pem file received from INSA.  Stored securely outside the database.',
    )
    certificate_filename = fields.Char(string='Certificate Filename', store=False)

    private_key_pem = fields.Binary(
        string='Private Key (.key)',
        attachment=False,
        store=False,
        help='RSA private key.  Stored securely outside the database.',
    )
    private_key_filename = fields.Char(string='Private Key Filename', store=False)

    private_key_password = fields.Char(
        string='Private Key Password',
        store=False,
        help='Leave blank if the key was generated without a passphrase.',
    )

    # Indicates whether secrets are present in the .env file
    cert_configured = fields.Boolean(
        string='Certificate Loaded',
        compute='_compute_cert_configured',
        store=False,
    )
    key_configured = fields.Boolean(
        string='Private Key Loaded',
        compute='_compute_cert_configured',
        store=False,
    )

    active = fields.Boolean(default=True)

    valid_from = fields.Datetime(string='Valid From', readonly=True)
    valid_to = fields.Datetime(string='Valid To', readonly=True)
    serial_number = fields.Char(string='Serial Number', readonly=True)
    issuer = fields.Char(string='Issuer', readonly=True)
    subject = fields.Char(string='Subject', readonly=True)

    is_expired = fields.Boolean(compute="_compute_expiry_status", store=False)
    is_expiring_soon = fields.Boolean(compute="_compute_expiry_status", store=False)
    days_to_expiry = fields.Integer(compute="_compute_expiry_status", store=False)

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    _sql_constraints = [
        (
            'source_number_unique',
            'unique(source_number)',
            'A certificate for this Source Number already exists.  '
            'Archive the existing one before adding a new certificate.',
        )
    ]

    @api.depends('name', 'source_number')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.name} [{rec.source_number}]"
                if rec.source_number
                else rec.name or ''
            )

    @api.depends('source_number')
    def _compute_cert_configured(self):
        for rec in self:
            rec.cert_configured = bool(
                rec.source_number and
                env_config.get_certificate_pem(rec.source_number)
            )
            rec.key_configured = bool(
                rec.source_number and
                env_config.get_private_key_pem(rec.source_number)
            )

    @api.depends("valid_to")
    def _compute_expiry_status(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_expired = False
            rec.is_expiring_soon = False
            rec.days_to_expiry = 0
            if rec.valid_to:
                delta = (rec.valid_to - now).days
                rec.days_to_expiry = delta
                rec.is_expired = delta < 0
                rec.is_expiring_soon = 0 <= delta <= 30

    # ORM overrides — intercept writes to push secrets to .env
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            rec._flush_secrets_to_env(vals)
        return records

    def write(self, vals):
        result = super().write(vals)
        for rec in self:
            rec._flush_secrets_to_env(vals)
        return result

    def unlink(self):
        for rec in self:
            env_config.delete_certificate(rec.source_number)
        return super().unlink()

    def _flush_secrets_to_env(self, vals):
        """Persist any secrets found in *vals* to the .env file."""
        self.ensure_one()
        if not self.source_number:
            return
        changed = False
        cert_b64 = vals.get('certificate_pem')
        if cert_b64:
            env_config.set_certificate_pem(self.source_number, cert_b64)
            changed = True
        key_b64 = vals.get('private_key_pem')
        if key_b64:
            env_config.set_private_key_pem(self.source_number, key_b64)
            changed = True
        # Password: store even if empty string (means "clear it")
        if 'private_key_password' in vals:
            env_config.set_private_key_password(
                self.source_number, vals['private_key_password'] or ''
            )
            changed = True

        if changed:
            self._parse_and_store_cert_metadata()
            self._verify_private_key()

    # Validation — reads from .env, never from DB fields

    @api.constrains('source_number')
    def _validate_certificate_and_key(self):
        for rec in self:
            if env_config.get_certificate_pem(rec.source_number):
                rec._parse_and_store_cert_metadata()
            if env_config.get_private_key_pem(rec.source_number):
                rec._verify_private_key()

    def _parse_and_store_cert_metadata(self):
        self.ensure_one()
        cert_bytes = env_config.get_certificate_pem(self.source_number)
        if not cert_bytes:
            return 
        try:
            leaf_pem = self._extract_leaf_pem(cert_bytes)
            cert = x509.load_pem_x509_certificate(leaf_pem, default_backend())
        except Exception as exc:
            raise ValidationError(
                f"Cannot parse certificate for source number '{self.source_number}': {exc}"
            ) from exc

        self.serial_number = format(cert.serial_number, 'X')
        self.issuer = cert.issuer.rfc4514_string()
        self.subject = cert.subject.rfc4514_string()
        try:
            self.valid_from = cert.not_valid_before_utc.replace(tzinfo=None)
            self.valid_to = cert.not_valid_after_utc.replace(tzinfo=None)
        except AttributeError:
            self.valid_from = cert.not_valid_before
            self.valid_to = cert.not_valid_after

    def _verify_private_key(self):
        self.ensure_one()
        key_bytes = env_config.get_private_key_pem(self.source_number)
        if not key_bytes:
            return 
        try:
            password_str = env_config.get_private_key_password(self.source_number)
            password = password_str.encode() if password_str else None
            load_pem_private_key(key_bytes, password=password, backend=default_backend())
        except Exception as exc:
            raise ValidationError(
                f"Cannot load private key for source number '{self.source_number}': {exc}"
            ) from exc

    @staticmethod
    def _extract_leaf_pem(pem_bytes: bytes) -> bytes:
        marker_begin = b'-----BEGIN CERTIFICATE-----'
        marker_end = b'-----END CERTIFICATE-----'
        start = pem_bytes.find(marker_begin)
        end = pem_bytes.find(marker_end)
        if start == -1 or end == -1:
            raise ValidationError("No PEM certificate block found in the uploaded file.")
        return pem_bytes[start: end + len(marker_end)]

    def action_check_expiry(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.valid_to:
            raise UserError("Certificate validity dates not yet parsed.  Please re-save the record.")
        delta = math.ceil((self.valid_to - now).total_seconds() / 86400) if self.valid_to > now else -1
        if delta < 0:
            raise UserError(
                f"⚠ Certificate for '{self.source_number}' has EXPIRED on "
                f"{self.valid_to.strftime('%Y-%m-%d %H:%M UTC')}.\n"
                "Obtain a new certificate from INSA immediately."
            )
        if delta <= 30:
            raise UserError(
                f"⚠ Certificate for '{self.source_number}' expires in {delta} day(s) "
                f"({self.valid_to.strftime('%Y-%m-%d %H:%M UTC')}).\n"
                "Start the certificate renewal process with INSA."
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Certificate Valid',
                'message': (
                    f"Certificate for '{self.source_number}' is valid for {delta} more day(s) "
                    f"(expires {self.valid_to.strftime('%Y-%m-%d')})."
                ),
                'type': 'success',
                'sticky': False,
            },
        }

# import base64
# import math
# import logging

# from cryptography import x509
# from cryptography.hazmat.backends import default_backend
# from cryptography.hazmat.primitives.serialization import load_pem_private_key

# from odoo import api, fields, models
# from odoo.exceptions import UserError, ValidationError

# _logger = logging.getLogger(__name__)


# class EInvoiceCertificate(models.Model):
#     _name = 'einvoice.certificate'
#     _description = 'E-Invoice Certificate'
#     _rec_name = 'display_name'
#     _order = 'source_number'

#     name = fields.Char(
#         string='Label',
#         required=True,
#         help='Human-readable label, e.g. "HQ – SourceNumber".',
#     )
#     source_number = fields.Char(
#         string='Source Number',
#         required=True,
#         index=True,
#         help='Must match the System Number in the corresponding E-Invoice configuration.',
#     )
#     certificate_pem = fields.Binary(
#         string='Certificate (.pem / .crt)',
#         required=True,
#         attachment=False,
#         help='Full PEM chain as issued by INSA.  Upload the .pem file received by email.',
#     )
#     certificate_filename = fields.Char(string='Certificate Filename')

#     private_key_pem = fields.Binary(
#         string='Private Key (.key)',
#         required=True,
#         attachment=False,
#         help='RSA private key generated before submitting the CSR.  Keep this secret.',
#     )
#     private_key_filename = fields.Char(string='Private Key Filename')

#     private_key_password = fields.Char(
#         string='Private Key Password',
#         help='Leave blank if the key was generated without a passphrase (default).',
#     )

#     active = fields.Boolean(default=True)

#     valid_from = fields.Datetime(string='Valid From', readonly=True)
#     valid_to = fields.Datetime(string='Valid To', readonly=True)
#     serial_number = fields.Char(string='Serial Number', readonly=True)
#     issuer = fields.Char(string='Issuer', readonly=True)
#     subject = fields.Char(string='Subject', readonly=True)

#     is_expired = fields.Boolean(
#         compute="_compute_expiry_status",
#         store=False,
#     )
#     is_expiring_soon = fields.Boolean(
#         compute="_compute_expiry_status",
#         store=False,
#     )
#     days_to_expiry = fields.Integer(
#         compute="_compute_expiry_status",
#         store=False,
#     )

#     display_name = fields.Char(
#         string='Display Name',
#         compute='_compute_display_name',
#         store=True,
#     )

#     _sql_constraints = [
#         (
#             'source_number_unique',
#             'unique(source_number)',
#             'A certificate for this Source Number already exists.  '
#             'Archive the existing one before adding a new certificate.',
#         )
#     ]

#     @api.depends('name', 'source_number')
#     def _compute_display_name(self):
#         for rec in self:
#             rec.display_name = (
#                 f"{rec.name} [{rec.source_number}]"
#                 if rec.source_number
#                 else rec.name or ''
#             )
        
#     @api.depends("valid_to")
#     def _compute_expiry_status(self):
#         now = fields.Datetime.now()
#         for rec in self:
#             rec.is_expired = False
#             rec.is_expiring_soon = False
#             rec.days_to_expiry = 0
#             if rec.valid_to:
#                 delta = (rec.valid_to - now).days
#                 rec.days_to_expiry = delta
#                 rec.is_expired = delta < 0
#                 rec.is_expiring_soon = 0 <= delta <= 30

#     @api.constrains('certificate_pem', 'private_key_pem', 'private_key_password')
#     def _validate_certificate_and_key(self):
#         for rec in self:
#             rec._parse_and_store_cert_metadata()
#             rec._verify_private_key()

#     def _parse_and_store_cert_metadata(self):
#         self.ensure_one()
#         try:
#             cert_bytes = base64.b64decode(self.certificate_pem)
#             leaf_pem = self._extract_leaf_pem(cert_bytes)
#             cert = x509.load_pem_x509_certificate(leaf_pem, default_backend())
#         except Exception as exc:
#             raise ValidationError(
#                 f"Cannot parse certificate for source number '{self.source_number}': {exc}"
#             ) from exc

#         self.serial_number = format(cert.serial_number, 'X')
#         self.issuer = cert.issuer.rfc4514_string()
#         self.subject = cert.subject.rfc4514_string()
#         # self.valid_from = cert.not_valid_before_utc.replace(tzinfo=None)
#         # self.valid_to = cert.not_valid_after_utc.replace(tzinfo=None)
#         try:
#             self.valid_from = cert.not_valid_before_utc.replace(tzinfo=None)
#             self.valid_to = cert.not_valid_after_utc.replace(tzinfo=None)
#         except AttributeError:
#             self.valid_from = cert.not_valid_before
#             self.valid_to = cert.not_valid_after

#     def _verify_private_key(self):
#         self.ensure_one()
#         try:
#             key_bytes = base64.b64decode(self.private_key_pem)
#             password = (
#                 self.private_key_password.encode()
#                 if self.private_key_password
#                 else None
#             )
#             load_pem_private_key(key_bytes, password=password, backend=default_backend())
#         except Exception as exc:
#             raise ValidationError(
#                 f"Cannot load private key for source number '{self.source_number}': {exc}"
#             ) from exc

#     @staticmethod
#     def _extract_leaf_pem(pem_bytes):
#         marker_begin = b'-----BEGIN CERTIFICATE-----'
#         marker_end = b'-----END CERTIFICATE-----'
#         start = pem_bytes.find(marker_begin)
#         end = pem_bytes.find(marker_end)
#         if start == -1 or end == -1:
#             raise ValidationError("No PEM certificate block found in the uploaded file.")
#         return pem_bytes[start: end + len(marker_end)]

#     def action_check_expiry(self):
#         self.ensure_one()
#         now = fields.Datetime.now()
#         if not self.valid_to:
#             raise UserError("Certificate validity dates not yet parsed.  Please re-save the record.")
#         delta = (self.valid_to - now).days if self.valid_to > now else -1
#         delta = math.ceil((self.valid_to - now).total_seconds() / 86400) if self.valid_to > now else -1
#         if delta < 0:
#             raise UserError(
#                 f"⚠ Certificate for '{self.source_number}' has EXPIRED on "
#                 f"{self.valid_to.strftime('%Y-%m-%d %H:%M UTC')}.\n"
#                 "Obtain a new certificate from INSA immediately."
#             )
#         if delta <= 30:
#             raise UserError(
#                 f"⚠ Certificate for '{self.source_number}' expires in {delta} day(s) "
#                 f"({self.valid_to.strftime('%Y-%m-%d %H:%M UTC')}).\n"
#                 "Start the certificate renewal process with INSA."
#             )
#         return {
#             'type': 'ir.actions.client',
#             'tag': 'display_notification',
#             'params': {
#                 'title': 'Certificate Valid',
#                 'message': (
#                     f"Certificate for '{self.source_number}' is valid for {delta} more day(s) "
#                     f"(expires {self.valid_to.strftime('%Y-%m-%d')})."
#                 ),
#                 'type': 'success',
#                 'sticky': False,
#             },
#         }
