import { Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { User } from '../../domain/entities/user.entity';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';
import {
  RegisterUserInput,
  UpdateUserProfileInput,
  UserCredentials,
  UserRepository,
} from '../../domain/user.repository.interface';
import { UserMapper, UserRow } from '../mappers/user.mapper';

const TABLE = 'tb_user';

@Injectable()
export class SupabaseUserRepository implements UserRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async register(input: RegisterUserInput): Promise<User> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        email: input.email,
        password: input.passwordHash,
        first_name: input.firstName,
        last_name: input.lastName,
        nationality: input.nationality,
        birth_date: input.birthDate,
        id_type: input.idType ?? null,
        id_number: input.idNumber ?? null,
        company_code: input.companyCode ?? null,
        terms_agreed_at: input.termsAgreedAt.toISOString(),
        privacy_agreed_at: input.privacyAgreedAt.toISOString(),
        email_verified_at: input.emailVerifiedAt.toISOString(),
      })
      .select()
      .single<UserRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '회원가입에 실패했습니다.');
    }
    return UserMapper.toDomain(data);
  }

  async findById(id: string): Promise<User | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('user_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<UserRow>();
    return data ? UserMapper.toDomain(data) : null;
  }

  async findByEmail(email: string): Promise<User | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('email', email)
      .is('deleted_at', null)
      .maybeSingle<UserRow>();
    return data ? UserMapper.toDomain(data) : null;
  }

  async findCredentialsByEmail(email: string): Promise<UserCredentials | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('email', email)
      .is('deleted_at', null)
      .maybeSingle<UserRow>();
    return data ? { user: UserMapper.toDomain(data), passwordHash: data.password } : null;
  }

  async existsByEmail(email: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('user_id')
      .eq('email', email)
      .is('deleted_at', null)
      .maybeSingle<{ user_id: number }>();
    return !!data;
  }

  async existsByIdentityDocument(idType: IdentityDocumentType, idNumber: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('user_id')
      .eq('id_type', idType)
      .eq('id_number', idNumber)
      .is('deleted_at', null)
      .maybeSingle<{ user_id: number }>();
    return !!data;
  }

  async recordLoginSuccess(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ login_attempts: 0, last_login_at: new Date().toISOString() })
      .eq('user_id', Number(id));
  }

  async recordLoginFailure(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('login_attempts')
      .eq('user_id', Number(id))
      .single<{ login_attempts: number }>();

    await client
      .from(TABLE)
      .update({ login_attempts: (data?.login_attempts ?? 0) + 1 })
      .eq('user_id', Number(id));
  }

  async update(id: string, input: UpdateUserProfileInput): Promise<User> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .update({
        ...(input.firstName !== undefined && { first_name: input.firstName }),
        ...(input.lastName !== undefined && { last_name: input.lastName }),
      })
      .eq('user_id', Number(id))
      .select()
      .single<UserRow>();

    if (error || !data) {
      throw new NotFoundDomainException(`사용자(${id})를 찾을 수 없습니다.`);
    }
    return UserMapper.toDomain(data);
  }

  async list(): Promise<User[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .is('deleted_at', null)
      .returns<UserRow[]>();
    return (data ?? []).map((row) => UserMapper.toDomain(row));
  }
}
