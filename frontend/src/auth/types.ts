export interface Studio {
  id: string;
  name: string;
  slug: string;
}

export interface BillingSummary {
  state: 'trial' | 'active' | 'payment_due' | 'ending' | 'lapsed';
  can_work: boolean;
  gallery_open: boolean;
  message: string;
  until: string | null;
  plan: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'owner' | 'staff' | '';
  email_verified: boolean;
  studio: Studio | null;
  billing: BillingSummary | null;
  /** How sharing works on this server. Missing (older servers) means email sharing is on. */
  sharing?: SharingSettings;
}

export interface SharingSettings {
  /** Clients can be given an email address and get their login by email. Off: WhatsApp only. */
  client_email: boolean;
  /** The studio must confirm its own email before sharing a gallery. */
  confirm_email_first: boolean;
}

export interface MeResponse {
  user: User | null;
}
