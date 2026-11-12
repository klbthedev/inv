from odoo import models, fields

class EinvoiceDocument(models.Model):
    _name = 'einvoice.document'
    _description = 'E-Invoice Document'

    name = fields.Char(string="File Name", required=True)
    datas = fields.Binary(string="File Content (Base64)", attachment=True)
    mimetype = fields.Char(string="Mime Type")
    res_model = fields.Char(string="Resource Model")
    res_id = fields.Integer(string="Resource ID")
