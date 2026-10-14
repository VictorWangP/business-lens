export interface User {
  id: string;
  username: string;
  email?: string;
  created_at: string;
  role?: 'user' | 'feedback_admin';
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}
