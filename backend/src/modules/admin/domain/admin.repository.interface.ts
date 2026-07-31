import { Admin } from './entities/admin.entity';

export interface RegisterAdminInput {
  email: string;
  passwordHash: string;
  name: string;
}

export interface AdminCredentials {
  admin: Admin;
  passwordHash: string;
}

export const ADMIN_REPOSITORY = Symbol('ADMIN_REPOSITORY');

export interface AdminRepository {
  register(input: RegisterAdminInput): Promise<Admin>;
  findById(id: string): Promise<Admin | null>;
  existsByEmail(email: string): Promise<boolean>;
  /** Includes the password hash — only for AuthService's credential check, never returned from the public API. */
  findCredentialsByEmail(email: string): Promise<AdminCredentials | null>;
  recordLoginSuccess(id: string): Promise<void>;
  recordLoginFailure(id: string): Promise<void>;
}
