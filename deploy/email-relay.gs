/**
 * Tro email relay: sends Tro's emails from your Gmail.
 *
 * Render's free plan blocks the ports email normally uses, so the backend
 * posts each email over https to this script instead, and Google sends it
 * from the account that deployed the script.
 *
 * Setup (deploy/README.md has screenshots-free steps):
 *   1. https://script.new while signed in to the sending Gmail account.
 *   2. Replace everything with this file. Change RELAY_KEY to a long random
 *      string (the same value goes in Render as EMAIL_RELAY_KEY).
 *   3. Deploy > New deployment > type "Web app".
 *      Execute as: Me.  Who has access: Anyone.  Deploy, allow access.
 *   4. Copy the Web app URL (ends in /exec) into Render as EMAIL_RELAY_URL.
 *
 * Free Gmail accounts can send to about 100 recipients a day this way.
 */

const RELAY_KEY = 'CHANGE-ME-to-a-long-random-string';

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    if (RELAY_KEY.indexOf('CHANGE-ME') === 0 || req.key !== RELAY_KEY) {
      return reply_({ ok: false, error: 'bad key' });
    }
    if (!req.to || !req.subject) {
      return reply_({ ok: false, error: 'missing to or subject' });
    }
    MailApp.sendEmail({
      to: req.to,
      subject: req.subject,
      body: req.text || '',
      htmlBody: req.html || undefined,
      name: req.name || 'Tro',
    });
    return reply_({ ok: true, remaining: MailApp.getRemainingDailyQuota() });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  }
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
