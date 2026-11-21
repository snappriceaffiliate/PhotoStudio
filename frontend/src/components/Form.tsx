import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react';
import { ApiError, type FieldErrors } from '../api/client';

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  name: string;
  errors?: FieldErrors;
  hint?: ReactNode;
}

export function Field({ label, name, errors, hint, ...input }: FieldProps) {
  const messages = errors?.[name];
  const id = `field-${name}`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} name={name} aria-invalid={messages ? true : undefined} aria-describedby={messages ? `${id}-error` : undefined} {...input} />
      {hint && !messages && <p className="field-hint">{hint}</p>}
      {messages && (
        <p className="field-error" id={`${id}-error`}>
          {messages.join(' ')}
        </p>
      )}
    </div>
  );
}

export function FormMessage({ error, success }: { error?: string; success?: string }) {
  if (error) return <p className="form-error" role="alert">{error}</p>;
  if (success) return <p className="form-success" role="status">{success}</p>;
  return null;
}

/** Runs an async submit handler and turns API errors into field and form messages. */
export function useSubmit<T>(handler: () => Promise<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fields, setFields] = useState<FieldErrors>({});

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const form = event.currentTarget instanceof HTMLFormElement ? event.currentTarget : null;
    setBusy(true);
    setError('');
    setFields({});
    try {
      return await handler();
    } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fields);
        // Errors not tied to one input (or none at all) go in the message above the form.
        const general = !Object.keys(err.fields).length || 'non_field_errors' in err.fields || err.status === 429;
        // Errors for a box this form does not have would otherwise show nowhere; this happens
        // when the page was opened before an update added the box.
        const unshown = form
          ? Object.keys(err.fields).filter((key) => key !== 'non_field_errors' && !form.elements.namedItem(key))
          : [];
        if (unshown.length) {
          const messages = unshown.flatMap((key) => err.fields[key]).join(' ');
          setError(`${messages} If you don't see a box for this, reload the page and try again.`);
        } else if (general) setError(err.message);
      } else {
        setError('Something went wrong. Check your connection and try again.');
      }
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, fields, onSubmit };
}
