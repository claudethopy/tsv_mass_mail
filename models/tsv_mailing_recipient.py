from odoo import fields, models


class TsvMailingRecipient(models.Model):
    _name = 'tsv.mailing.recipient'
    _description = 'TSV Mailing Versandzeile'
    _order = 'id'

    mailing_id = fields.Many2one(
        'tsv.mailing', string='Mailing',
        required=True, ondelete='cascade',
    )
    partner_id = fields.Many2one('res.partner', string='Kontakt')
    email = fields.Char(string='E-Mail-Adresse', required=True)
    state = fields.Selection([
        ('pending', 'Ausstehend'),
        ('sent', 'Gesendet'),
        ('failed', 'Fehlgeschlagen'),
    ], default='pending', string='Status', required=True)
    sent_at = fields.Datetime(string='Gesendet am')
    error_message = fields.Char(string='Fehlermeldung')
