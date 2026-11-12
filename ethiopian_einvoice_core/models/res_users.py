from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    einvoice_config_id = fields.Many2one(
        'einvoice.config',
        string='E-Invoice System Number',
        domain="[('active', '=', True), ('company_id', 'in', company_ids)]",
        help='System number/source number profile used when registering e-invoices.',
    )

    @api.constrains('einvoice_config_id', 'company_ids', 'groups_id')
    def _check_einvoice_config_company(self):
        einvoice_group = self.env.ref('ethiopian_einvoice_core.group_einvoice_user', raise_if_not_found=False)
        for user in self:
            if einvoice_group and einvoice_group in user.groups_id and not user.einvoice_config_id:
                raise ValidationError(_(
                    "Users in 'E-Invoice User' group must have an E-Invoice System Number assigned."
                ))
            if user.einvoice_config_id:
                allowed = user.company_ids
                if user.einvoice_config_id.company_id not in allowed:
                    raise ValidationError(_(
                        "E-Invoice configuration %(config)s belongs to company %(company)s, "
                        "which is not allowed for user %(user)s.",
                        config=user.einvoice_config_id.display_name,
                        company=user.einvoice_config_id.company_id.name,
                        user=user.name,
                    ))
