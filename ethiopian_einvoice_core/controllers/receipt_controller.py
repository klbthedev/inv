import base64

from odoo import http
from odoo.http import request


class EInvoiceReceiptController(http.Controller):

    @http.route('/einvoice/receipt/<int:attachment_id>/pdf', auth='public', type='http', csrf=True)
    def receipt_pdf(self, attachment_id, **kwargs):
        attachment = request.env['einvoice.document'].sudo().browse(attachment_id)
        if not attachment or not attachment.exists():
            return request.not_found()
        # Odoo stores attachment.datas as base64; decode for binary PDF response
        pdf_bytes = base64.b64decode(attachment.datas) if attachment.datas else b''
        if not pdf_bytes:
            return request.not_found()
        return request.make_response(
            pdf_bytes,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'inline; filename="{attachment.name}"')
            ]
        )
