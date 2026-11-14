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
