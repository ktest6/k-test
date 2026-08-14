import { User } from '../../domain/entities/user.entity';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';

export interface UserRow {
  user_id: number;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  nationality: string;
  birth_date: string;
  id_type: IdentityDocumentType | null;
  id_number: string | null;
  company_code: string | null;
  terms_agreed_at: string;
  privacy_agreed_at: string;
  login_attempts: number;
  last_login_at: string | null;
  created_at: string;
}

export class UserMapper {
  static toDomain(row: UserRow): User {
    return new User(
      String(row.user_id),
      row.email,
      row.first_name,
      row.last_name,
      row.nationality,
      row.birth_date,
      row.id_type,
      row.id_number,
      row.company_code,
      new Date(row.terms_agreed_at),
      new Date(row.privacy_agreed_at),
      row.login_attempts,
      row.last_login_at ? new Date(row.last_login_at) : null,
      new Date(row.created_at),
    );
  }
}
