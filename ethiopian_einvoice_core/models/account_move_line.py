from odoo import api, fields, models

class AccountDebitNote(models.TransientModel):
    _inherit = 'account.debit.note'

    copy_lines = fields.Boolean("Copy Lines",help="In case you need to do corrections for every line, it can be in handy to copy them. We won't copy them for debit notes from credit notes. ", default=True)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    nature_of_goods = fields.Selection([
        ("goods", "Goods"),
        ("service", "Service"),
    ], )

    x_excise_tax_value_line = fields.Monetary(
        string="Excise (on gross)",
        compute="_compute_x_excise_tax_value_line",
        store=True,
        currency_field="currency_id",
        help="Excise tax amount computed on gross (quantity × unit price), before line discount.",
    )
    x_line_total_wo_vat = fields.Monetary(
        string="Total Amount (w/o VAT)",
        compute="_compute_x_line_total_wo_vat",
        store=True,
        currency_field="currency_id",
        help="Line total excluding VAT15. Includes discount impact and excise amount.",
    )
    x_line_gross_extended = fields.Monetary(
        string="Line Gross (Qty × Unit Price)",
        compute="_compute_x_line_gross_extended",
        store=True,
        currency_field="currency_id",
        help="Quantity × unit price before discount (matches invoice2 PDF Total Amount column).",
    )

    @api.depends("quantity", "price_unit", "tax_ids", "tax_ids.amount", "tax_ids.tax_group_id", "tax_ids.name", "currency_id", "display_type")
    def _compute_x_excise_tax_value_line(self):
        for line in self:
            if line.display_type not in (False, "product") or not line.tax_ids:
                line.x_excise_tax_value_line = 0.0
                continue
            excise_tax = None
            for tax in line.tax_ids:
                name = (tax.name or "").lower()
                group_name = (tax.tax_group_id.name or "").lower()
                if "excise" in name or "excise" in group_name:
                    excise_tax = tax
                    break
            if not excise_tax:
                line.x_excise_tax_value_line = 0.0
                continue
            gross = line.quantity * line.price_unit
            rate = excise_tax.amount or 0.0
            amount = gross * (rate / 100.0)
            line.x_excise_tax_value_line = line.currency_id.round(amount) if line.currency_id else round(amount, 2)

    @api.depends("quantity", "price_unit", "currency_id", "display_type")
    def _compute_x_line_gross_extended(self):
        for line in self:
            if line.display_type not in (False, "product"):
                line.x_line_gross_extended = 0.0
                continue
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            line.x_line_gross_extended = line.currency_id.round(gross) if line.currency_id else round(gross, 2)

    @api.depends("quantity", "price_unit", "discount", "x_excise_tax_value_line", "currency_id", "display_type")
    def _compute_x_line_total_wo_vat(self):
        for line in self:
            if line.display_type not in (False, "product"):
                line.x_line_total_wo_vat = 0.0
                continue
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            discount_amount = gross * ((line.discount or 0.0) / 100.0)
            pre_tax = gross - discount_amount
            total_wo_vat = pre_tax + (line.x_excise_tax_value_line or 0.0)
            line.x_line_total_wo_vat = line.currency_id.round(total_wo_vat) if line.currency_id else round(total_wo_vat, 2)
