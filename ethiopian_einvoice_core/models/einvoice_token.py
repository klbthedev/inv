from odoo import api, models, fields
import logging
from ..utils import env_config

_logger = logging.getLogger(__name__)


class EinvoiceToken(models.Model):
    _name = 'einvoice.token'
    _description = 'E-Invoice Token'
    _order = 'expiry_datetime desc'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        ondelete='cascade',
        index=True,
    )
    config_id = fields.Many2one(
        'einvoice.config',
        string='E-Invoice Configuration',
        ondelete='cascade',
    )

    access_token = fields.Text(
        string='Access Token',
        store=False,
        readonly=True,
        help='Stored securely outside the database.',
    )
    refresh_token = fields.Text(
        string='Refresh Token',
        store=False,
        readonly=True,
        help='Stored securely outside the database.',
    )
    encryption_key = fields.Char(
        string='Encryption Key',
        store=False,
        readonly=True,
        help='Stored securely outside the database.',
    )

    expiry_datetime = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)

    def _system_number(self) -> "str | None":
        self.ensure_one()
        return self.config_id.system_number if self.config_id else None
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            rec._flush_tokens_to_env(vals)
        return records

    def write(self, vals):
        result = super().write(vals)
        for rec in self:
            rec._flush_tokens_to_env(vals)
        return result

    def unlink(self):
        for rec in self:
            sn = rec._system_number()
            if sn:
                env_config.delete_token(sn)
        return super().unlink()

    def _flush_tokens_to_env(self, vals):
        self.ensure_one()
        sn = self._system_number()
        if not sn:
            return
        if vals.get('access_token'):
            env_config.set_access_token(sn, vals['access_token'])
        if vals.get('refresh_token'):
            env_config.set_refresh_token(sn, vals['refresh_token'])
        if vals.get('encryption_key'):
            env_config.set_encryption_key(sn, vals['encryption_key'])

    def get_access_token(self) -> str:
        self.ensure_one()
        sn = self._system_number()
        return (env_config.get_access_token(sn) if sn else '') or ''

    def get_refresh_token(self) -> str:
        self.ensure_one()
        sn = self._system_number()
        return (env_config.get_refresh_token(sn) if sn else '') or ''

    def get_encryption_key(self) -> str:
        self.ensure_one()
        sn = self._system_number()
        return (env_config.get_encryption_key(sn) if sn else '') or ''

    def is_expired(self) -> bool:
        self.ensure_one()
        return not self.expiry_datetime or self.expiry_datetime <= fields.Datetime.now()
    