from markupsafe import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import formataddr


class TsvMailing(models.Model):
    _name = 'tsv.mailing'
    _inherit = ['mail.thread']
    _description = 'TSV Massen-Mailing'
    _order = 'create_date desc'
    _rec_name = 'name'

    def _default_sender_position(self):
        """Vereinsamt des angemeldeten Benutzers, dessen Amtskontakt eine E-Mail-Adresse hat."""
        positions = self.env.user.partner_id.position_ids
        return next((p for p in positions if p.contact_id.email), self.env['tsv.position'])

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
    ], default='draft', string='Status', required=True, tracking=True)

    sender_position_id = fields.Many2one(
        'tsv.position',
        string='Absender (Vereinsamt)',
        domain=[('contact_id.email', '!=', False)],
        default=lambda self: self._default_sender_position(),
        tracking=True,
        help='Die E-Mail geht im Namen dieses Vereinsamts raus, mit der E-Mail-Adresse des '
             'Amtskontakts. Standard ist ein Vereinsamt des Erstellers. TSV-Admins können es '
             'vor dem Versand ändern, z. B. wenn der Vorstand versenden soll.',
    )
    sender_editable = fields.Boolean(compute='_compute_sender_editable')
    sender_display = fields.Char(string='Absender', compute='_compute_sender_display')

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

    @api.depends('state')
    @api.depends_context('uid')
    def _compute_sender_editable(self):
        is_admin = self.env.user.has_group('tsv_access_restrictions.group_tsv_admin')
        for rec in self:
            rec.sender_editable = is_admin and rec.state == 'draft'

    @api.depends('sender_position_id', 'sender_position_id.contact_id.email',
                 'sender_position_id.contact_id.name', 'create_uid')
    def _compute_sender_display(self):
        from_address = self._get_smtp_from()
        for rec in self:
            email_from, reply_to = self._get_sender(rec, from_address)
            rec.sender_display = email_from or _('(kein Absender ermittelbar)')

    def write(self, vals):
        if 'sender_position_id' in vals and not self.env.user.has_group('tsv_access_restrictions.group_tsv_admin'):
            for rec in self:
                if rec.sender_position_id.id != vals['sender_position_id']:
                    raise UserError(_('Nur TSV-Admins dürfen den Absender ändern.'))
        return super().write(vals)

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

    def _log(self, text):
        """Protokolleintrag im Chatter (wer, wann steht automatisch dabei)."""
        # Viele Odoo-Benutzer haben keine eigene E-Mail-Adresse; ohne email_from verweigert
        # message_post() den Eintrag. Autor bleibt der handelnde Benutzer.
        user_partner = self.env.user.partner_id
        email_from = (user_partner.email_formatted or self.env.company.email_formatted
                      or self._get_smtp_from() or 'noreply@localhost')
        self.sudo().message_post(
            body=escape(text), message_type='notification', subtype_xmlid='mail.mt_note',
            author_id=user_partner.id, email_from=email_from)

    def action_start(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Das Mailing wurde bereits gestartet. Ein erneuter Versand ist nur '
                              'über „Zurück zu Entwurf" durch einen TSV-Admin möglich.'))
        if not self.recipient_ids:
            raise UserError('Keine Empfänger ausgewählt.')
        # Abteilungsadmins sehen nur Kontakte der eigenen Abteilung (und ohne Abteilung). Enthält die
        # Liste mehr, wird der Versand auf die sichtbaren Empfänger beschränkt; das wird im
        # Verlauf vermerkt, damit es nachvollziehbar ist.
        # Direkt in der Relationstabelle zaehlen: ueber den ORM-Cache wuerde auch die sudo-Liste
        # nur die bereits gefilterten, sichtbaren Empfaenger enthalten.
        self.flush_recordset(['recipient_ids'])
        self.env.cr.execute(
            'SELECT COUNT(*) FROM tsv_mailing_partner_rel WHERE mailing_id = %s', (self.id,))
        hidden = self.env.cr.fetchone()[0] - len(self.recipient_ids)
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
        text = _('Versand gestartet von %(user)s. Absender: %(sender)s. Empfänger mit E-Mail-Adresse: %(n)s.',
                 user=self.env.user.name, sender=self.sender_display, n=len(new_lines))
        if hidden > 0:
            text += ' ' + _('ACHTUNG: %s weitere Empfänger der Liste gehören zu anderen Abteilungen, sind für '
                            'diesen Benutzer nicht sichtbar und erhalten die E-Mail nicht.', hidden)
        self._log(text)

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
        self._log(_('Versand abgebrochen von %s.', self.env.user.name))

    def action_reset_draft(self):
        # Kompletter Neustart: Versandprotokoll verwerfen, damit ein erneuter
        # Start frische pending-Zeilen fuer alle aktuellen Empfaenger erzeugt.
        # Ohne dieses Loeschen wuerde action_start die bereits vorhandenen
        # sent/failed-Zeilen ueberspringen und es wuerde nichts versendet.
        # Das loescht das Versandprotokoll und kann zu doppelten Mails fuehren,
        # deshalb nur fuer TSV-Admins.
        if not self.env.user.has_group('tsv_access_restrictions.group_tsv_admin'):
            raise UserError(_('Nur TSV-Admins dürfen ein Mailing zurück zu Entwurf setzen.'))
        for rec in self:
            lines = rec.recipient_line_ids
            rec._log(_('Zurück zu Entwurf gesetzt von %(user)s. Versandprotokoll gelöscht '
                       '(%(total)s Einträge, davon %(sent)s gesendet). Bei erneutem Versand erhalten die '
                       'Empfänger die E-Mail nochmals.',
                       user=self.env.user.name, total=len(lines),
                       sent=len(lines.filtered(lambda l: l.state == 'sent'))))
            lines.unlink()
            rec.state = 'draft'

    def _get_smtp_from(self):
        mail_server = self.env['ir.mail_server'].sudo().search([], order='sequence asc', limit=1)
        smtp_from = mail_server.smtp_user if mail_server and mail_server.smtp_user else False
        return smtp_from or self.env.company.email

    def _get_sender(self, mailing, fallback_from):
        """Ermittelt Absenderadresse und Reply-To fuer ein Mailing.

        Vorrang hat die E-Mail des Amtskontakts zum Vereinsamt des Erstellers:
        Odoo-User haben meist keine eigene E-Mail, die echte tsv-schwerin.org-
        Adresse haengt am Amtskontakt (tsv.position.contact_id). Wir suchen also
        ueber create_uid.partner_id.position_ids das erste Amt mit hinterlegter
        Amtskontakt-E-Mail und senden darueber. Faellt das weg, nutzen wir die
        SMTP-/Firmenadresse als Rueckfallebene.

        Die Adresse muss zur authentifizierten Domain passen (SPF/DMARC), sonst
        lehnt der Provider ab; die Amtskontakt-Adressen liegen in dieser Domain.
        """
        # Explizit gewaehlter Absender (Feld sender_position_id) hat Vorrang.
        chosen = mailing.sender_position_id.contact_id
        if chosen and chosen.email:
            return formataddr((chosen.name or mailing.sender_position_id.name, chosen.email)), chosen.email

        sender_partner = mailing.create_uid.partner_id
        office_contact = next((
            pos.contact_id
            for pos in sender_partner.position_ids
            if pos.contact_id and pos.contact_id.email
        ), False)

        if office_contact:
            name = office_contact.name or sender_partner.name or self.env.company.name
            return formataddr((name, office_contact.email)), office_contact.email

        # Rueckfall: SMTP-/Firmenadresse als Absender, Reply-To auf den Ersteller.
        # fallback_from kann leer sein (kein SMTP-User, keine Firmen-E-Mail) -
        # dann darf formataddr nicht crashen, sonst reisst es den ganzen Cron-Lauf
        # mit zurueck. In dem Fall ohne gueltigen Absender: der einzelne
        # Sendeversuch schlaegt dann sauber pro Empfaenger fehl.
        name = sender_partner.name or self.env.company.name
        if mailing.department_id:
            name = '%s (%s)' % (name, mailing.department_id.name)
        email_from = formataddr((name, fallback_from)) if fallback_from else False
        reply_to = sender_partner.email or fallback_from or False
        return email_from, reply_to

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

            email_from, reply_to = self._get_sender(mailing, self._get_smtp_from())

            for line in pending:
                mail = False
                try:
                    # auto_delete=False, damit wir nach dem Senden den echten
                    # Status der Mail auslesen koennen (bei auto_delete wuerde der
                    # Datensatz bei Erfolg sofort geloescht).
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': mailing.subject,
                        'email_from': email_from,
                        'reply_to': reply_to,
                        'email_to': line.email,
                        'body_html': mailing.body_html,
                        'attachment_ids': [(4, att.id) for att in mailing.attachment_ids],
                        'auto_delete': False,
                    })
                    mail.send(raise_exception=True)
                    # WICHTIG: mail.send() liefert auch dann True, wenn Odoo den
                    # Empfaenger still verwirft (ungueltige/blacklisted Adresse,
                    # ungueltiger Absender) und in Wahrheit nichts versendet wurde.
                    # Deshalb pruefen wir den tatsaechlichen Mail-Status, nicht den
                    # Rueckgabewert von send().
                    if mail.state == 'sent':
                        line.write({'state': 'sent', 'sent_at': fields.Datetime.now()})
                    else:
                        line.write({
                            'state': 'failed',
                            'error_message': (
                                mail.failure_reason
                                or 'E-Mail nicht versendet (Status: %s)' % mail.state
                            )[:255],
                        })
                except Exception as exc:
                    line.write({'state': 'failed', 'error_message': str(exc)[:255]})
                finally:
                    if mail and mail.exists():
                        mail.sudo().unlink()

            if not mailing.recipient_line_ids.filtered(lambda l: l.state == 'pending'):
                mailing.state = 'done'
