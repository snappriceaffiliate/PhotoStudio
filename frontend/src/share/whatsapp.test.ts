import { describe, expect, it } from 'vitest';
import { formatPhone, invitationText, whatsappLink } from './whatsapp';

const invite = {
  clientName: 'Priya Rao',
  studioName: 'Lens & Light',
  eventTitle: 'Priya and Arun Wedding',
  galleryUrl: 'https://app.example.in/gallery/login?u=priya-k7m2qx',
  username: 'priya-k7m2qx',
  password: 'ab2c-de3f-gh4j',
  selectionLimit: 200,
};

describe('WhatsApp invitation', () => {
  it('greets by first name and includes the login and the limit', () => {
    const text = invitationText(invite);
    expect(text.startsWith('Hello Priya, your photos from Priya and Arun Wedding')).toBe(true);
    expect(text).toContain('Username: priya-k7m2qx\nPassword: ab2c-de3f-gh4j');
    expect(text).toContain('up to 200 photos');
    expect(text.endsWith('– Lens & Light')).toBe(true);
  });

  it('opens the client chat when the number is known, and encodes the text safely', () => {
    const link = whatsappLink('a & b ♡\nc', '919876543210');
    expect(link.startsWith('https://wa.me/919876543210?text=')).toBe(true);
    expect(decodeURIComponent(link.split('text=')[1])).toBe('a & b ♡\nc');
    expect(link).not.toContain(' ');
  });

  it('lets the studio choose the contact when there is no number', () => {
    expect(whatsappLink('hi').startsWith('https://wa.me/?text=')).toBe(true);
  });

  it('formats numbers for display', () => {
    expect(formatPhone('919876543210')).toBe('+91 98765 43210');
    expect(formatPhone('447700900123')).toBe('+447700900123');
  });
});
