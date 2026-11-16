import { api } from '../api/client';

/**
 * Deletes an event after the owner types its name. Returns true if it was deleted.
 * Deleting cannot be undone, so a simple OK/Cancel is not enough.
 */
export async function deleteEventAfterConfirm(event: { id: string; title: string }): Promise<boolean> {
  const typed = window.prompt(
    `Delete "${event.title}"?\n\n` +
      'This deletes the event, all its photos, the client logins and the client’s selection. ' +
      'It cannot be undone. Your original photos on your computer are not touched.\n\n' +
      'Type the event name to confirm:',
  );
  if (typed === null) return false;
  if (typed.trim() !== event.title.trim()) {
    window.alert('The name did not match, so nothing was deleted.');
    return false;
  }
  await api(`/events/${event.id}`, { method: 'DELETE' });
  return true;
}
