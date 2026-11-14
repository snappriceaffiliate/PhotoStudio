export interface Studio {
  id: string;
  name: string;
  slug: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'owner' | 'staff' | '';
  email_verified: boolean;
  studio: Studio | null;
}

export interface MeResponse {
  user: User | null;
}
