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
}

export interface MeResponse {
  user: User | null;
}
