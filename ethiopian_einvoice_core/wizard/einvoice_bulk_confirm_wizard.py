import logging
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EinvoiceBulkConfirmWizard(models.TransientModel):
    _name = 'einvoice.bulk.confirm.wizard'
    _description = 'Confirm Bulk E-Invoice Submission'

    move_ids = fields.Many2many('account.move', readonly=True)

    def action_confirm_bulk(self):
        _logger.info("Bulk E-Invoice moves: %s", self.move_ids.ids)
        if not self.move_ids:
            raise UserError(_("No invoices selected."))
        self.env['einvoice.invoice.service'].register_bulk_invoices(self.move_ids)
        return {'type': 'ir.actions.act_window_close'}