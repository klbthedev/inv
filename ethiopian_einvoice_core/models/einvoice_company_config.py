from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
from ..utils import env_config

_logger = logging.getLogger(__name__)


class EinvoiceConfig(models.Model):
    _name = 'einvoice.config'
    _description = 'E-Invoice Configuration'
    _rec_name = 'company_id'
    region = fields.Selection([
        ("1", "Addis Ababa"),
        ("3", "Tigray"),
        ("4", "Afar"),
        ("11", "Amhara"),
        ("2", "Oromia"),
        ("6", "Somali"),
        ("5", "Benishangul Gumuz"),
        ("7", "Gambella"),
        ("9", "SNNPRS"),
        ("10", "DireDawa"),
        ("17", "Central Ethiopia"),
        ("14", "Sidama"),
        ("15", "South West"),
    ])
    zone = fields.Char(string="Zone")
    wereda = fields.Char(string="Wereda")
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    token_ids = fields.One2many('einvoice.token', 'config_id', string='Tokens')
    counter_ids = fields.One2many('einvoice.counter', 'config_id', string='Fiscal Counters')

    # Sensitive credential fields — NOT stored in the database.
    # Values are written to the .env file on save.
    client_id = fields.Char(
        string='Client ID',
        store=False,
        help='Stored securely outside the database.',
    )
    client_secret = fields.Char(
        string='Client Secret',
        store=False,
        help='Stored securely outside the database.',
    )
    api_key = fields.Char(
        string='API Key',
        store=False,
        help='Stored securely outside the database.',
    )

    # Indicator shown in the UI so the operator knows credentials are set
    credentials_configured = fields.Boolean(
        string='Credentials Configured',
        compute='_compute_credentials_configured',
        store=False,
    )

    seller_tin = fields.Char(
        string='Seller TIN',
        compute='_compute_seller_tin',
        store=True,
        readonly=True,
    )
    einvoice_callback_url = fields.Char(string="Callback URL")
    vat_number = fields.Char(string='VAT Number')
    system_type = fields.Selection(
        [('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS')],
        string='System Type',
        default='ERP',
    )
    source_system_type = fields.Selection(
        [('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS')],
        string='Source System Type',
        default='ERP',
    )
    source_system_number = fields.Char(
        string='System / Source System Number',
        compute='_compute_source_system_number',
        inverse='_inverse_source_system_number',
        store=True,
    )
    system_number = fields.Char(
        string='System / Source System Number',
        required=True,
    )
    environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        default='sandbox',
        required=True,
    )
    sandbox_base_url = fields.Char(default='https://core.mor.gov.et', required=True)
    production_base_url = fields.Char(default='https://core.mor.gov.et', required=True)
    active = fields.Boolean(default=True)

    geo_fencing_mode = fields.Selection([
        ('radius', 'Radius'),
        ('country', 'Country'),
    ], string='Geo-Fencing Mode', default='radius')
    geo_fencing_radius = fields.Integer(string='Allowed Radius (meters)', default=100)
    geo_fencing_latitude = fields.Float(string='Reference Latitude', digits=(10, 7), default=9.1450)
    geo_fencing_longitude = fields.Float(string='Reference Longitude', digits=(10, 7), default=40.489673)
    geo_fencing_country_geojson = fields.Text(string='Country Boundary GeoJSON')

    _sql_constraints = [
        (
            'einvoice_config_unique_company_system_number',
            'unique(company_id, system_number)',
            'An E-Invoice configuration with this system number already exists for this company.',
        ),
    ]

    @api.depends('system_number')
    def _compute_credentials_configured(self):
        for rec in self:
            if not rec.system_number:
                rec.credentials_configured = False
                continue
            rec.credentials_configured = all([
                env_config.get_client_id(rec.system_number),
                env_config.get_client_secret(rec.system_number),
                env_config.get_api_key(rec.system_number),
            ])

    @api.depends('system_number')
    def _compute_source_system_number(self):
        for rec in self:
            rec.source_system_number = rec.system_number

    def _inverse_source_system_number(self):
        for rec in self:
            rec.system_number = rec.source_system_number

    @api.depends('company_id.vat')
    def _compute_seller_tin(self):
        for rec in self:
            rec.seller_tin = rec.company_id.vat or ''

    # Public accessors — used throughout the module instead of field reads
    def get_client_id(self):
        self.ensure_one()
        return env_config.get_client_id(self.system_number) or ''

    def get_client_secret(self):
        self.ensure_one()
        return env_config.get_client_secret(self.system_number) or ''

    def get_api_key(self):
        self.ensure_one()
        return env_config.get_api_key(self.system_number) or ''

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            rec._flush_credentials_to_env(vals)
        Counter = self.env['einvoice.counter'].sudo()
        for rec in records:
            if not Counter.search([('config_id', '=', rec.id)], limit=1):
                Counter.create({
                    'config_id': rec.id,
                    'company_id': rec.company_id.id,
                    'next_number': 1,
                })
        return records

    def write(self, vals):
        result = super().write(vals)
        for rec in self:
            rec._flush_credentials_to_env(vals)
        return result

    def unlink(self):
        for rec in self:
            env_config.delete_config_credentials(rec.system_number)
        return super().unlink()

    def _flush_credentials_to_env(self, vals):
        self.ensure_one()
        if not self.system_number:
            return
        if 'client_id' in vals and vals['client_id']:
            env_config.set_client_id(self.system_number, vals['client_id'])
        if 'client_secret' in vals and vals['client_secret']:
            env_config.set_client_secret(self.system_number, vals['client_secret'])
        if 'api_key' in vals and vals['api_key']:
            env_config.set_api_key(self.system_number, vals['api_key'])

    @api.constrains('active', 'company_id', 'system_number')
    def _check_unique_active_profile(self):
        for rec in self:
            if not rec.active:
                continue
            domain = [
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                ('id', '!=', rec.id),
                ('system_number', '=', rec.system_number),
            ]
            if self.search_count(domain):
                raise ValidationError(_(
                    "Only one active E-Invoice configuration is allowed per company and system number."
                ))

    def get_base_url(self):
        self.ensure_one()
        return (
            self.sandbox_base_url
            if self.environment == 'sandbox'
            else self.production_base_url
        )



# from odoo import models, fields, api, _
# from odoo.exceptions import ValidationError
# import logging

# _logger = logging.getLogger(__name__)


# class EinvoiceConfig(models.Model):
#     _name = 'einvoice.config'
#     _description = 'E-Invoice Configuration'
#     _rec_name = 'company_id'
#     region = fields.Selection([
#         ("1", "Addis Ababa"),
#         ("3", "Tigray"),
#         ("4", "Afar"),
#         ("11", "Amhara"),
#         ("2", "Oromia"),
#         ("6", "Somali"),
#         ("5", "Benishangul Gumuz"),
#         ("7", "Gambella"),
#         ("9", "SNNPRS"),
#         ("10", "DireDawa"),
#         ("17", "Central Ethiopia"),
#         ("14", "Sidama"),
#         ("15", "South West"),
#     ])
#     zone = fields.Char(string="Zone")
#     wereda = fields.Char(string="Wereda")
#     company_id = fields.Many2one(
#         'res.company',
#         required=True,
#         default=lambda self: self.env.company,
#         ondelete='cascade',
#     )
#     token_ids = fields.One2many(
#         'einvoice.token',
#         'config_id',
#         string='Tokens',
#     )
#     counter_ids = fields.One2many(
#         'einvoice.counter',
#         'config_id',
#         string='Fiscal Counters',
#     )

#     client_id = fields.Char(string='Client ID', required=True)
#     client_secret = fields.Char(string='Client Secret', required=True)
#     api_key = fields.Char(string='API Key', required=True)
#     seller_tin = fields.Char(
#         string='Seller TIN',
#         compute='_compute_seller_tin',
#         store=True,
#         readonly=True,
#     )
#     einvoice_callback_url = fields.Char(string="Callback URL")

#     vat_number = fields.Char(
#         string='VAT Number',
#         help='Seller VAT Number for SellerDetails payload',
#     )
#     system_type = fields.Selection(
#         [('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS')],
#         string='System Type',
#         default='ERP',
#         help='SourceSystem.SystemType in invoice payload',
#     )
#     source_system_type = fields.Selection(
#         [('POS', 'POS'), ('ERP', 'ERP'), ('SPOS', 'SPOS')],
#         string='Source System Type',
#         default='ERP',
#         help='SourceSystemType in receipt payload',
#     )
#     source_system_number = fields.Char(
#         string='System / Source System Number',
#         compute='_compute_source_system_number',
#         inverse='_inverse_source_system_number',
#         store=True,
#         help='Unified number used for both SourceSystem.SystemNumber and SourceSystemNumber.',
#     )
#     system_number = fields.Char(
#         string='System / Source System Number',
#         required=True,
#         help='Unified number used for both SourceSystem.SystemNumber and SourceSystemNumber.',
#     )

#     @api.depends('system_number')
#     def _compute_source_system_number(self):
#         for rec in self:
#             rec.source_system_number = rec.system_number

#     def _inverse_source_system_number(self):
#         for rec in self:
#             rec.system_number = rec.source_system_number

#     @api.depends('company_id.vat')
#     def _compute_seller_tin(self):
#         for rec in self:
#             rec.seller_tin = rec.company_id.vat or ''

#     environment = fields.Selection(
#         [('sandbox', 'Sandbox'), ('production', 'Production')],
#         default='sandbox',
#         required=True,
#     )

#     sandbox_base_url = fields.Char(
#         default='https://core.mor.gov.et',
#         required=True,
#     )
#     production_base_url = fields.Char(
#         default='https://core.mor.gov.et',
#         required=True,
#     )

#     active = fields.Boolean(default=True)

#     _sql_constraints = [
#         (
#             'einvoice_config_unique_company_system_number',
#             'unique(company_id, system_number)',
#             'An E-Invoice configuration with this system number already exists for this company.',
#         ),
#     ]

#     @api.constrains('active', 'company_id', 'system_number')
#     def _check_unique_active_profile(self):
#         for rec in self:
#             if not rec.active:
#                 continue
#             domain = [
#                 ('company_id', '=', rec.company_id.id),
#                 ('active', '=', True),
#                 ('id', '!=', rec.id),
#                 ('system_number', '=', rec.system_number),
#             ]
#             if self.search_count(domain):
#                 raise ValidationError(_(
#                     "Only one active E-Invoice configuration is allowed per company and system number."
#                 ))

#     @api.model_create_multi
#     def create(self, vals_list):
#         records = super().create(vals_list)
#         Counter = self.env['einvoice.counter'].sudo()
#         for rec in records:
#             if not Counter.search([('config_id', '=', rec.id)], limit=1):
#                 Counter.create({
#                     'config_id': rec.id,
#                     'company_id': rec.company_id.id,
#                     'next_number': 1,
#                 })
#         return records

#     def get_base_url(self):
#         self.ensure_one()
#         return (
#             self.sandbox_base_url
#             if self.environment == 'sandbox'
#             else self.production_base_url
#         )
