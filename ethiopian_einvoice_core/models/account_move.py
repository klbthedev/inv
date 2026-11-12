import logging
from contextlib import contextmanager
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)




class AccountMove(models.Model):
    _inherit = "account.move"

    buyer_city = fields.Char(default="0")
    buyer_region = fields.Selection([
        ("3","Tigray"),
        ("4","Afar"),
        ("11","Amhara"),
        ("2","Oromia"),
        ("6","Somali"),
        ("5","Benishangul Gumuz"),
        ("7","Gambella"),
        ("9","SNNPRS"),
        ("1","Addis Ababa"),
        ("10","DireDawa"),
        ("17","Central Ethiopia"),
        ("14","Sidama"),
        ("15","South West"),
    ],)
    buyer_wereda = fields.Char(default="00")
    buyer_phone = fields.Char(string="Buyer Phone",compute="_compute_buyer_fields",inverse="_inverse_buyer_phone",store=True)
    buyer_email = fields.Char(string="Buyer Email",compute="_compute_buyer_fields",inverse="_inverse_buyer_email",store=True)
    buyer_vat = fields.Char(string="Buyer TIN",compute="_compute_buyer_fields",inverse="_inverse_buyer_vat",store=True)
    buyer_country = fields.Char(default="70")
    buyer_house_number = fields.Char(default="000")
    buyer_id_type = fields.Char(default="KID")
    buyer_number = fields.Char(default="000")
    transaction_type = fields.Selection([
        ("B2B","B2B - Business to Business"),
        ("B2C","B2C - Business to Customer"),
        ("B2G","B2G - Business to Government"),
    ], string="Transaction Type", help="Note: Tin Number is required for B2B transactions.")
    system_type = fields.Selection([
        ("POS","POS"),
        ("ERP","ERP - Enterprise Resource Planning System"),
        ("SPOS","SPOS - Smart POS"),
    ], string="System Type")
    mode_of_payment = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        ('CREDIT', 'CREDIT'),
        # ('CHEQUE', 'Cheque'),
        # ('CPO', 'CPO'),
        # ('Local Bank Transfer', 'Local Bank Transfer'),
        # ('SWIFT', 'SWIFT'),
        # ('Wire Transfer', 'Wire Transfer'),
        # ('Letter of Credit', 'Letter of Credit'),
        # ('Card', 'Card'),
    ], string="Mode of Payment") 
    mode_of_payment_receipt = fields.Selection([
        ('CASH', 'Cash'),
        ('ADVANCE', 'ADVANCE'),
        ('CREDIT', 'CREDIT'),
        ('CHEQUE', 'Cheque'),
        ('CPO', 'CPO'),
        ('BANK', 'Bank Transfer'),
        ('SWIFT', 'SWIFT'),
        ('WIRE', 'Wire Transfer'),
        ('LC', 'Letter of Credit'),
        ('CARD', 'Card'),
    ], string="Mode of Payment (Receipt)") 
    payment_term = fields.Selection([
        ('IMMEDIATE', 'Immediate'),
    ], string="Payment Term")
    x_clicked_by_id = fields.Many2one('res.users',string='Clicked By',readonly=True)
    payment_service_provider = fields.Selection([
        ("BANK","Bank"),
        ("TELEBIRR","TeleBirr"),
    ], string="Payment Service Provider")
    account_number = fields.Char('Account Number')
    transaction_number = fields.Char('Transaction Number')
    payment_coverage = fields.Selection([
        ("FULL","Full"),
        ("PARTIAL","Partial"),
    ],string="Payment Coverage")
    x_sales_type = fields.Selection(
        [
            ("cash", "Cash sales"),
            ("credit", "Credit sales"),
        ],
        string="Type of Sales",
        # compute="_compute_x_sales_type",
        store=False,
        help="Optional sales type sourced from partner_sequence when installed.",
    )
    remaining_amount = fields.Char("Remaining Amount")
    reason = fields.Char(string="Reason for Credit Note")
    re_einvoice_reason = fields.Selection([
        ("1","Duplicate"),
        ("2","Data Entry Mistake"),
        ("3","Order Canceled"),
        ("4","Others"),
    ], string="Reason")
    
    einvoice_status = fields.Selection([
        ('draft', 'Not Sent'),
        ('sent', 'Sent'),
        ('registered', 'Registered'),
        ('cancelled', 'Cancelled'),
        ('error', 'Error'),
    ], default='draft', copy=False, tracking=True)
    # einvoice_irn = fields.Char(string="IRN", copy=False, index=True)
    # einvoice_error = fields.Text(string="E-Invoice Error", copy=False)
    # einvoice_response_json = fields.Json(string="E-Invoice Full Response",copy=False,readonly=True)
    einvoice_submission_count = fields.Integer(default=0,copy=False,help="Retry safeguard counter")
    einvoice_config_id = fields.Many2one(
        'einvoice.config',
        string='E-Invoice Configuration',
        copy=False,
        readonly=True,
        help='Source profile used when this document was registered with MoR.',
    )

    x_einvoice_irn = fields.Char("E-Invoice IRN", copy=False, index=True)
    x_einvoice_status = fields.Selection(
        [('A', 'Active'), ('C', 'Cancelled')],
        string="E-Invoice Status",
        copy=False)
    x_einvoice_ack_date = fields.Datetime("E-Invoice Acknowledged At", copy=False)
    x_einvoice_document_number = fields.Char("E-Invoice Document Number", copy=False)
    x_einvoice_signed_invoice = fields.Text("Signed Invoice (Base64)", copy=False)
    x_einvoice_signed_qr = fields.Binary("Signed QR Code (Base64)",copy=False)
    x_einvoice_response_raw = fields.Json("E-Invoice Full Response",copy=False)
    x_einvoice_error_message = fields.Text("E-Invoice Error Message",copy=False)

    x_einvoice_cancel_status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('requested', 'Cancellation Requested'),
            ('cancelled', 'Cancelled'),
            ('failed', 'Failed'),
        ],
        string="E-Invoice Cancel Status",
        copy=False,
    )
    x_einvoice_cancel_date = fields.Datetime("E-Invoice Cancel Date",copy=False)
    x_einvoice_cancel_response = fields.Json("E-Invoice Cancel Full Response",copy=False)

    x_einvoice_verified_status = fields.Selection([
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('not_registered', 'Not Registered')
    ], string="E-Invoice Verification Status", copy=False)
    x_einvoice_verified_details = fields.Json(string="E-Invoice Verification Full Response", copy=False)

    client_latitude = fields.Float(
        string="Client Latitude",
        digits=(10, 7),
        copy=False,
        help="Client GPS latitude at the time of invoice processing.",
    )
    client_longitude = fields.Float(
        string="Client Longitude",
        digits=(10, 7),
        copy=False,
        help="Client GPS longitude at the time of invoice processing.",
    )
    is_in_configured_location = fields.Boolean(
        string="In Configured Geo-Location",
        compute="_compute_is_in_configured_location",
        store=True,
        copy=False,
        help="Indicates whether the client's location is within the configured geo-fencing boundary.",
    )

    company_einvoice_zone = fields.Char(
        string="Company Zone (E-Invoice)",
        compute="_compute_company_einvoice_zone_wereda",
        help="Zone from company's E-Invoice config, for reports.",
    )
    company_einvoice_wereda = fields.Char(
        string="Company Wereda (E-Invoice)",
        compute="_compute_company_einvoice_zone_wereda",
        help="Wereda from company's E-Invoice config, for reports.",
    )

    x_einvoice_cn_irn = fields.Char("E-Invoice Credit/Debit IRN", copy=False, index=True)
    x_einvoice_cn_status = fields.Selection(
        [("A", "Active"), ("C", "Cancelled")],
        string="E-Invoice Credit/Debit Status",
        copy=False,)
    x_einvoice_cn_ack_date = fields.Datetime("E-Invoice Credit/Debit Acknowledged At", copy=False)
    x_einvoice_cn_document_number = fields.Char("E-Invoice Credit/Debit Document Number", copy=False)
    x_einvoice_cn_signed_invoice = fields.Text("Credit/Debit Signed Invoice (Base64)", copy=False)
    x_einvoice_cn_signed_qr = fields.Binary("Credit/Debit Signed QR Code (Base64)", copy=False)
    x_einvoice_cn_response_raw = fields.Json("E-Invoice Credit/Debit Full Response", copy=False)
    x_einvoice_cn_error_message = fields.Text("E-Invoice Credit/Debit Error Message", copy=False)
    
    x_einvoice_credit_irn = fields.Char("E-Invoice Credit IRN", copy=False, index=True)
    x_einvoice_credit_status = fields.Selection(
        [("A", "Active"), ("C", "Cancelled")],
        string="E-Invoice Credit Status",
        copy=False,
    )
    x_einvoice_credit_ack_date = fields.Datetime("E-Invoice Credit Acknowledged At", copy=False)
    x_einvoice_credit_document_number = fields.Char("E-Invoice Credit Document Number", copy=False)
    x_einvoice_credit_signed_invoice = fields.Text("Credit Signed Invoice (Base64)", copy=False)
    x_einvoice_credit_signed_qr = fields.Binary("Credit Signed QR Code (Base64)", copy=False)
    x_einvoice_credit_response_raw = fields.Json("E-Invoice Credit Full Response", copy=False)
    x_einvoice_credit_error_message = fields.Text("E-Invoice Credit Error Message", copy=False)

    x_einvoice_debit_irn = fields.Char("E-Invoice Debit IRN", copy=False, index=True)
    x_einvoice_debit_status = fields.Selection(
        [("A", "Active"), ("C", "Cancelled")],
        string="E-Invoice Debit Status",
        copy=False,
    )
    x_einvoice_debit_ack_date = fields.Datetime("E-Invoice Debit Acknowledged At", copy=False)
    x_einvoice_debit_document_number = fields.Char("E-Invoice Debit Document Number", copy=False)
    x_einvoice_debit_signed_invoice = fields.Text("Debit Signed Invoice (Base64)", copy=False)
    x_einvoice_debit_signed_qr = fields.Binary("Debit Signed QR Code (Base64)", copy=False)
    x_einvoice_debit_response_raw = fields.Json("E-Invoice Debit Full Response", copy=False)
    x_einvoice_debit_error_message = fields.Text("E-Invoice Debit Error Message", copy=False)

    x_total_discount_amount = fields.Monetary(
        string="Total discount",
        compute="_compute_x_total_discount_amount",
        store=True,
        currency_field="currency_id",
        help="Sum of line discount amounts (quantity × unit price × discount %) for product lines.",)
    x_total_excise_on_gross = fields.Monetary(
        string="Total excise (on gross)",
        compute="_compute_x_total_excise_on_gross",
        store=True,
        currency_field="currency_id",
        help="Sum of excise tax computed on gross per line (x_excise_tax_value_line). Used in invoice totals display.",)

    credit_note_count = fields.Integer(
        string='Credit Note Count', 
        compute='_compute_credit_note_count'
    )

    def _compute_credit_note_count(self):
        for move in self:
            move.credit_note_count = self.search_count([
                ('reversed_entry_id', '=', move.id),
                ('move_type', '=', 'out_refund')
            ])

    def action_view_credit_notes(self):
        self.ensure_one()
        return {
            'name': 'Credit Notes',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('reversed_entry_id', '=', self.id), ('move_type', '=', 'out_refund')],
            'context': {
                'default_move_type': 'out_refund',
                'default_reversed_entry_id': self.id,
            },
        }
    
    @api.depends("invoice_line_ids", "invoice_line_ids.x_excise_tax_value_line", "invoice_line_ids.display_type", "currency_id")
    def _compute_x_total_excise_on_gross(self):
        for move in self:
            if not move.is_invoice(include_receipts=True):
                move.x_total_excise_on_gross = 0.0
                continue
            total = sum(
                line.x_excise_tax_value_line or 0.0
                for line in move.invoice_line_ids
                if line.display_type == "product"
            )
            move.x_total_excise_on_gross = move.currency_id.round(total) if move.currency_id else round(total, 2)

    @api.depends("invoice_line_ids.currency_rate","invoice_line_ids.tax_base_amount","invoice_line_ids.tax_line_id","invoice_line_ids.price_total","invoice_line_ids.price_subtotal",
        "invoice_payment_term_id","partner_id","currency_id","invoice_line_ids.x_excise_tax_value_line",)
    def _compute_tax_totals(self):
        super()._compute_tax_totals()
        for move in self:
            if not move.tax_totals or not move.is_invoice(include_receipts=True):
                continue
            sign = -1.0 if move.move_type in ("out_refund", "in_refund") else 1.0
            new_excise_currency = sign * (move.x_total_excise_on_gross or 0.0)
            if move.currency_id == move.company_currency_id:
                new_excise_company = new_excise_currency
            else:
                converted = move.currency_id._convert(
                    move.x_total_excise_on_gross or 0.0,
                    move.company_currency_id,
                    move.company_id,
                    move.invoice_date or fields.Date.context_today(self),)
                new_excise_company = sign * converted
            old_excise_currency = 0.0
            old_excise_company = 0.0
            excise_found = False
            for subtotal in (move.tax_totals.get("subtotals") or []):
                for tax_group in subtotal.get("tax_groups") or []:
                    if (tax_group.get("group_name") or "").strip().lower() != "excise":
                        continue
                    excise_found = True
                    old_excise_currency = tax_group.get("tax_amount_currency") or 0.0
                    old_excise_company = tax_group.get("tax_amount") or 0.0
                    tax_group["tax_amount_currency"] = new_excise_currency
                    tax_group["tax_amount"] = new_excise_company
                    subtotal["tax_amount_currency"] = (subtotal.get("tax_amount_currency") or 0.0) - old_excise_currency + new_excise_currency
                    subtotal["tax_amount"] = (subtotal.get("tax_amount") or 0.0) - old_excise_company + new_excise_company
                    break
                if excise_found:
                    break
            if not excise_found:
                continue
            delta_currency = new_excise_currency - old_excise_currency
            delta_company = new_excise_company - old_excise_company
            move.tax_totals["tax_amount_currency"] = (move.tax_totals.get("tax_amount_currency") or 0.0) + delta_currency
            move.tax_totals["tax_amount"] = (move.tax_totals.get("tax_amount") or 0.0) + delta_company
            move.tax_totals["total_amount_currency"] = (move.tax_totals.get("total_amount_currency") or 0.0) + delta_currency
            move.tax_totals["total_amount"] = (move.tax_totals.get("total_amount") or 0.0) + delta_company
            if not (move.x_total_excise_on_gross and move.x_total_excise_on_gross != 0.0):
                continue
            # base_currency = (move.tax_totals.get("base_amount_currency") or 0.0) + (move.x_total_excise_on_gross or 0.0)
            # base_company = (move.tax_totals.get("base_amount") or 0.0)
            # if move.currency_id != move.company_currency_id:
            #     base_company = move.currency_id._convert(
            #         move.x_total_excise_on_gross or 0.0,
            #         move.company_currency_id,
            #         move.company_id,
            #         move.invoice_date or fields.Date.context_today(self),
            #     ) + (move.tax_totals.get("base_amount") or 0.0)
            # else:
            #     base_company = base_currency
            # vat_rate = 0.15
            # new_vat_currency = sign * (vat_rate * base_currency)
            # new_vat_company = sign * (vat_rate * base_company)
            vat_target_currency = move._compute_target_vat15_amount_currency()
            new_vat_currency = sign * vat_target_currency
            if move.currency_id == move.company_currency_id:
                new_vat_company = new_vat_currency
            else:
                new_vat_company = sign * move.currency_id._convert(
                    vat_target_currency,
                    move.company_currency_id,
                    move.company_id,
                    move.invoice_date or fields.Date.context_today(self),
                )
            old_vat_currency = 0.0
            old_vat_company = 0.0
            vat_found = False
            for subtotal in (move.tax_totals.get("subtotals") or []):
                for tax_group in subtotal.get("tax_groups") or []:
                    gname = (tax_group.get("group_name") or "").strip().lower()
                    if "vat" not in gname or "withhold" in gname:
                        continue
                    vat_found = True
                    old_vat_currency = tax_group.get("tax_amount_currency") or 0.0
                    old_vat_company = tax_group.get("tax_amount") or 0.0
                    tax_group["tax_amount_currency"] = new_vat_currency
                    tax_group["tax_amount"] = new_vat_company
                    subtotal["tax_amount_currency"] = (subtotal.get("tax_amount_currency") or 0.0) - old_vat_currency + new_vat_currency
                    subtotal["tax_amount"] = (subtotal.get("tax_amount") or 0.0) - old_vat_company + new_vat_company
                    break
                if vat_found:
                    break
            if vat_found:
                delta_vat_currency = new_vat_currency - old_vat_currency
                delta_vat_company = new_vat_company - old_vat_company
                move.tax_totals["tax_amount_currency"] = (move.tax_totals.get("tax_amount_currency") or 0.0) + delta_vat_currency
                move.tax_totals["tax_amount"] = (move.tax_totals.get("tax_amount") or 0.0) + delta_vat_company
                move.tax_totals["total_amount_currency"] = (move.tax_totals.get("total_amount_currency") or 0.0) + delta_vat_currency
                move.tax_totals["total_amount"] = (move.tax_totals.get("total_amount") or 0.0) + delta_vat_company

    def _is_excise_tax(self, tax):
        return bool(
            tax
            and (
                "excise" in (tax.name or "").strip().lower()
                or "excise" in (tax.tax_group_id.name or "").strip().lower()
            )
        )

    def _is_vat15_tax(self, tax):
        if not tax:
            return False
        if self._is_excise_tax(tax):
            return False
        if "withhold" in (tax.name or "").strip().lower() or "wht" in (tax.name or "").strip().lower():
            return False
        if "withhold" in (tax.tax_group_id.name or "").strip().lower():
            return False
        return float(tax.amount or 0.0) == 15.0

    def _compute_target_vat15_amount_currency(self):
        # VAT applies on pre-tax + excise
        self.ensure_one()
        if not self.is_invoice(include_receipts=True):
            return 0.0
        currency = self.currency_id
        target_vat = 0.0
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            discount_amount = gross * ((line.discount or 0.0) / 100.0)
            pre_tax = gross - discount_amount
            has_excise = any(self._is_excise_tax(tax) for tax in line.tax_ids)
            has_vat15 = any(self._is_vat15_tax(tax) for tax in line.tax_ids)
            if not has_vat15:
                continue
            line_excise = line.x_excise_tax_value_line or 0.0
            vat_base = (pre_tax + line_excise) if has_excise else pre_tax
            line_vat = vat_base * 0.15
            target_vat += currency.round(line_vat) if currency else round(line_vat, 2)
        return currency.round(target_vat) if currency else round(target_vat, 2)

    @contextmanager
    def _sync_tax_lines(self, container):
        with super()._sync_tax_lines(container):
            yield
        for move in container["records"]:
            if move.state != "draft" or not move.is_invoice(include_receipts=True):
                continue
            move._apply_excise_on_gross_to_tax_lines()
            move._apply_vat_on_pretax_plus_excise()

    def _apply_vat_on_pretax_plus_excise(self):
        self.ensure_one()
        if not (self.x_total_excise_on_gross and self.x_total_excise_on_gross != 0.0):
            return
        vat_lines = self.line_ids.filtered(
            lambda l: l.tax_line_id
            and l.tax_line_id.tax_group_id
            and "vat" in (l.tax_line_id.tax_group_id.name or "").strip().lower()
            and "withhold" not in (l.tax_line_id.tax_group_id.name or "").strip().lower()
        )
        if not vat_lines:
            return
        total_vat_target = self._compute_target_vat15_amount_currency()
        sign = 1.0 if self.move_type in ("out_refund", "in_refund") else -1.0
        amount_currency_target = sign * total_vat_target
        if self.currency_id == self.company_currency_id:
            balance_target = amount_currency_target
        else:
            balance_target = sign * self.currency_id._convert(
                total_vat_target,
                self.company_currency_id,
                self.company_id,
                self.invoice_date or fields.Date.context_today(self),
            )
        total_curr = sum(vat_lines.mapped("amount_currency"))
        total_bal = sum(vat_lines.mapped("balance"))
        if abs(total_curr) < 1e-9 and abs(total_bal) < 1e-9:
            if total_vat_target and vat_lines:
                vat_lines[0].write({
                    "amount_currency": amount_currency_target,
                    "balance": balance_target,
                })
                for line in vat_lines[1:]:
                    line.write({"amount_currency": 0.0, "balance": 0.0})
            return
        factor_curr = amount_currency_target / total_curr if total_curr else 0.0
        factor_bal = balance_target / total_bal if total_bal else 0.0
        for i, line in enumerate(vat_lines):
            if i == 0:
                continue
            new_curr = line.amount_currency * factor_curr
            new_bal = line.balance * factor_bal
            line.write({
                "amount_currency": self.currency_id.round(new_curr) if self.currency_id else round(new_curr, 2),
                "balance": self.company_currency_id.round(new_bal) if self.company_currency_id else round(new_bal, 2),
            })
        first = vat_lines[0]
        remainder_curr = amount_currency_target - sum(l.amount_currency for l in vat_lines[1:])
        remainder_bal = balance_target - sum(l.balance for l in vat_lines[1:])
        first.write({
            "amount_currency": self.currency_id.round(remainder_curr) if self.currency_id else round(remainder_curr, 2),
            "balance": self.company_currency_id.round(remainder_bal) if self.company_currency_id else round(remainder_bal, 2),
        })

    def _apply_excise_on_gross_to_tax_lines(self):
        self.ensure_one()
        excise_lines = self.line_ids.filtered(
            lambda l: l.tax_line_id
            and (l.tax_line_id.tax_group_id.name or "").strip().lower() == "excise"
        )
        if not excise_lines:
            return
        total_excise = self.x_total_excise_on_gross or 0.0
        sign = 1.0 if self.move_type in ("out_refund", "in_refund") else -1.0
        amount_currency_target = sign * total_excise
        if self.currency_id == self.company_currency_id:
            balance_target = amount_currency_target
        else:
            balance_target = sign * self.currency_id._convert(
                total_excise,
                self.company_currency_id,
                self.company_id,
                self.invoice_date or fields.Date.context_today(self),
            )
        total_curr = sum(excise_lines.mapped("amount_currency"))
        total_bal = sum(excise_lines.mapped("balance"))
        if abs(total_curr) < 1e-9 and abs(total_bal) < 1e-9:
            if total_excise and excise_lines:
                excise_lines[0].write({
                    "amount_currency": amount_currency_target,
                    "balance": balance_target,})
                for line in excise_lines[1:]:
                    line.write({"amount_currency": 0.0, "balance": 0.0})
            return
        factor_curr = amount_currency_target / total_curr if total_curr else 0.0
        factor_bal = balance_target / total_bal if total_bal else 0.0
        for i, line in enumerate(excise_lines):
            if i == 0:
                continue
            new_curr = line.amount_currency * factor_curr
            new_bal = line.balance * factor_bal
            line.write({
                "amount_currency": self.currency_id.round(new_curr) if self.currency_id else round(new_curr, 2),
                "balance": self.company_currency_id.round(new_bal) if self.company_currency_id else round(new_bal, 2),
            })
        first = excise_lines[0]
        remainder_curr = amount_currency_target - sum(l.amount_currency for l in excise_lines[1:])
        remainder_bal = balance_target - sum(l.balance for l in excise_lines[1:])
        first.write({
            "amount_currency": self.currency_id.round(remainder_curr) if self.currency_id else round(remainder_curr, 2),
            "balance": self.company_currency_id.round(remainder_bal) if self.company_currency_id else round(remainder_bal, 2),
        })

    @api.depends("invoice_line_ids", "invoice_line_ids.quantity", "invoice_line_ids.price_unit", "invoice_line_ids.discount", "invoice_line_ids.display_type", "currency_id")
    def _compute_x_total_discount_amount(self):
        for move in self:
            if not move.is_invoice(include_receipts=True):
                move.x_total_discount_amount = 0.0
                continue
            total = 0.0
            for line in move.invoice_line_ids:
                if line.display_type != "product":
                    continue
                total += line.quantity * line.price_unit * (line.discount or 0.0) / 100.0
            move.x_total_discount_amount = move.currency_id.round(total) if move.currency_id else round(total, 2)

    @api.depends("company_id")
    def _compute_company_einvoice_zone_wereda(self):
        for move in self:
            config = self.env["einvoice.config"].sudo().search(
                [("company_id", "=", move.company_id.id), ("active", "=", True)],
                limit=1,
            )
            move.company_einvoice_zone = config.zone if config else ""
            move.company_einvoice_wereda = config.wereda if config else ""

    x_einvoice_receipt_status = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('error', 'Error'),
        ('pending', 'Pending'),
    ], string="E-Invoice Receipt Status", default='draft')
    x_einvoice_receipt_id = fields.Char(string="E-Invoice Receipt ID")
    x_einvoice_receipt_status_code = fields.Char(string="E-Invoice Receipt Status Code")
    x_einvoice_receipt_rrn = fields.Char(string="E-Invoice Receipt RRN")
    x_einvoice_receipt_qr = fields.Binary(string="E-Invoice Receipt QR Code")
    x_einvoice_receipt_response_raw = fields.Json(string="E-Invoice Receipt Raw Response")
    x_einvoice_sales_paid_total = fields.Monetary(
        string="E-Invoice Sales Paid Total",currency_field="currency_id",copy=False,
        help="Running total of amounts already sent to EIMS via sales receipts for this invoice. Used to compute incremental partial receipts.",)

    x_withholding_external_id = fields.Char("Withholding External ID", copy=False)
    x_withholding_status = fields.Char("Withholding Status", copy=False)
    x_withholding_rrn = fields.Char("Withholding RRN", copy=False)
    x_withholding_invoice_irn = fields.Char("Withholding Invoice IRN", copy=False)
    x_withholding_qr = fields.Binary("Withholding QR Code", copy=False)

    x_einvoice_bulk_conversation_id = fields.Char(string="E-Invoice Bulk Conversation ID",index=True,)
    x_einvoice_bulk_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],default="pending",string="E-Invoice Bulk Status",)
    x_einvoice_bulk_error = fields.Text(string="E-Invoice Bulk Error",)
    x_einvoice_bulk_sent_at = fields.Datetime()

    related_irn = fields.Char(
        string="Related Invoice IRN",
        help="IRN of the original invoice"
    )
    @api.onchange('reversed_entry_id')
    def _onchange_reversed_entry_id(self):
        if self.reversed_entry_id and self.move_type == 'out_refund':
            self.related_irn = self.reversed_entry_id.x_einvoice_irn

    @api.depends('partner_id')
    def _compute_buyer_fields(self):
        for move in self:
            partner = move.partner_id
            move.buyer_vat = partner.vat if partner else False
            move.buyer_phone = partner.phone if partner else False
            move.buyer_email = partner.email if partner else False

    def _inverse_buyer_vat(self):
        for move in self:
            if move.partner_id:
                move.partner_id.vat = move.buyer_vat

    def _inverse_buyer_phone(self):
        for move in self:
            if move.partner_id:
                pass
                # move.partner_id.phone = move.buyer_phone

    def _inverse_buyer_email(self):
        for move in self:
            if move.partner_id:
                move.partner_id.email = move.buyer_email

    def _ensure_einvoice_user_config(self, pending_action='send_invoice'):
        self.ensure_one()
        if not self.env.user.has_group('ethiopian_einvoice_core.group_einvoice_user'):
            return None
        if self.env.user.einvoice_config_id and self.env.user.einvoice_config_id.company_id == self.company_id:
            return None
        raise UserError(_(
            "Your user is in E-Invoice User group but has no E-Invoice system number assigned "
            "for company %s."
        ) % self.company_id.name)

    def _check_coordinates_in_geofence(self, lat, lon, config):
        if not lat or not lon or not config:
            return False
        mode = config.geo_fencing_mode
        if mode == 'radius':
            ref_lat = config.geo_fencing_latitude
            ref_lon = config.geo_fencing_longitude
            radius = config.geo_fencing_radius
            if not ref_lat or not ref_lon:
                return True
            import math
            R = 6371e3  # metres
            phi1 = math.radians(lat)
            phi2 = math.radians(ref_lat)
            delta_phi = math.radians(ref_lat - lat)
            delta_lambda = math.radians(ref_lon - lon)

            a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = R * c
            return distance <= radius
        elif mode == 'country':
            geojson_str = config.geo_fencing_country_geojson
            if not geojson_str:
                return True
            import json
            try:
                data = json.loads(geojson_str)
            except Exception:
                return False

            def point_in_polygon(point, polygon):
                x, y = point
                inside = False
                n = len(polygon)
                p1x, p1y = polygon[0]
                for i in range(1, n + 1):
                    p2x, p2y = polygon[i % n]
                    if min(p1y, p2y) < y <= max(p1y, p2y) and x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
                    p1x, p1y = p2x, p2y
                return inside

            features = data.get('features', [data]) if data.get('type') == 'FeatureCollection' else [data]
            for feature in features:
                geom = feature.get('geometry', {})
                geom_type = geom.get('type')
                coords = geom.get('coordinates', [])
                if geom_type == 'Polygon':
                    for poly in coords:
                        if point_in_polygon((lon, lat), poly):
                            return True
                elif geom_type == 'MultiPolygon':
                    for multi in coords:
                        for poly in multi:
                            if point_in_polygon((lon, lat), poly):
                                return True
            return False
        return True

    @api.depends('client_latitude', 'client_longitude', 'company_id')
    def _compute_is_in_configured_location(self):
        for move in self:
            if not move.client_latitude and not move.client_longitude:
                move.is_in_configured_location = False
                continue
            config = move.einvoice_config_id or self.env.user.einvoice_config_id or self.env['einvoice.config'].sudo().search([
                ('company_id', '=', move.company_id.id),
                ('active', '=', True),
            ], limit=1)
            if not config:
                move.is_in_configured_location = False
                continue
            move.is_in_configured_location = move._check_coordinates_in_geofence(
                move.client_latitude, move.client_longitude, config
            )

    def _validate_geolocation(self, config):
        lat = self.env.context.get('geo_fencing_latitude') or self.client_latitude
        lon = self.env.context.get('geo_fencing_longitude') or self.client_longitude
        if not lat or not lon:
            raise UserError(_("Could not obtain user location. Location permission is required for this action."))
        
        mode = config.geo_fencing_mode
        if mode == 'radius':
            ref_lat = config.geo_fencing_latitude
            ref_lon = config.geo_fencing_longitude
            radius = config.geo_fencing_radius
            if not ref_lat or not ref_lon:
                return 
            
            import math
            R = 6371e3 # metres
            phi1 = math.radians(lat)
            phi2 = math.radians(ref_lat)
            delta_phi = math.radians(ref_lat - lat)
            delta_lambda = math.radians(ref_lon - lon)

            a = math.sin(delta_phi/2.0) * math.sin(delta_phi/2.0) + \
                math.cos(phi1) * math.cos(phi2) * \
                math.sin(delta_lambda/2.0) * math.sin(delta_lambda/2.0)
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance = R * c
            
            if distance > radius:
                raise UserError(_("You are outside the allowed radius (%.2fm away, max %.2fm). Action blocked.") % (distance, radius))
        elif mode == 'country':
            if not self._check_coordinates_in_geofence(lat, lon, config):
                raise UserError(_("You are outside the allowed country boundary. Action blocked."))

    def action_send_to_einvoice(self):
        self.ensure_one()
        if self.move_type != 'out_invoice':
            raise UserError(_("Only customer invoices can be sent to E-Invoice."))
        if self.einvoice_status in ('sent', 'registered'):
            raise UserError(_("This invoice has already been sent."))
        config_action = self._ensure_einvoice_user_config()
        if config_action:
            return config_action
            
        return {
            'type': 'ir.actions.client',
            'tag': 'einvoice_get_location',
            'params': {
                'next_method': 'action_send_to_einvoice_with_location',
                'res_model': self._name,
                'res_id': self.id,
            }
        }

    def action_get_client_location(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'einvoice_get_location',
            'params': {
                'next_method': 'action_save_client_location',
                'res_model': self._name,
                'res_id': self.id,
            }
        }

    def action_save_client_location(self):
        self.ensure_one()
        lat = self.env.context.get('geo_fencing_latitude')
        lon = self.env.context.get('geo_fencing_longitude')
        if lat is not None and lon is not None:
            self.write({
                'client_latitude': lat,
                'client_longitude': lon,
            })
            status_text = _("within") if self.is_in_configured_location else _("outside")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Location Updated'),
                    'message': _('Client coordinates updated to (%.7f, %.7f). Location is %s the configured boundary.') % (
                        lat, lon, status_text
                    ),
                    'type': 'success' if self.is_in_configured_location else 'warning',
                    'sticky': False,
                }
            }
        return True

    def action_send_to_einvoice_with_location(self):
        self.ensure_one()
        lat = self.env.context.get('geo_fencing_latitude')
        lon = self.env.context.get('geo_fencing_longitude')
        vals = {'x_clicked_by_id': self.env.user.id}
        if lat is not None and lon is not None:
            vals.update({
                'client_latitude': lat,
                'client_longitude': lon,
            })
        self.write(vals)

        config = self.env.user.einvoice_config_id
        if config:
            self._validate_geolocation(config)
            
        return {
            'name': _('Confirm E-Invoice Submission'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.confirm.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_move_id': self.id,
            }
        }

    def action_bulk_send_to_einvoice(self):
        self.write({'x_clicked_by_id': self.env.user.id,})
        return {
            'name': _('Confirm E-Invoice Submission'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.bulk.confirm.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_move_ids': [(6, 0, self.ids)],
                # 'default_move_ids': self.env.context.get('active_ids', []),
            },
        }

    def action_cancel_einvoice(self):
        self.ensure_one()
        self.write({'x_clicked_by_id': self.env.user.id,})

        return {
            'name': _('Cancel E-Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.cancel.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_move_id': self.id,
            },
        }

    def action_verify_einvoice(self):
        self.ensure_one()
        self.write({'x_clicked_by_id': self.env.user.id,})
        
        return {
            'name': _('Verify E-Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.verify.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_move_id': self.id,
            },
        }

    # def action_sales_receipt(self):
    #     self.ensure_one()
    #     self.write({'x_clicked_by_id': self.env.user.id,})

    #     return {
    #         'name': _('Send Receipt'),
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'einvoice.receipt.wizard',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'context': {
    #             'default_move_id': self.id,
    #         },
    #     }

    def action_sales_withholding(self):
        self.ensure_one()
        if self.move_type != 'in_invoice':
            raise UserError(_("Withholding receipts can only be sent from vendor bills."))
        self.write({'x_clicked_by_id': self.env.user.id,})
        
        return {
            'name': _('Send Withholding'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.withholding.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_id': self.id,
            },
        }

    def action_send_credit_note(self):
        self.ensure_one()
        if self.move_type != 'out_refund':
            raise UserError(_("Only credit notes can be sent via Send Credit Note."))
        if self.x_einvoice_cn_irn:
            raise UserError(_("This credit note is already registered with IRN %s.") % self.x_einvoice_cn_irn)
        config_action = self._ensure_einvoice_user_config(pending_action='send_credit')
        if config_action:
            return config_action
            
        return {
            'type': 'ir.actions.client',
            'tag': 'einvoice_get_location',
            'params': {
                'next_method': 'action_send_credit_note_with_location',
                'res_model': self._name,
                'res_id': self.id,
            }
        }

    def action_send_credit_note_with_location(self):
        self.ensure_one()
        lat = self.env.context.get('geo_fencing_latitude')
        lon = self.env.context.get('geo_fencing_longitude')
        vals = {'x_clicked_by_id': self.env.user.id}
        if lat is not None and lon is not None:
            vals.update({
                'client_latitude': lat,
                'client_longitude': lon,
            })
        self.write(vals)

        config = self.env.user.einvoice_config_id
        if config:
            self._validate_geolocation(config)
            
        return {
            'name': _('Confirm Credit Note E-Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.credit.debit.confirm.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_send_debit_note(self):
        self.ensure_one()
        if self.move_type != 'out_invoice' or not getattr(self, "debit_origin_id", False):
            raise UserError(_("Only debit notes (invoices created from another invoice) can be sent via Send Debit Note."))
        if self.x_einvoice_cn_irn:
            raise UserError(_("This debit note is already registered with IRN %s.") % self.x_einvoice_cn_irn)
        config_action = self._ensure_einvoice_user_config(pending_action='send_debit')
        if config_action:
            return config_action
            
        return {
            'type': 'ir.actions.client',
            'tag': 'einvoice_get_location',
            'params': {
                'next_method': 'action_send_debit_note_with_location',
                'res_model': self._name,
                'res_id': self.id,
            }
        }

    def action_send_debit_note_with_location(self):
        self.ensure_one()
        lat = self.env.context.get('geo_fencing_latitude')
        lon = self.env.context.get('geo_fencing_longitude')
        vals = {'x_clicked_by_id': self.env.user.id}
        if lat is not None and lon is not None:
            vals.update({
                'client_latitude': lat,
                'client_longitude': lon,
            })
        self.write(vals)

        config = self.env.user.einvoice_config_id
        if config:
            self._validate_geolocation(config)
            
        return {
            'name': _('Confirm Debit Note E-Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'einvoice.credit.debit.confirm.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_register_einvoice(self):
        result = False
        for move in self:
            if move.move_type == "out_refund":
                result = move.action_send_credit_note()
            # elif move.move_type == "out_debit":
            elif move.debit_origin_id:
                result = move.action_send_debit_note()
        return result or True


    def _check_invoice_registered(self):
        self.ensure_one()
        if not self.x_einvoice_irn:
            raise UserError(_("The invoice needs to be registered first before processing the receipt."))

    def _check_sales_receipt_registered(self):
        self.ensure_one()
        self._check_invoice_registered()
        if not self.x_einvoice_receipt_rrn and not self.x_einvoice_receipt_qr:
            raise UserError(_("The invoice needs to be registered first before processing the receipt."))

    def _check_withholding_registered(self):
        self.ensure_one()
        self._check_invoice_registered()
        if not self.x_withholding_rrn and not self.x_withholding_qr:
            raise UserError(_("The invoice needs to be registered first before processing the receipt."))

    def action_print_sales_receipt(self):
        self.ensure_one()
        self._check_sales_receipt_registered()
        # return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt").report_action(self)
        return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt_payment").report_action(self)

    def action_print_withholding_receipt(self):
        self.ensure_one()
        self._check_withholding_registered()
        return self.env.ref("ethiopian_einvoice_core.action_report_withholding_receipt").report_action(self)

    def action_print_registered_einvoice(self):
        self.ensure_one()
        self._check_invoice_registered()
        return self.env.ref("ethiopian_einvoice_core.action_report_registered_einvoice").report_action(self)

    def action_sms_sales_receipt(self):
        self.ensure_one()
        self._check_sales_receipt_registered()
        service = self.env['einvoice.invoice.service']
        attachment, download_url = service._generate_receipt_pdf_and_attachment(self, "Sales Receipt")
        # Send SMS
        phone = self.partner_id.phone or self.buyer_phone
        if phone:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_url = base_url + download_url if download_url else ''
            message = "Your Sales Receipt for %s is ready. Download: %s" % (self.name, full_url)
            service.send_sms(phone, message)
        else:
            _logger.warning("No phone number for partner %s, skipping SMS", self.partner_id.name)
        # Also return the PDF report action
        # return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt").report_action(self)
        return self.env.ref("ethiopian_einvoice_core.action_report_sales_receipt_payment").report_action(self)

    def action_sms_withholding_receipt(self):
        self.ensure_one()
        self._check_withholding_registered()
        service = self.env['einvoice.invoice.service']
        attachment, download_url = service._generate_receipt_pdf_and_attachment(self, "Withholding Receipt")
        # Send SMS
        phone = self.partner_id.phone or self.buyer_phone
        if phone:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            full_url = base_url + download_url if download_url else ''
            message = "Your Withholding Receipt for %s is ready. Download: %s" % (self.name, full_url)
            service.send_sms(phone, message)
        else:
            _logger.warning("No phone number for partner %s, skipping SMS", self.partner_id.name)
        # Also return the PDF report action
        return self.env.ref("ethiopian_einvoice_core.action_report_withholding_receipt").report_action(self)

    def action_send_sales_receipt_email(self):
        self.ensure_one()
        self._check_sales_receipt_registered()
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        service = self.env['einvoice.invoice.service']
        attachment, _url = service._generate_receipt_pdf_and_attachment(self, "Sales Receipt")
        service._send_receipt_email(
            self,
            attachment,
            "ethiopian_einvoice_core.email_template_sales_receipt")
        return True

    def action_send_withholding_receipt_email(self):
        self.ensure_one()
        self._check_withholding_registered()
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        service = self.env['einvoice.invoice.service']
        attachment, _url = service._generate_receipt_pdf_and_attachment(self, "Withholding Receipt")
        service._send_receipt_email(
            self,
            attachment,
            "ethiopian_einvoice_core.email_template_sales_receipt")
        return True

    def _check_invoice_registered_for_notification(self):
        self.ensure_one()
        if not self.x_einvoice_irn:
            raise UserError(_("Invoice is not yet registered. No IRN to send."))

    def _check_cancelled_for_notification(self):
        self.ensure_one()
        if self.x_einvoice_cancel_status != "cancelled":
            raise UserError(_("Invoice is not cancelled. Nothing to send."))

    def action_sms_invoice_registration(self):
        self.ensure_one()
        self._check_invoice_registered_for_notification()
        # if self.move_type in ("out_refund", "out_debit"):
        if self.move_type in ("out_refund") or self.debit_origin_id:
            raise UserError(_("Use 'SMS Credit Note' for credit/debit notes."))
        self.env["einvoice.invoice.service"]._send_invoice_registration_sms(self)
        return True

    def action_email_invoice_registration(self):
        self.ensure_one()
        self._check_invoice_registered_for_notification()
        # if self.move_type in ("out_refund", "out_debit"):
        if self.move_type in ("out_refund") or self.debit_origin_id:
            raise UserError(_("Use 'Email Credit Note' for credit/debit notes."))
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        self.env["einvoice.invoice.service"]._send_invoice_registration_email(self)
        return True

    def action_sms_cancellation(self):
        self.ensure_one()
        self._check_cancelled_for_notification()
        self.env["einvoice.invoice.service"]._send_cancellation_sms(self)
        return True

    def action_email_cancellation(self):
        self.ensure_one()
        self._check_cancelled_for_notification()
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        self.env["einvoice.invoice.service"]._send_cancellation_email(self)
        return True

    def _check_credit_note_registered_for_notification(self):
        self.ensure_one()
        if not self.x_einvoice_cn_irn:
            raise UserError(_("Credit/Debit note is not yet registered. No IRN to send."))

    def action_sms_credit_note(self):
        self.ensure_one()
        # if self.move_type not in ("out_refund", "out_debit"):
        if self.move_type in ("out_refund") or self.debit_origin_id:
            raise UserError(_("Only for credit or debit notes."))
        self._check_credit_note_registered_for_notification()
        self.env["einvoice.invoice.service"]._send_credit_note_sms(self)
        return True

    def action_sms_debit_note(self):
        self.ensure_one()
        # if self.move_type not in ("out_refund", "out_debit"):
        #     raise UserError(_("Only for credit or debit notes."))
        self._check_credit_note_registered_for_notification()
        self.env["einvoice.invoice.service"]._send_debit_note_sms(self)
        return True

    def action_email_credit_note(self):
        self.ensure_one()
        # if self.move_type not in ("out_refund", "out_debit"):
        if self.move_type in ("out_refund") or self.debit_origin_id:
            raise UserError(_("Only for credit or debit notes."))
        self._check_credit_note_registered_for_notification()
        if not self.partner_id.email:
            raise UserError(_("Customer has no email address."))
        self.env["einvoice.invoice.service"]._send_credit_note_email(self)
        return True

    reversal_move_id = fields.Many2one('account.move', string="Original Invoice", copy=False)
    related_credit_debit_ids = fields.One2many(
        'account.move', 'reversal_move_id', string="Related Credit/Debit Notes"
    )

    @api.depends("reversal_move_id", "reversed_entry_id", "debit_origin_id")
    def _compute_related_invoice(self):
        for move in self:
            move.related_invoice_id = move.reversal_move_id or move.reversed_entry_id or move.debit_origin_id

    related_invoice_id = fields.Many2one(
        'account.move', string="Related Original Invoice", compute="_compute_related_invoice", store=True
    )

    def action_view_related_credit_debit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Related Credit/Debit Notes',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('reversal_move_id', '=', self.id)],
        }

    def action_view_original_invoice(self):
        self.ensure_one()
        original_move = self.reversal_move_id or self.reversed_entry_id or self.debit_origin_id
        if not original_move:
            raise UserError(_("No original invoice linked."))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Original Invoice',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': original_move.id,
        }

    @api.constrains('x_einvoice_irn', 'x_einvoice_credit_irn', 'x_einvoice_debit_irn', 'x_withholding_invoice_irn')
    def _check_irn_uniqueness(self):
        irn_fields = [
            ('x_einvoice_irn', 'E-Invoice IRN'),
            ('x_einvoice_credit_irn', 'Credit IRN'),
            ('x_einvoice_debit_irn', 'Debit IRN'),
            ('x_withholding_invoice_irn', 'Withholding IRN'),
        ]
        for move in self:
            for field_name, label in irn_fields:
                val = getattr(move, field_name, None)
                if not val:
                    continue
                duplicate = self.env['account.move'].sudo().search([
                    (field_name, '=', val),
                    ('id', '!=', move.id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "%(label)s '%(irn)s' already exists on invoice %(name)s. "
                        "IRN values must be unique across all invoices."
                    ) % {'label': label, 'irn': val, 'name': duplicate.name})

    @api.constrains('invoice_line_ids')
    def _check_duplicate_product_lines(self):
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
                continue
            product_lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type in (False, 'product') and l.product_id
            )
            seen = set()
            for line in product_lines:
                pid = line.product_id.id
                if pid in seen:
                    raise ValidationError(_(
                        "Duplicate product '%s' found in invoice lines. "
                        "Each product may only appear once per invoice. "
                        "Please adjust the quantity on the existing line instead."
                    ) % line.product_id.display_name)
                seen.add(pid)

    def get_invoice2_pdf_totals(self):
        self.ensure_one()
        currency = self.currency_id
        lines = self.invoice_line_ids.filtered(lambda l: l.display_type in (False, "product"))
        total_line_gross = 0.0
        discount_total = 0.0
        excise_monetary_sum = 0.0
        vat15_taxable = 0.0
        vat15_tax = 0.0
        non_taxable = 0.0
        withholding_total = 0.0

        def _non_taxable_line_subtotal(line):
            taxes = line.tax_ids.filtered(
                lambda tx: "excise" not in (tx.name or "").lower()
                and "excise" not in (tx.tax_group_id.name or "").lower()
            )
            if not line.tax_ids:
                return line.price_subtotal or 0.0
            if taxes and all(
                (t.name or "").strip().lower() in ("vat 0%", "0%", "0% exempt", "vat0")
                or (t.name or "").replace(" ", "").lower() in ("vat0%", "0%", "0%exempt", "vat0")
                or "EXEMPT" in (t.name or "").upper()
                for t in taxes
            ):
                return line.price_subtotal or 0.0
            return 0.0

        def _is_excise_tax(tax):
            return ("excise" in (tax.name or "").lower()) or ("excise" in (tax.tax_group_id.name or "").lower())

        def _is_wht_tax(tax):
            amt = float(tax.amount or 0.0)
            return (
                "withhold" in (tax.name or "").lower()
                or "wht" in (tax.name or "").lower()
                or amt in (2.0, 3.0, -2.0, -3.0, 30.0, -30.0)
            )

        def _is_b2g_vat_wht_tax(tax):
            return float(tax.amount or 0.0) == -7.5

        def _is_vat15_tax(tax):
            return (
                float(tax.amount or 0.0) == 15.0
                and not _is_excise_tax(tax)
                and not _is_wht_tax(tax))

        for line in lines:
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            total_line_gross += gross
            disc = gross * ((line.discount or 0.0) / 100.0)
            discount_total += disc
            pre_tax = gross - disc
            exc_amt = line.x_excise_tax_value_line or 0.0
            excise_monetary_sum += exc_amt

            has_excise = any(_is_excise_tax(t) for t in line.tax_ids)
            has_vat15 = any(_is_vat15_tax(t) for t in line.tax_ids)

            if has_vat15:
                base = (pre_tax + exc_amt) if has_excise else pre_tax
                vat15_taxable += base
                if has_excise:
                    vat15_tax += base * 0.15
                else:
                    vat15_tax += pre_tax * 0.15

            non_taxable += _non_taxable_line_subtotal(line)

            for t in line.tax_ids:
                if not _is_wht_tax(t):
                    continue
                if t.amount_type == "percent":
                    withholding_total += pre_tax * (t.amount or 0.0) / 100.0
                elif t.amount_type == "fixed":
                    withholding_total += (t.amount or 0.0) * (line.quantity or 0.0)

        try:
            service_totals = self.env["einvoice.invoice.service"]._compute_einvoice_totals(self)
            withholding_total = float(service_totals.get("total_wht", 0.0))
        except Exception:
            pass

        # B2G VAT withholding: aggregate absolute value of -7.5 tax across all lines
        b2g_vat_withhold_total = 0.0
        for line in lines:
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            disc = gross * ((line.discount or 0.0) / 100.0)
            pre_tax = gross - disc
            for t in line.tax_ids:
                if _is_b2g_vat_wht_tax(t):
                    if t.amount_type == "percent":
                        b2g_vat_withhold_total += abs(pre_tax * (t.amount or 0.0) / 100.0)
                    elif t.amount_type == "fixed":
                        b2g_vat_withhold_total += abs((t.amount or 0.0) * (line.quantity or 0.0))

        round2 = lambda x: currency.round(x) if currency else round(x, 2)
        return {
            "total_line_gross_extended": round2(total_line_gross),
            "excise_tax_total": round2(excise_monetary_sum),
            "discount_total": round2(discount_total),
            "vat15_taxable_total": round2(vat15_taxable),
            "vat15_tax_amount": round2(vat15_tax),
            "non_taxable_total": round2(non_taxable),
            "withholding_total": round2(withholding_total),
            "b2g_vat_withhold_total": round2(b2g_vat_withhold_total),
            "total_including_tax": round2(self.amount_total or 0.0) + round2(b2g_vat_withhold_total or 0.0),
        }

    def get_invoice2_reference_irn(self):
        self.ensure_one()
        orig = self.related_invoice_id
        if orig:
            return (orig.x_einvoice_irn or orig.x_einvoice_receipt_rrn or "").strip()
        return (self.x_einvoice_irn or self.x_einvoice_receipt_rrn or "").strip()
    # @api.constrains('re_einvoice_reason')
    # def _check_reason_required(self):
    #     for move in self:
    #         if move.move_type == 'out_refund' and not move.re_einvoice_reason:
    #             raise UserError(_("Cancellation Reason is required for Credit Notes."))


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    re_einvoice_reason = fields.Selection([
        ("1", "Duplicate"),
        ("2", "Data Entry Mistake"),
        ("3", "Order Canceled"),
        ("4", "Others"),], string="Reason", required=True)
    reason = fields.Char(string="Reason for Credit Note")

    def _prepare_default_reversal(self, move):
        res = super()._prepare_default_reversal(move)
        if self.re_einvoice_reason and self.move_type.endswith('_refund'):
            res['re_einvoice_reason'] = self.re_einvoice_reason
        return res

    def _prepare_reverse_moves(self, move):
        vals = super()._prepare_reverse_moves(move)
        if self.reason and self.move_type.endswith('_refund'):
            vals['reason'] = self.reason
        return vals

