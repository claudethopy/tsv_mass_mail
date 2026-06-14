{
    'name': 'TSV Massen-Mailing',
    'version': '18.0.1.0.0',
    'summary': 'Einfaches Massen-Mailing für TSV-Mitglieder mit Rate-Limiting',
    'author': 'TSV Schwerin',
    'category': 'Communication',
    'depends': ['mail', 'tsv_membership_form', 'tsv_access_restrictions', 'tsv_main'],
    'data': [
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/cron.xml',
        'views/tsv_mailing_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
