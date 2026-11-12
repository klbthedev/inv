from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EinvoiceCounter(models.Model):
    _name = 'einvoice.counter'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fiscal Invoice Counter'
    _rec_name = 'config_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='cascade',
    )
    config_id = fields.Many2one(
        'einvoice.config',
        string='E-Invoice Configuration',
        required=True,
        ondelete='cascade',
        index=True,
    )
    next_number = fields.Integer(string='Next Number', default=1, required=True, tracking=True)

    _sql_constraints = [
        (
            'einvoice_counter_unique_config',
            'unique(config_id)',
            'Each E-Invoice configuration may have only one fiscal counter.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('config_id') and not vals.get('company_id'):
                config = self.env['einvoice.config'].browse(vals['config_id'])
                vals['company_id'] = config.company_id.id
        return super().create(vals_list)


class AccountMove(models.Model):
    _inherit = 'account.move'

    x_einvoice_reserved_document_number = fields.Char(
        string='Reserved E-Invoice Document Number',
        copy=False,
        readonly=True,
        help='Fiscal document number reserved before API submission (not rolled back on failure).',
    )

    def _reserve_fiscal_number(self, config):
        self.ensure_one()
        config.ensure_one()
        self.env.cr.execute("""
            SELECT id, next_number
            FROM einvoice_counter
            WHERE config_id = %s
            FOR UPDATE
        """, [config.id])
        row = self.env.cr.fetchone()
        if not row:
            counter = self.env['einvoice.counter'].sudo().create({
                'config_id': config.id,
                'company_id': config.company_id.id,
                'next_number': 1,
            })
            self.env.cr.execute("""
                SELECT id, next_number
                FROM einvoice_counter
                WHERE id = %s
                FOR UPDATE
            """, [counter.id])
            row = self.env.cr.fetchone()
        counter_id, next_number = row
        reserved_number = next_number
        self.env.cr.execute("""
            UPDATE einvoice_counter
            SET next_number = %s
            WHERE id = %s
        """, [next_number + 1, counter_id])
        reserved_str = str(reserved_number)
        self.write({'x_einvoice_reserved_document_number': reserved_str})
        return reserved_str
