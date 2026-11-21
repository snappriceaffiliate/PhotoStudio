/** WhatsApp "click to chat" links: open WhatsApp with the gallery invitation typed in. */

export interface Invitation {
  clientName: string;
  studioName: string;
  eventTitle: string;
  galleryUrl: string;
  username: string;
  password: string;
  selectionLimit?: number | null;
}

export function invitationText(i: Invitation): string {
  const firstName = i.clientName.trim().split(/\s+/)[0] || i.clientName;
  const limit = i.selectionLimit ? `You can choose up to ${i.selectionLimit} photos. ` : '';
  return [
    `Hello ${firstName}, your photos from ${i.eventTitle} are ready to choose.`,
    '',
    `Open the gallery, tap ♡ on the photos you want printed, and press Submit when you are done. ${limit}Your choices save as you go.`,
    '',
    `Gallery: ${i.galleryUrl}`,
    `Username: ${i.username}`,
    `Password: ${i.password}`,
    '',
    `– ${i.studioName}`,
  ].join('\n');
}

export interface Reminder {
  clientName: string;
  studioName: string;
  eventTitle: string;
  galleryUrl: string;
  username: string;
  selected: number;
  selectionLimit?: number | null;
  /** The gallery closes after this date (YYYY-MM-DD), when the reminder is because of it. */
  closesOn?: string | null;
}

/** A reminder for a client who has not submitted. The password was in the first message and
 * the server keeps only a hash of it, so the reminder points back to that message. */
export function reminderText(r: Reminder): string {
  const firstName = r.clientName.trim().split(/\s+/)[0] || r.clientName;
  const chosen = r.selected
    ? ` You have chosen ${r.selected}${r.selectionLimit ? ` of ${r.selectionLimit}` : ''} so far; your choices are saved.`
    : '';
  const closes = r.closesOn
    ? ` The gallery closes after ${new Date(`${r.closesOn}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'long' })}, so please submit by then.`
    : '';
  return [
    `Hello ${firstName}, a gentle reminder to choose your photos from ${r.eventTitle}.${chosen}${closes}`,
    '',
    'Open the gallery, tap ♡ on the photos you want printed, and press Submit when you are done.',
    '',
    `Gallery: ${r.galleryUrl}`,
    `Username: ${r.username}`,
    'Use the password from our earlier message. If you cannot find it, reply here and we will send a new one.',
    '',
    `– ${r.studioName}`,
  ].join('\n');
}

/**
 * wa.me link. With a number (country code + digits, as the server stores it) WhatsApp opens
 * that chat; without one, the studio picks the contact inside WhatsApp.
 */
export function whatsappLink(text: string, phone?: string | null): string {
  const digits = (phone ?? '').replace(/\D/g, '');
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

export function formatPhone(digits: string): string {
  if (digits.startsWith('91') && digits.length === 12) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return `+${digits}`;
}
