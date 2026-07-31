import { User } from './entities/user.entity';
import { IdentityDocumentType } from './enums/identity-document-type.enum';

export interface RegisterUserInput {
  email: string;
  passwordHash: string;
  firstName: string;
  lastName: string;
  nationality: string;
  birthDate: string;
  idType: IdentityDocumentType;
  idNumber: string;
  companyCode?: string;
  termsAgreedAt: Date;
  privacyAgreedAt: Date;
}

export interface RegisterAdminInput {
  email: string;
  passwordHash: string;
  firstName: string;
  lastName: string;
}

export interface UpdateUserProfileInput {
  firstName?: string;
  lastName?: string;
}

export interface UserCredentials {
  user: User;
  passwordHash: string;
}

export const USER_REPOSITORY = Symbol('USER_REPOSITORY');

export interface UserRepository {
  register(input: RegisterUserInput): Promise<User>;
  registerAdmin(input: RegisterAdminInput): Promise<User>;
  findById(id: string): Promise<User | null>;
  findByEmail(email: string): Promise<User | null>;
  /** Includes the password hash — only for AuthService's credential check, never returned from the public API. */
  findCredentialsByEmail(email: string): Promise<UserCredentials | null>;
  existsByEmail(email: string): Promise<boolean>;
  existsByIdentityDocument(idType: IdentityDocumentType, idNumber: string): Promise<boolean>;
  recordLoginSuccess(id: string): Promise<void>;
  recordLoginFailure(id: string): Promise<void>;
  update(id: string, input: UpdateUserProfileInput): Promise<User>;
  list(): Promise<User[]>;
}
