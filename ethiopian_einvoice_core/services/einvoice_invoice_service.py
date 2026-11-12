import base64
import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import requests
import pprint

from odoo import _, api, fields, models
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

TIN_REGEX = r"^\d{10}$" 
DATE_REGEX = r"^\d{2}-\d{2}-\d{4}T\d{2}:\d{2}:\d{2}$" 
EMAIL_REGEX = r"^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$"
PHONE_REGEX = r"^\+?[0-9]{6,20}$"

class EinvoiceInvoiceService(models.AbstractModel):
    _name = 'einvoice.invoice.service'
    _description = 'E-Invoice Invoice Service'

    def _validate_payload(self, payload):
        if not re.match(TIN_REGEX, payload['SellerDetails']['Tin']):
            raise UserError(_("Invalid Seller TIN format"))
        buyer_tin = payload['BuyerDetails'].get('Tin')
        if buyer_tin and not re.match(TIN_REGEX, buyer_tin):
            raise UserError(_("Invalid Buyer TIN format"))
        if not re.match(DATE_REGEX, payload['DocumentDetails']['Date']):
            raise UserError(_("Invalid invoice date format"))
        for party in ['BuyerDetails', 'SellerDetails']:
            email = payload[party].get('Email')
            if email and not re.match(EMAIL_REGEX, email):
                raise UserError(_(f"{party} Email is invalid"))
        for party in ['BuyerDetails', 'SellerDetails']:
            phone = payload[party].get('Phone')
            if phone and not re.match(PHONE_REGEX, phone):
                raise UserError(_(f"{party} Phone is invalid"))
        required_seller_fields = ['Region', 'Wereda', 'VatNumber']
        for field in required_seller_fields:
            if field not in payload['SellerDetails']:
                raise UserError(_(f"SellerDetails.{field} is required"))
        if 'ItemList' not in payload or not payload['ItemList']:
            raise UserError(_("Invoice must have at least one item"))
        for idx, item in enumerate(payload['ItemList'], start=1):
            if item['Quantity'] <= 0:
                raise UserError(_(f"Item {idx}: Quantity must be greater than zero"))
            if item.get('NatureOfSupplies', '').lower() not in ['goods', 'service']:
                raise UserError(_(f"Item {idx}: NatureOfSupplies must be 'goods' or 'service'"))
        doc_number = payload['DocumentDetails']['DocumentNumber']
        if not re.match(r"^(0|[1-9][0-9]{0,8})$", doc_number):
            raise UserError(_("DocumentNumber must be numeric, max 9 digits"))
        for field in ['SourceSystem', 'PaymentDetails', 'ReferenceDetails']:
            if field not in payload:
                raise UserError(_(f"{field} is required in the invoice payload"))
       
    def _map_tax_code(self, tax):
        # [TOT10, TOT2, VAT15, VWHT, TWHT, VATEX, VATWH, WHOP2, WTHOI, VAT0, VWTH]
        tax_name = (tax.name or "").lower()
        group_name = (tax.tax_group_id.name or "").lower()
        amount = tax.amount or 0.0
        if not tax:
            return "VAT0", False
        if "EXEMPT" in tax.name:
            return "VATEX", False
        if amount == 15 or amount == -7.5:
            return "VAT15", False
        if amount == 0:
            return "VAT0", False
        if "withholding" in tax_name or "wht" in tax_name or amount in [2, 3, -3, -2, 30, -30]:
            return "TWTH", True
        if "excise" in tax_name or "excise" in group_name:
            return "EXCISE", True
        raise UserError(f"Unsupported tax for E-Invoice: {tax.name}")

    def _get_excise_hsn_and_rate(self, line):
        for tax in line.tax_ids:
            try:
                mapped_code, is_conditional = self._map_tax_code(tax)
            except UserError:
                continue
            if not is_conditional or mapped_code != "EXCISE":
                continue
            rate = Decimal(str(tax.amount or 0))
            name = (tax.name or "").strip()
            # Parse HSN code: "Excise 1012100 5.0" -> "1012100", "Excise 8052010 10.0" -> "8052010"
            match = re.search(r"excise\s+(\d+)\s+[\d.]+", name, re.IGNORECASE)
            if not match:
                raise UserError(_(
                    "Excise tax name must contain HSN code and rate, e.g. 'Excise 1012100 5.0'. Got: %s"
                ) % name)
            hsn_code = match.group(1)
            return (hsn_code, rate)
        return (None, Decimal('0'))

    def _get_document_type(self, move):
        return {
            "out_invoice": "INV",
            "out_refund": "CRE",
        }.get(move.move_type)
    # def _get_document_type(self, move):
    #     doc_type_map = {
    #         "out_invoice": "INV",
    #         "out_debit": "DEB",
    #         "out_refund": "CRE",
    #         "out_proforma": "PRF",#TODO: add this as custom invoice
    #     }
    #     if getattr(move, "is_overdue_invoice", False):
    #         return "OVD"
    #     if getattr(move, "is_intercompany", False):
    #         return "INC"
    #     return doc_type_map.get(move.move_type, "INV")

    def _validate_debit_credit_requirements(self, move):
        if move.move_type == "out_refund":
            original_invoice = move.reversed_entry_id
            if not move.re_einvoice_reason:
                raise UserError(_("Reason is mandatory for Debit and Credit Notes."))
            if not original_invoice or not original_invoice.x_einvoice_irn:
                raise UserError(_("Related Invoice IRN is mandatory for Debit and Credit Notes."))
            if move.amount_total >= original_invoice.amount_total:
                raise UserError(_(
                    "Credit Note total must be less than the original invoice total."
                ))
        if move.move_type == "out_invoice" and getattr(move, "debit_origin_id", False):
            original_invoice = move.debit_origin_id
            if original_invoice.move_type == "out_refund":
                raise UserError(_(
                    "You cannot create a Debit Note from a Credit Note for E-Invoice. "
                    "Please create the Debit Note from the original invoice instead."
                ))
            if not move.re_einvoice_reason:
                raise UserError(_("Reason is mandatory for Debit and Credit Notes."))
            if not original_invoice or not original_invoice.x_einvoice_irn:
                raise UserError(_("Related Invoice IRN is mandatory for Debit and Credit Notes."))
            # if move.amount_total <= original_invoice.amount_total:
            #     raise UserError(_(
            #         "Debit Note total must be greater than the original invoice total."
            #     ))

    def _get_active_configs(self, company):
        return self.env['einvoice.config'].sudo().search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])

    def _get_einvoice_config(self, company):
        configs = self._get_active_configs(company)
        if not configs:
            raise UserError(_("No active E-Invoice configuration found for company %s.") % company.name)
        return configs[0]

    def _get_original_move_for_note(self, move):
        if move.move_type == 'out_refund':
            return move.reversed_entry_id or move.reversal_move_id
        if move.move_type == 'out_invoice' and getattr(move, 'debit_origin_id', False):
            return move.debit_origin_id
        return self.env['account.move']

    def _is_credit_or_debit_note(self, move):
        if move.move_type == 'out_refund':
            return True
        return move.move_type == 'out_invoice' and bool(getattr(move, 'debit_origin_id', False))

    def _get_einvoice_product_lines(self, move):
        return move.invoice_line_ids.filtered(
            lambda line: line.display_type in (False, 'product')
        )

    def _build_original_line_number_map(self, original_move):
        # Map original invoice line id -> LineNumber, 1-based product lines only
        return {
            line.id: idx
            for idx, line in enumerate(self._get_einvoice_product_lines(original_move), start=1)
        }

    def _resolve_credit_debit_line_number(self, note_line, original_move, matched_original_line_ids):
        original_lines = self._get_einvoice_product_lines(original_move)
        line_number_map = {line.id: idx for idx, line in enumerate(original_lines, start=1)}
        for orig_line in original_lines:
            if orig_line.id in matched_original_line_ids:
                continue
            if orig_line.product_id == note_line.product_id:
                matched_original_line_ids.add(orig_line.id)
                return line_number_map[orig_line.id]
        raise UserError(_(
            "Could not match credit/debit line '%s' to a line on the original invoice %s."
        ) % (note_line.name, original_move.name))

    def _resolve_einvoice_config(self, move, user=None):
        # """Pick config: move/original invoice config, otherwise user-assigned config.
        user = user or self.env.user
        company = move.company_id
        configs = self._get_active_configs(company)
        if not configs:
            raise UserError(_("No active E-Invoice configuration found for company %s.") % company.name)

        if move.einvoice_config_id and move.einvoice_config_id in configs:
            return move.einvoice_config_id

        original_move = self._get_original_move_for_note(move)
        if original_move and original_move.einvoice_config_id and original_move.einvoice_config_id in configs:
            return original_move.einvoice_config_id

        user_config = user.sudo().einvoice_config_id
        if user_config and user_config in configs:
            return user_config

        raise UserError(_("Please assign your E-Invoice system number in user settings before submission."))

    INVALID_BUYER_NAMES = {'xxx', 'abc', 'test', 'na', 'n/a', 'none', 'x', 'a', 'b', 'c', '.', '-', '---', '...'}

    def _validate_buyer_for_b2b(self, move):
        name = (move.partner_id.name or '').strip().lower()
        if not name or len(name) < 2 or name in self.INVALID_BUYER_NAMES:
            raise UserError(_(
                "Please provide a valid buyer name for B2B transactions. "
                "Current name '%s' appears to be a placeholder."
            ) % (move.partner_id.name or ''))

    def _reserve_document_number(self, move, config):
        if move.x_einvoice_reserved_document_number:
            return move.x_einvoice_reserved_document_number
        return move._reserve_fiscal_number(config)

    def _build_invoice_payload(self, move, for_bulk=False, document_number=None, config=None):
        move.ensure_one()
        self._validate_debit_credit_requirements(move)
        move = move.with_company(move.company_id)
        company = move.company_id
        config = config or self._resolve_einvoice_config(move)
        is_note = self._is_credit_or_debit_note(move)
        original_move = self._get_original_move_for_note(move) if is_note else False
        matched_original_line_ids = set()

        if not document_number:
            document_number = move.x_einvoice_reserved_document_number
        if not document_number:
            raise UserError(_("Fiscal document number must be reserved before building the payload."))
        inv_count = int(document_number) if str(document_number).isdigit() else document_number

        if not move.invoice_date:
            raise UserError(_("Invoice date is required."))
        if not company.vat:
            raise UserError(_("Seller TIN is missing for company %s") % company.name)
        if move.transaction_type == 'B2B':
            self._validate_buyer_for_b2b(move)
        item_list = []
        conditional_taxes_found = set()
        line_number = 1
        total_tax = Decimal('0.00')
        total_discount = Decimal('0.00')
        total_excise = Decimal('0.00')
        transaction_withhold_value = Decimal('0.00')
        total_value = Decimal('0.00')

        product_lines = self._get_einvoice_product_lines(move)
        if not product_lines:
            raise UserError(_("Invoice must have at least one product line."))
        for line in product_lines:
            gross = (Decimal(str(line.quantity)) * Decimal(str(line.price_unit))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_discount_pct = line.discount or 0.0
            line_discount_amount = (gross * Decimal(str(line_discount_pct)) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            pre_tax_value = (gross - line_discount_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            price_unit_after_discount = (Decimal(str(line.price_unit)) * (Decimal('1.0') - (Decimal(str(line_discount_pct)) / Decimal('100')))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            hsn_code, excise_rate = self._get_excise_hsn_and_rate(line)
            has_excise = hsn_code is not None

            taxes_res = line.tax_ids.compute_all(float(price_unit_after_discount),currency=move.currency_id,quantity=line.quantity,product=line.product_id,partner=move.partner_id,)
            tax_code = None
            vat_amount = Decimal('0.0')
            wht_amount = Decimal('0.0')
            for tax_line in taxes_res["taxes"]:
                tax = self.env["account.tax"].browse(tax_line["id"])
                tax_amount = Decimal(str(tax_line["amount"]))
                if tax.amount == -7.5:
                    continue
                mapped_code, is_conditional = self._map_tax_code(tax)
                if is_conditional:
                    conditional_taxes_found.add(mapped_code)
                    if mapped_code == "TWTH":
                        wht_amount += Decimal(str(tax_line["amount"]))
                    continue
                tax_code = mapped_code
                if not has_excise:
                    vat_amount += Decimal(str(tax_line["amount"]))
            if not tax_code:
                tax_code = "VAT0"

            if has_excise:
                excise_tax_value = Decimal(str(line.x_excise_tax_value_line or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                if tax_code == "VAT15":
                    vat_amount = ((pre_tax_value + excise_tax_value) * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                else:
                    vat_amount = Decimal('0.00')
                tax_amount = (vat_amount + excise_tax_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                total_line_amount = (pre_tax_value + tax_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                excise_tax_value = Decimal('0.00')
                vat_amount = vat_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                tax_amount = vat_amount
                total_line_amount = (pre_tax_value + tax_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            total_value += total_line_amount
            total_tax += tax_amount
            transaction_withhold_value += wht_amount
            total_excise += excise_tax_value
            total_discount += line_discount_amount

            UNIT_MAP = {"units": "PCS","kg": "KLG","kilogram": "KLG","liter": "LTR","liters": "LTR","meter": "MTR","meters": "MTR","package": "PKG","set": "SET",}
            unit = UNIT_MAP.get((line.product_uom_id.name or "").lower(), "PCS")
            unit_price = gross / Decimal(str(line.quantity)) if line.quantity else Decimal('0.0')

            if is_note and original_move:
                payload_line_number = self._resolve_credit_debit_line_number(
                    line, original_move, matched_original_line_ids,
                )
            else:
                payload_line_number = line_number

            item = {
                "ItemCode": line.product_id.default_code or "MISC",
                "ProductDescription": line.name or "",
                "Quantity": float(round(line.quantity, 2)),
                "UnitPrice": float(unit_price),
                "PreTaxValue": float(pre_tax_value),
                "TaxAmount": float(tax_amount),
                "TaxCode": tax_code,
                "TotalLineAmount": float(total_line_amount),
                "Unit": unit,
                "LineNumber": payload_line_number,
                "Discount": float(line_discount_amount) if line_discount_amount else None,
                "ExciseTaxValue": float(excise_tax_value),
                "NatureOfSupplies": line.nature_of_goods,
            }
            if hsn_code is not None:
                item["HarmonizationCode"] = hsn_code
            else:
                item["HarmonizationCode"] = None
            item_list.append(item)
            line_number += 1
        total_value_after_wht = (total_value + transaction_withhold_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_value_rounded = total_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        net_total_value = (total_value_rounded - abs(transaction_withhold_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        payload = {
            "BuyerDetails": {
                "Tin": move.buyer_vat or None,
                "LegalName": move.partner_id.name,
                "Phone": move.buyer_phone or None,
                "Email": move.buyer_email or None,
                "Country": move.buyer_country or "70",
                "City": move.buyer_city or "0",
                "Region": move.buyer_city or "01",
                "Wereda": move.buyer_wereda or "00",
                "HouseNumber": move.buyer_house_number or "000",
                "IdType": move.buyer_id_type or "KID",
                "IdNumber": move.partner_id.id or "000"
            },
            "SellerDetails": {
                "Tin": config.seller_tin or company.vat,
                "LegalName": company.name,
                "Phone": None,
                "Email": None,
                "Wereda": config.wereda or "",
                "Region": config.region or "1",
                "VatNumber": config.vat_number or company.vat or "",
                "City": "101",
                "HouseNumber": "101",
                "Locality": None,
                "SubCity": None,
            },
            "DocumentDetails": {
                "DocumentNumber": str(inv_count),
                # "DocumentNumber": str(document_number or ""),
                "Date": move.date.strftime("%d-%m-%YT%H:%M:%S"),
                "Type": self._get_document_type(move),
                "Reason": None,
            },
            "ItemList": item_list,
            "ValueDetails": {
                "Discount": float(total_discount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "ExciseValue": float(total_excise.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "IncomeWithholdValue": 0,
                "TaxValue": float(total_tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "TotalValue": float(total_value_rounded),
                "TransactionWithholdValue": float(abs(transaction_withhold_value)),
                "InvoiceCurrency": move.currency_id.name or "ETB",
            },
            "TransactionType": move.transaction_type,
            "Version": "1",
            "SourceSystem": {
                "CashierName": move.x_clicked_by_id.name if move.x_clicked_by_id else None,
                "InvoiceCounter": inv_count,
                # "InvoiceCounter": document_number,
                "SalesPersonName": (
                    move.invoice_user_id.name
                    if move.invoice_user_id
                    else move.x_clicked_by_id.name if move.x_clicked_by_id else None
                ),
                "SystemNumber": config.system_number or "",
                "SystemType": config.system_type or "ERP",
            },
            "PaymentDetails":  {
                "Mode": move.mode_of_payment,
                "PaymentTerm": move.payment_term,
            },
            "ReferenceDetails": {
                "PreviousIrn": "",
                "RelatedDocument": None
            },
        }
        if not item_list:
            raise UserError(_("No valid invoice lines to submit."))
        if move.transaction_type == 'B2C' and "BuyerDetails" in payload:
            del payload["BuyerDetails"]["Tin"]
        # self._validate_payload(payload)
        return payload

    def _build_credit_debit_payload(self, move):
        move.ensure_one()
        # if not move.reversal_move_id:
        #     raise UserError(_("Original invoice must be selected for credit/debit notes."))
        # if not move.reversal_move_id.x_einvoice_irn:
        #     raise UserError(_("Original invoice is not yet registered with E-Invoice. Cannot register this note."))
        if not move.re_einvoice_reason:
            raise UserError(_("Cancellation/Adjustment Reason is required."))
        original_irn = ""
        original_move = False
        if move.move_type == "out_refund":
            original_move = move.reversed_entry_id or move.reversal_move_id
            if original_move and original_move.x_einvoice_irn:
                original_irn = original_move.x_einvoice_irn
            elif move.related_irn:
                original_irn = move.related_irn
        elif move.move_type == "out_invoice" and getattr(move, "debit_origin_id", False):
            original_move = move.debit_origin_id
            if original_move and original_move.x_einvoice_irn:
                original_irn = original_move.x_einvoice_irn
        config = self._resolve_einvoice_config(move)
        document_number = self._reserve_document_number(move, config)
        move.write({'einvoice_config_id': config.id})
        payload = self._build_invoice_payload(move, for_bulk=False, document_number=document_number, config=config,)
        payload["ReferenceDetails"]["PreviousIrn"] = original_irn
        payload["ReferenceDetails"]["RelatedDocument"] = original_irn
        payload["DocumentDetails"]["Reason"] = move.reason
        if move.move_type == "out_refund":
            payload["DocumentDetails"]["Type"] = "CRE"
        elif move.move_type == "out_invoice" and getattr(move, "debit_origin_id", False):
            payload["DocumentDetails"]["Type"] = "DEB"

        # _logger.info("_build_credit_debit_payload %s" , pprint.pformat(payload))

        return payload

    def register_credit_debit_note(self, move):
        move.ensure_one()
        if move.x_einvoice_cn_irn:
            raise UserError(_("This credit/debit note is already registered with IRN %s.") % move.x_einvoice_cn_irn)
        payload = self._build_credit_debit_payload(move)
        response = self.env["einvoice.api.base"]._request(
            company=move.company_id,
            method="POST",
            endpoint="/v1/register",
            payload=payload,
            config=move.einvoice_config_id,
        )
        self._handle_credit_debit_response(move, response.json())

    def register_single_invoice(self, move):
        move.ensure_one()
        if move.x_einvoice_irn:
            raise UserError(_("This invoice has already been registered with IRN %s.") % move.x_einvoice_irn)
        config = self._resolve_einvoice_config(move)
        document_number = self._reserve_document_number(move, config)
        move.write({'einvoice_config_id': config.id})
        payload = self._build_invoice_payload(
            move, document_number=document_number, config=config,
        )
        response = self.env['einvoice.api.base']._request(
            company=move.company_id,
            method='POST',
            endpoint='/v1/register',
            payload=payload,
            config=config,
        )
        self._handle_response(move, response.json())

    def register_bulk_invoices(self, moves):
        if not moves:
            return False
        company = moves[0].company_id
        invoices_payload = []
        bulk_config = None
        for move in moves:
            config = self._resolve_einvoice_config(move)
            if bulk_config and bulk_config != config:
                raise UserError(_(
                    "Bulk registration requires all invoices to use the same E-Invoice configuration. "
                    "Adjust user sales locations or split the batch."
                ))
            bulk_config = config
            document_number = self._reserve_document_number(move, config)
            move.write({'einvoice_config_id': config.id})
            payload = self._build_invoice_payload(
                move, for_bulk=True, document_number=document_number, config=config,
            )
            invoices_payload.append(payload)
        response = self.env['einvoice.api.base']._request(
            company=company,
            method='POST',
            endpoint='/v1/bulkRegister',
            payload=invoices_payload,
            config=bulk_config,
        )
        result = response.json()
        # if response.status_code != 202:
        #     raise UserError(_("Bulk invoice registration: %s") % result)
        conversation_id = result.get("conversationId")
        status = result.get("status")
        if not conversation_id:
            raise UserError(_("Bulk registration accepted but no conversationId returned."))
        moves.write({
            "x_einvoice_bulk_conversation_id": conversation_id,
            # "x_einvoice_bulk_status": status or "PENDING",
            "x_einvoice_bulk_sent_at": fields.Datetime.now(),
        })
        _logger.info("Bulk invoice registration submitted. Conversation ID: %s",conversation_id)
        return {
            "conversation_id": conversation_id,
            "status": "SUBMITTED",
        }

    def cancel_single_invoice(self, move, reason_code, remark):
        move.ensure_one()
        if not move.x_einvoice_irn:
            raise UserError(_("This invoice has no IRN to cancel."))
        if move.x_einvoice_cancel_status == "cancelled":
            raise UserError(_("This invoice has already been canceled on %s." % move.x_einvoice_cancel_date.strftime("%Y-%m-%d %H:%M:%S")))
        payload = {
            "Irn": move.x_einvoice_irn,
            "ReasonCode": str(reason_code),
            "Remark": remark or "",
        }
        response = self.env['einvoice.api.base']._request(
            company=move.company_id,
            method='POST',
            endpoint='/v1/cancel',
            payload=payload,
            config=move.einvoice_config_id or None,
        )
        self._handle_cancel_response(move, response.json())

    def verify_invoice(self, move):
        move.ensure_one()
        if not move.x_einvoice_irn:
            raise UserError(_("This invoice has no IRN to verify."))
        payload = {"irn": move.x_einvoice_irn}
        response = self.env['einvoice.api.base']._request(
            company=move.company_id,
            method='POST',
            endpoint='/v1/verify',
            payload=payload,
            config=move.einvoice_config_id or None,
        )
        return self._handle_verify_response(move, response.json())

    def _compute_einvoice_totals(self, move):
        total_value = Decimal('0.00')
        total_tax = Decimal('0.00')
        total_wht = Decimal('0.00')
        for line in move.invoice_line_ids:
            gross = (Decimal(str(line.quantity)) * Decimal(str(line.price_unit))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_discount_pct = line.discount or 0.0
            line_discount_amount = (gross * Decimal(str(line_discount_pct)) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            pre_tax = (gross - line_discount_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            price_unit_after_discount = (Decimal(str(line.price_unit)) * (Decimal('1.0') - (Decimal(str(line_discount_pct)) / Decimal('100')))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            vat_amount = Decimal('0.00')
            wht_amount = Decimal('0.00')
            excise_tax_value = Decimal(str(line.x_excise_tax_value_line or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            has_excise = excise_tax_value != Decimal('0.00')
            taxes_res = line.tax_ids.compute_all(
                float(price_unit_after_discount),
                currency=move.currency_id,
                quantity=line.quantity,
                product=line.product_id,
                partner=move.partner_id,)
            for tax_line in taxes_res["taxes"]:
                tax = self.env["account.tax"].browse(tax_line["id"])
                code, is_conditional = self._map_tax_code(tax)
                if code == "WHT" or code == "TWTH":
                    wht_amount += Decimal(str(tax_line["amount"]))
                elif code == "VAT15":
                    if not has_excise:
                        vat_amount += Decimal(str(tax_line["amount"]))
            if has_excise:
                vat_amount = ((pre_tax + excise_tax_value) * Decimal('0.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            total_line = (pre_tax + vat_amount + excise_tax_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_value += total_line
            total_tax += (vat_amount + excise_tax_value)
            total_wht += wht_amount
        return {
            "total_value": total_value.quantize(Decimal("0.01")),
            "total_tax": total_tax.quantize(Decimal("0.01")),
            "total_wht": abs(total_wht).quantize(Decimal("0.01")),
        }

    @api.model
    def send_withholding(self, move, withholding_irn=None, pretax_amount=None, withholding_amount=None):
        move.ensure_one()
        totals = self._compute_einvoice_totals(move)
        sales_total = totals["total_value"] 
        wht_total = totals["total_wht"]
        collected_amount = sales_total - wht_total
        withholding_irn = (withholding_irn or "").strip()
        if not withholding_irn:
            raise UserError(_("Cannot generate withholding receipt: missing Invoice IRN on %s.") % move.name)
        move.write({"x_withholding_invoice_irn": withholding_irn})
        pretax_amount = float(pretax_amount) if pretax_amount is not None else float(move.amount_untaxed)
        withholding_amount = float(withholding_amount) if withholding_amount is not None else float(totals["total_wht"])
        sales_lines = []
        wht_lines = []
        for line in move.invoice_line_ids:
            for tax in line.tax_ids:
                tax_code, is_wht = self._map_tax_code(tax)
                if is_wht:
                    wht_lines.append((line, tax))
                else:
                    sales_lines.append((line, tax))
        results = []
        if wht_lines:
            totals = self._compute_einvoice_totals(move)
            wht_config = self._resolve_einvoice_config(move)
            _line, first_wht_tax = wht_lines[0]
            rate = abs(first_wht_tax.amount or 0.0) / 100.0
            payload =  {
                "ReceiptNumber": f"WHREC{move.id:06d}",
                "Reason": "Withhold for goods purchased",
                "ReceiptCounter": str(move.id),
                "ManualReceiptNumber": str(move.id),
                "SourceSystemType": wht_config.source_system_type,
                "SourceSystemNumber": wht_config.system_number,
                "InvoiceDetail": {
                    "InvoiceIRN": withholding_irn,
                    "Currency": "ETB",
                    "ExchangeRate": None,
                },
                "WithholdDetail": {
                    "Type": "TWTH",
                    "Rate": rate,
                    "PreTaxAmount": pretax_amount,
                    "WithholdingAmount": withholding_amount,
                }
            }
            response = self.env['einvoice.api.base']._request(
                company=move.company_id,
                method='POST',
                endpoint='/v1/receipt/withholding',
                payload=payload,
                config=wht_config,
            )
            results.append(self._handle_withholding_response(move, self._safe_json_response(response), payload))        
        return results
        
    @api.model
    def send_receipt_from_payment(self, payment, move):
        payment.ensure_one()
        move.ensure_one()
        if not move.x_einvoice_irn:
            raise UserError(_("Invoice %s has no IRN.") % move.name)
        if payment.state in ['draft', 'canceled', 'rejected']:
            raise UserError(_("Payment must be posted before sending receipt."))

        invoice_paid_amount = payment.amount
        total_discount = sum((line.discount or 0.0) * line.price_unit * line.quantity / 100.0 for line in move.invoice_line_ids)

        config = self._resolve_einvoice_config(move)
        totals = self._compute_einvoice_totals(move)
        total_amount = float(totals["total_value"])
        # already_sent = float(move.x_einvoice_sales_paid_total or 0.0)
        # cumulative_paid_after = already_sent + invoice_paid_amount
        # remaining_amount = total_amount - cumulative_paid_after
        # payment_coverage = "FULL" if remaining_amount <= 0 else "PARTIAL"
        already_sent = float(move.x_einvoice_sales_paid_total or 0.0)
        actual_paid_total = float(total_amount - move.amount_residual)
        invoice_paid_amount = actual_paid_total - already_sent
        # if invoice_paid_amount <= 0:
        #     raise UserError(_("No new amount available for receipt submission."))
        remaining_amount = float(move.amount_residual)
        payment_coverage = (
            "FULL"
            if move.payment_state in ('paid', 'in_payment') or remaining_amount <= 0
            else "PARTIAL"
        )
        payload = {
            "ReceiptNumber": f"REC{payment.id:06d}",
            "ReceiptType": "Sales Receipts",
            "ReceiptDate": fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f+03:00"),
            "ReceiptCounter": str(payment.id),

            "SourceSystemType": config.source_system_type or "POS",
            "SourceSystemNumber": config.source_system_number or "",
            "ReceiptCurrency": move.currency_id.name or "ETB",

            "CollectedAmount": invoice_paid_amount,
            "SellerTIN": config.seller_tin or move.company_id.vat or "",

            "Invoices": [{
                "InvoiceIRN": move.x_einvoice_irn,
                "InvoicePaidAmount": invoice_paid_amount,
                "RemainingAmount": remaining_amount,
                "PaymentCoverage": payment.x_payment_coverage,
                "TotalAmount": total_amount,
            }],

            "TransactionDetails": {
                "ModeOfPayment": payment.mode_of_payment_receipt or None,
                "CollectorName": payment.x_clicked_by_id.name if hasattr(payment, "x_clicked_by_id") else "",
                "PaymentServiceProvider": payment.payment_service_provider or None,
                "AccountNumber": payment.account_number or None,
                "TransactionNumber": payment.transaction_number or "",
            },
        }
        _logger.info("Sales Receipt%s", pprint.pformat(payload))

        response = self.env['einvoice.api.base']._request(
            company=move.company_id,
            method='POST',
            endpoint='/v1/receipt/sales',
            payload=payload,
            config=config,
        )

        move.x_einvoice_sales_paid_total = actual_paid_total
        return self._handle_receipt_response_from_payment(
            move,
            payment,
            self._safe_json_response(response),
            payload,
            "Sales Receipt"
        )

