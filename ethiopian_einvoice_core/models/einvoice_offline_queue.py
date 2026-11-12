from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import logging
import hashlib
import secrets

_logger = logging.getLogger(__name__)


class EinvoiceOfflineQueue(models.Model):
    _name = 'einvoice.offline.queue'
    _description = 'E-Invoice Offline Request Queue'
    _order = 'create_date asc'

    company_id = fields.Many2one('res.company', required=True)
    endpoint = fields.Char(required=True)
    method = fields.Char(required=True)
    payload = fields.Text(required=True)
    payload_encrypted = fields.Text(
        string="Encrypted Payload",
        copy=False,
        groups="base.group_system",
        help="Encrypted payload-at-rest mirror for INSA compliance. If set, cron replay decrypts it before sending.",
    )
    payload_hash = fields.Char(index=True, readonly=True, copy=False)
    move_ids = fields.Many2many('account.move', string="Related Invoices")
    status = fields.Selection([
        ('pending', 'Pending'),
        ('failed', 'Failed'),
        ('done', 'Done')
    ], default='pending')
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)

    # @api.model
    # def _compute_payload_hash(self, payload):
    #     payload_json = json.dumps(payload or [], sort_keys=True, separators=(",", ":"))
    #     return hashlib.sha256(payload_json.encode("utf-8")).hexdigest(), payload_json

    # def _ensure_pgcrypto(self):
    #     self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # def _get_master_key(self):
    #     icp = self.env["ir.config_parameter"].sudo()
    #     key = icp.get_param("ethiopian_einvoice_hardening.master_key")
    #     if not key:
    #         key = secrets.token_urlsafe(48)
    #         icp.set_param("ethiopian_einvoice_hardening.master_key", key)
    #     return key

    # def _encrypt_text(self, plaintext):
    #     if plaintext is False or plaintext is None:
    #         return False
    #     self._ensure_pgcrypto()
    #     key = self._get_master_key()
    #     self.env.cr.execute(
    #         "SELECT encode(pgp_sym_encrypt(%s, %s), 'base64')",
    #         (plaintext, key),)
    #     row = self.env.cr.fetchone()
    #     return row and row[0] or False

    # def _decrypt_text(self, ciphertext):
    #     if not ciphertext:
    #         return False
    #     self._ensure_pgcrypto()
    #     key = self._get_master_key()
    #     self.env.cr.execute(
    #         "SELECT pgp_sym_decrypt(decode(%s, 'base64'), %s)",
    #         (ciphertext, key),)
    #     row = self.env.cr.fetchone()
    #     return row and row[0] or False

    # @api.model
    # def enqueue_unique(self, company, endpoint, method, payload, move_ids=None):
    #     payload_hash, payload_json = self._compute_payload_hash(payload)
    #     domain = [
    #         ("company_id", "=", company.id),
    #         ("endpoint", "=", endpoint),
    #         ("method", "=", method),
    #         ("payload_hash", "=", payload_hash),
    #         ("status", "in", ["pending", "failed"]),
    #     ]
    #     existing = self.search(domain, limit=1)
    #     if existing:
    #         if move_ids:
    #             existing.write({"move_ids": [(6, 0, list(set(existing.move_ids.ids + list(move_ids))))]})
    #         return existing, False
    #     payload_encrypted = False
    #     payload_field_value = payload_json
    #     try:
    #         payload_encrypted = self._encrypt_text(payload_json)
    #         if payload_encrypted:
    #             payload_field_value = _("REDACTED")
    #     except Exception:
    #         payload_encrypted = False
    #     rec = self.create({
    #         "company_id": company.id,
    #         "endpoint": endpoint,
    #         "method": method,
    #         "payload": payload_field_value,
    #         "payload_encrypted": payload_encrypted,
    #         "payload_hash": payload_hash,
    #         "move_ids": [(6, 0, move_ids or [])],
    #     })
    #     return rec, True

    # def _mark_duplicate_siblings_done(self):
    #     for req in self:
    #         if not req.payload_hash:
    #             continue
    #         siblings = self.search([
    #             ("id", "!=", req.id),
    #             ("company_id", "=", req.company_id.id),
    #             ("endpoint", "=", req.endpoint),
    #             ("method", "=", req.method),
    #             ("payload_hash", "=", req.payload_hash),
    #             ("status", "in", ["pending", "failed"]),
    #         ])
    #         if siblings:
    #             siblings.write({
    #                 "status": "done",
    #                 "error_message": _("Deduplicated: another identical queued request already succeeded."),})

    # @api.model
    # def _is_duplicate_registration_response(self, response):
    #     text = ""
    #     try:
    #         text = (response.text or "").lower()
    #     except Exception:
    #         text = ""
    #     markers = (
    #         "already registered",
    #         "already been registered",
    #         "duplicate",
    #         "irn already exists",
    #         "invoice irn given",)
    #     return any(m in text for m in markers)

    # @api.model
    # def cron_resubmit_offline_requests(self):
    #     pending = self.search([('status', 'in', ['pending', 'failed']), ('retry_count', '<', 10)])
    #     service = self.env['einvoice.invoice.service']
    #     for req in pending:
    #         try:
    #             if req.endpoint == '/v1/register' and req.move_ids and any(req.move_ids.mapped("x_einvoice_irn")):
    #                 req.write({
    #                     'status': 'done',
    #                     'error_message': _('Skipped retry: invoice is already registered (IRN exists).'),
    #                 })
    #                 req._mark_duplicate_siblings_done()
    #                 continue
    #             payload_source = req.payload
    #             used_plaintext_storage = not bool(req.payload_encrypted)
    #             if req.payload_encrypted:
    #                 decrypted = req._decrypt_text(req.payload_encrypted)
    #                 if decrypted:
    #                     payload_source = decrypted
    #             payload = json.loads(payload_source)
    #             if used_plaintext_storage:
    #                 try:
    #                     encrypted = req._encrypt_text(req.payload) if req.payload else False
    #                     if encrypted:
    #                         req.write({"payload": _("REDACTED"), "payload_encrypted": encrypted})
    #                 except Exception:
    #                     pass
    #             move_for_config = req.move_ids[:1]
    #             response = self.env['einvoice.api.base'].with_context(skip_offline_queue=True)._request(
    #                 req.company_id,
    #                 req.method,
    #                 req.endpoint,
    #                 payload,
    #                 config=move_for_config.einvoice_config_id if move_for_config else None,
    #             )
    #             if response.status_code == 200:
    #                 req.write({'status': 'done', 'error_message': False})
    #                 move = req.move_ids[:1]
    #                 if move and req.endpoint == '/v1/register':
    #                     service._handle_response(move, response.json())
    #                 req._mark_duplicate_siblings_done()
    #             elif response.status_code == 202 and req.endpoint == '/v1/bulkRegister':
    #                 req.write({'status': 'done', 'error_message': False})
    #                 result = response.json()
    #                 conversation_id = result.get('conversationId')
    #                 if conversation_id and req.move_ids:
    #                     req.move_ids.write({
    #                         'einvoice_bulk_conversation_id': conversation_id,
    #                         'x_einvoice_bulk_status': 'PENDING',
    #                         'x_einvoice_bulk_sent_at': fields.Datetime.now(),
    #                     })
    #                 req._mark_duplicate_siblings_done()
    #             elif req.endpoint in ("/v1/register", "/v1/bulkRegister") and self._is_duplicate_registration_response(response):
    #                 req.write({
    #                     'status': 'done',
    #                     'error_message': _('Terminal duplicate response: request already processed upstream.'),
    #                 })
    #                 req._mark_duplicate_siblings_done()
    #             else:
    #                 req.write({
    #                     'retry_count': req.retry_count + 1,
    #                     'error_message': response.text,
    #                     'status': 'failed',
    #                 })
    #         except Exception as e:
    #             req.write({
    #                 'retry_count': req.retry_count + 1,
    #                 'error_message': str(e),
    #                 'status': 'failed',
    #             })
