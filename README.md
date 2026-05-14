# tsv_mass_mail

Odoo 18 Addon für den TSV Schwerin. Bietet eine leichtgewichtige Alternative zum
kostenpflichtigen Odoo-Enterprise-Modul `mass_mailing`. Erlaubt das Versenden von
Sammel-E-Mails an eine frei wählbare Liste von Kontakten (`res.partner`) — mit
Rate-Limiting durch einen Cron-Job, um den E-Mail-Provider nicht zu überlasten.
Abteilungsadmins können nur Mitglieder ihrer eigenen Abteilung anschreiben; TSV-Admins
haben uneingeschränkten Zugriff mit optionalem Abteilungsfilter.

---

## Voraussetzungen

- Odoo 18
- Modul `tsv_membership_form` installiert (für `tsv_membership_state` auf `res.partner`)
- Modul `tsv_access_restrictions` installiert (für Gruppen und `department_id`)
- Ausgehender Mailserver konfiguriert (*Einstellungen → Technisch → E-Mail → Ausgehende
  Mailserver*)

---

## Installation

```bash
docker compose exec web odoo -d tsv_18 \
  --db_host=db --db_user=odoo --db_password=odoo \
  -i tsv_mass_mail --stop-after-init
```

---

## Bedienung (Schritt für Schritt)

### 1. Neue Sammel-E-Mail anlegen

*TSV → Sammel-E-Mails → Neu*

| Feld | Bedeutung |
|---|---|
| Bezeichnung | Interner Name, z. B. „Newsletter Mai 2026" |
| Betreff | Betreff der E-Mail |
| E-Mail-Vorlage | Optionale Odoo-Vorlage als Ausgangspunkt (wird in den Editor geladen) |
| Abteilung | Wird automatisch aus dem Nutzerprofil gesetzt; bestimmt die Sichtbarkeit |
| Nur diese Abteilungen | (Nur TSV-Admin) Schränkt den Schnellknopf auf bestimmte Abteilungen ein |
| Inhalt | HTML-E-Mail-Body (Rich-Text-Editor, startet mit ausreichend Höhe) |
| Anhänge | Dateianhänge, die an jede E-Mail angehängt werden |

### 2. Vorlage verwenden

- **Vorlage auswählen**: Sobald eine Vorlage gewählt wird, lädt deren Inhalt automatisch
  in den Editor. Der Betreff wird übernommen, falls das Feld noch leer ist.
- **Als Vorlage speichern**: Schaltfläche in der Kopfzeile speichert den aktuellen
  Betreff und Inhalt als neue Odoo-E-Mail-Vorlage und verknüpft sie sofort.

Vorlagen werden unter *Einstellungen → Technisch → E-Mail → Vorlagen* verwaltet und
müssen dem Modell **Kontakt (`res.partner`)** zugeordnet sein.

### 3. Empfänger wählen

Im Tab **Empfänger** (zeigt Name, Abteilung und E-Mail-Adresse) stehen zwei Wege:

- **Manuell**: Partner über das Suchfeld einzeln hinzufügen oder entfernen
- **Schnellknopf** „Alle aktiven Mitglieder hinzufügen" (Kopfzeile):
  - *Abteilungsadmin*: fügt nur Mitglieder der eigenen Abteilung hinzu
  - *TSV-Admin*: fügt alle Mitglieder hinzu — oder nur die aus den im Feld
    „Nur diese Abteilungen" gewählten Abteilungen, falls gesetzt

> Empfänger können nur im Zustand **Entwurf** bearbeitet werden.

### 4. Versand starten

Schaltfläche **„Versand starten"** in der Kopfzeile:

- Erzeugt eine Versandzeile (`tsv.mailing.recipient`) für jeden Empfänger
- Setzt den Status auf **Bereit**
- Der Cron-Job übernimmt das tatsächliche Versenden in Batches

### 5. Fortschritt verfolgen

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

### 6. Abbrechen und neu starten

- **„Abbrechen"**: stoppt den Versand (Status → Abgebrochen); bereits gesendete E-Mails
  bleiben erhalten
- **„Zurück zu Entwurf"**: setzt den Status zurück; ausstehende Versandzeilen werden beim
  nächsten **„Versand starten"** neu erzeugt, bereits gesendete/fehlerhafte Zeilen bleiben
  als Protokoll erhalten

---

## Zugriffsrechte

| Gruppe | Sieht | Schnellknopf |
|---|---|---|
| `group_tsv_department_admin` | Nur eigene Mailings (gleiche Abteilung) | Nur eigene Abteilungsmitglieder |
| `group_tsv_admin` | Alle Mailings | Alle Mitglieder (oder gefiltert nach „Nur diese Abteilungen") |

Die Empfängerliste im Entwurf ist durch die bestehende `ir.rule` auf `res.partner`
abgesichert: Abteilungsadmins können dort ohnehin nur Partner ihrer eigenen Abteilung
sehen und auswählen.

---

## Rate-Limiting (Batchgröße konfigurieren)

Der Cron-Job läuft standardmäßig alle **5 Minuten** und sendet pro Lauf maximal
**30 E-Mails** (ca. 360 E-Mails/Stunde).

### Batchgröße anpassen

*Einstellungen → Technisch → Parameter → Systemparameter → Neu*

| Schlüssel | Standardwert | Bedeutung |
|---|---|---|
| `tsv_mailing.batch_size` | `30` | E-Mails pro Cron-Lauf |

### Cron-Intervall anpassen

*Einstellungen → Technisch → Automatische Aktionen → „TSV Mailing: Batch versenden"*

**Beispielkonfigurationen:**

| Batchgröße | Intervall | E-Mails/Stunde |
|---|---|---|
| 30 | 5 min | 360 |
| 20 | 5 min | 240 |
| 50 | 10 min | 300 |

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
│   ├── ir.model.access.csv
│   └── record_rules.xml            ← Abteilungsbeschränkung per ir.rule
└── views/
    └── tsv_mailing_views.xml       ← Form, Liste, Menü
```

---

## Einschränkungen

- Kein Opt-out-Mechanismus. Für Blog-Benachrichtigungen mit Abmeldefunktion
  siehe `tsv_blog_notifications`.
- Bei SMTP-Fehlern wird die Versandzeile als **Fehlgeschlagen** markiert;
  ein automatischer Wiederholungsversuch findet nicht statt.
