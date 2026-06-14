from odoo import api, fields, models
from odoo.exceptions import UserError


class TsvMailing(models.Model):
    _name = 'tsv.mailing'
    _description = 'TSV Massen-Mailing'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Bezeichnung', required=True)
    subject = fields.Char(string='Betreff', required=True)
    body_html = fields.Html(string='Inhalt', required=True, sanitize=False)
    template_id = fields.Many2one(
        'mail.template',
        string='E-Mail-Vorlage',
        domain=[('model', '=', 'res.partner')],
        ondelete='set null',
    )
    department_id = fields.Many2one(
        'tsv.departments',
        string='Abteilung',
        default=lambda self: self.env.user.partner_id.department_id,
        readonly=True,
    )
    filter_department_ids = fields.Many2many(
        'tsv.departments',
        'tsv_mailing_dept_filter_rel',
        'mailing_id', 'dept_id',
        string='Nur diese Abteilungen',
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'tsv_mailing_attachment_rel',
        'mailing_id',
        'attachment_id',
        string='Anhänge',
    )
    state = fields.Selection([
        ('draft', 'Entwurf'),
        ('ready', 'Bereit'),
        ('sending', 'Wird gesendet'),
        ('done', 'Abgeschlossen'),
        ('cancelled', 'Abgebrochen'),
    ], default='draft', string='Status', required=True)

    recipient_ids = fields.Many2many(
        'res.partner',
        'tsv_mailing_partner_rel',
        'mailing_id',
        'partner_id',
        string='Empfänger',
    )
    recipient_line_ids = fields.One2many(
        'tsv.mailing.recipient',
        'mailing_id',
        string='Versandprotokoll',
    )

    total_count = fields.Integer(compute='_compute_counts', string='Gesamt')
    sent_count = fields.Integer(compute='_compute_counts', string='Gesendet')
    failed_count = fields.Integer(compute='_compute_counts', string='Fehlgeschlagen')
    pending_count = fields.Integer(compute='_compute_counts', string='Ausstehend')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if not self.template_id:
            return
        if self.template_id.body_html:
            self.body_html = self.template_id.body_html
        if self.template_id.subject and not self.subject:
            self.subject = self.template_id.subject

    @api.depends('recipient_line_ids.state')
    def _compute_counts(self):
        for rec in self:
            lines = rec.recipient_line_ids
            rec.total_count = len(lines)
            rec.sent_count = len(lines.filtered(lambda l: l.state == 'sent'))
            rec.failed_count = len(lines.filtered(lambda l: l.state == 'failed'))
            rec.pending_count = len(lines.filtered(lambda l: l.state == 'pending'))

    def action_add_board_members(self):
        self.ensure_one()
        positions = self.env['tsv.position'].search([
            ('contact_id', '!=', False),
            ('contact_id.email', '!=', False),
        ])
        contacts = positions.mapped('contact_id')
        self.recipient_ids = [(4, c.id) for c in contacts]

    def action_add_all_members(self):
        self.ensure_one()
        is_admin = self.env.user.has_group('tsv_access_restrictions.group_tsv_admin')
        domain = [
            ('tsv_membership_state', '=', 'member'),
            ('email', '!=', False),
            ('active', '=', True),
        ]
        if is_admin:
            if self.filter_department_ids:
                domain.append(('department_id', 'in', self.filter_department_ids.ids))
        else:
            own_dept = self.env.user.partner_id.department_id
            if not own_dept:
                raise UserError('Ihrem Benutzer ist keine Abteilung zugewiesen.')
            domain.append(('department_id', '=', own_dept.id))
        members = self.env['res.partner'].search(domain)
        self.recipient_ids = [(4, p.id) for p in members]

    def action_start(self):
        self.ensure_one()
        if not self.recipient_ids:
            raise UserError('Keine Empfänger ausgewählt.')
        # Pending-Zeilen aus einem vorherigen Versuch entfernen, gesendete/fehlerhafte behalten
        self.recipient_line_ids.filtered(lambda l: l.state == 'pending').unlink()
        processed_ids = self.recipient_line_ids.mapped('partner_id').ids
        new_lines = [
            {'mailing_id': self.id, 'partner_id': p.id, 'email': p.email}
            for p in self.recipient_ids
            if p.id not in processed_ids and p.email
        ]
        if new_lines:
            self.env['tsv.mailing.recipient'].create(new_lines)
        self.state = 'ready'

    def action_save_as_template(self):
        self.ensure_one()
        partner_model = self.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1
        )
        template = self.env['mail.template'].create({
            'name': self.name,
            'model_id': partner_model.id,
            'subject': self.subject,
            'body_html': self.body_html,
        })
        self.template_id = template
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Vorlage gespeichert',
                'message': f'Die Vorlage „{template.name}" wurde angelegt und verknüpft.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_cancel(self):
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.state = 'draft'

    def _send_batch(self):
        """Wird vom Cron-Job aufgerufen: sendet den nächsten Batch ausstehender Empfänger."""
        batch_size = int(self.env['ir.config_parameter'].sudo().get_param(
            'tsv_mailing.batch_size', default=30
        ))
        mailings = self.search([('state', 'in', ['ready', 'sending'])], order='id asc')
        for mailing in mailings:
            if mailing.state == 'ready':
                mailing.state = 'sending'

            pending = mailing.recipient_line_ids.filtered(
                lambda l: l.state == 'pending'
            )[:batch_size]

            if not pending:
                mailing.state = 'done'
                continue

            for line in pending:
                try:
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': mailing.subject,
                        'email_to': line.email,
                        'body_html': mailing.body_html,
                        'attachment_ids': [(4, att.id) for att in mailing.attachment_ids],
                        'auto_delete': True,
                    })
                    mail.send(raise_exception=True)
                    line.write({'state': 'sent', 'sent_at': fields.Datetime.now()})
                except Exception as exc:
                    line.write({'state': 'failed', 'error_message': str(exc)[:255]})

            if not mailing.recipient_line_ids.filtered(lambda l: l.state == 'pending'):
                mailing.state = 'done'
