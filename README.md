# tsv_mass_mail

Odoo 18 Addon für den TSV Schwerin. Bietet eine leichtgewichtige Alternative zum
kostenpflichtigen Odoo-Enterprise-Modul `mass_mailing`. Erlaubt das Versenden von
E-Mails an eine frei wählbare Liste von Kontakten (`res.partner`) — mit Rate-Limiting
durch einen Cron-Job, um den E-Mail-Provider nicht zu überlasten.

---

## Voraussetzungen

- Odoo 18
- Modul `tsv_membership_form` installiert (wird für den Schnellknopf "Alle aktiven
  Mitglieder hinzufügen" benötigt, da er auf das Feld `tsv_membership_state` zugreift)
- Ausgehender Mailserver konfiguriert (*Einstellungen → Technisch → E-Mail → Ausgehende
  Mailserver*)

> **Hinweis zur Abhängigkeit:** Die Kernfunktion (Mailing mit beliebiger Partner-Auswahl)
> ist unabhängig von `tsv_membership_form`. Nur der Schnellknopf setzt das dortige
> Mitgliedschaftsfeld voraus. Sollte das Modul einmal nicht mehr benötigt werden, kann
> `action_add_all_members` in `models/tsv_mailing.py` durch eine eigene Filterlogik
> ersetzt und die Abhängigkeit entfernt werden.

---

## Installation

```bash
docker compose exec web odoo -d tsv_18 \
  --db_host=db --db_user=odoo --db_password=odoo \
  -i tsv_mass_mail --stop-after-init
```

---

## Bedienung (Schritt für Schritt)

### 1. Neues Mailing anlegen

*TSV Mailing → Mailings → Neu*

| Feld | Bedeutung |
|---|---|
| Bezeichnung | Interner Name, z. B. „Newsletter Mai 2026" |
| Betreff | Betreff der E-Mail |
| Inhalt | HTML-E-Mail-Body (Rich-Text-Editor) |

### 2. Empfänger wählen

Im Tab **Empfänger** stehen zwei Wege zur Auswahl:

- **Manuell**: Partner über das Suchfeld einzeln hinzufügen oder entfernen
- **Schnellknopf** „Alle aktiven Mitglieder hinzufügen" (Kopfzeile): trägt automatisch
  alle Partner mit `tsv_membership_state = 'member'` und vorhandener E-Mail-Adresse ein.
  Die Liste kann danach noch manuell angepasst werden.

> Empfänger können nur im Zustand **Entwurf** bearbeitet werden.

### 3. Versand starten

Schaltfläche **„Versand starten"** in der Kopfzeile:

- Erzeugt eine Versandzeile (`tsv.mailing.recipient`) für jeden Empfänger
- Setzt den Status auf **Bereit**
- Der Cron-Job übernimmt das tatsächliche Versenden

### 4. Fortschritt verfolgen

Sobald der Cron-Job den ersten Batch verschickt hat, wechselt der Status auf
**Wird gesendet**. Im Tab **Versandprotokoll** ist pro Empfänger sichtbar:

| Spalte | Bedeutung |
|---|---|
| Kontakt | Verlinkter `res.partner` |
| E-Mail-Adresse | Adresse zum Zeitpunkt des Versands |
| Status | Ausstehend / Gesendet / Fehlgeschlagen |
| Gesendet am | Zeitstempel des erfolgreichen Versands |
| Fehlermeldung | SMTP-Fehlertext bei fehlgeschlagenen Zeilen |

Zeilen sind farblich hervorgehoben: grün = gesendet, rot = fehlgeschlagen, grau = ausstehend.

### 5. Abbrechen und neu starten

- **„Abbrechen"**: stoppt den Versand (Status → Abgebrochen); bereits gesendete E-Mails
  bleiben erhalten
- **„Zurück zu Entwurf"**: setzt den Status auf Entwurf zurück; ausstehende Versandzeilen
  werden beim nächsten **„Versand starten"** neu erzeugt, bereits gesendete/fehlerhafte
  Zeilen bleiben als Protokoll erhalten

---

## Rate-Limiting (Batchgröße konfigurieren)

Der Cron-Job läuft standardmäßig alle **5 Minuten** und sendet pro Lauf maximal
**30 E-Mails**. Das ergibt ca. 360 E-Mails pro Stunde.

### Batchgröße anpassen

*Einstellungen → Technisch → Parameter → Systemparameter → Neu*

| Schlüssel | Standardwert | Bedeutung |
|---|---|---|
| `tsv_mailing.batch_size` | `30` | E-Mails pro Cron-Lauf |

### Cron-Intervall anpassen

*Einstellungen → Technisch → Automatische Aktionen → „TSV Mailing: Batch versenden"*

Dort lässt sich das Intervall direkt ändern (z. B. alle 10 Minuten für langsamere
Provider).

**Beispielkonfigurationen:**

| Batchgröße | Intervall | E-Mails/Stunde |
|---|---|---|
| 30 | 5 min | 360 |
| 20 | 5 min | 240 |
| 50 | 10 min | 300 |

---

## Zugriffsrechte

Standardmäßig ist das Modul nur für Nutzer der Gruppe **Einstellungen / Technisch**
(`base.group_system`) sichtbar und bedienbar. Um es für weitere Nutzer freizugeben,
die Einträge in `security/ir.model.access.csv` und die `groups`-Attribute in
`views/tsv_mailing_views.xml` auf die gewünschte Gruppe anpassen (z. B.
`base.group_partner_manager` für Kontakt-Manager).

---

## Dateistruktur

```
tsv_mass_mail/
├── __init__.py
├── __manifest__.py
├── data/
│   └── cron.xml                    ← Cron-Job-Definition
├── models/
│   ├── __init__.py
│   ├── tsv_mailing.py              ← Hauptmodell + _send_batch()-Logik
│   └── tsv_mailing_recipient.py    ← Versandzeilen pro Empfänger
├── security/
│   └── ir.model.access.csv
└── views/
    └── tsv_mailing_views.xml       ← Form, Liste, Menü
```

---

## Einschränkungen

- Es gibt kein Opt-out-Mechanismus in diesem Modul. Für Blog-Benachrichtigungen mit
  Abmeldefunktion siehe `tsv_blog_notifications`.
- Anhänge werden nicht unterstützt.
- Bei SMTP-Fehlern (z. B. ungültige Adresse) wird die Versandzeile als **Fehlgeschlagen**
  markiert; ein automatischer Wiederholungsversuch findet nicht statt.
