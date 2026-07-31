import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Admin } from '../../domain/entities/admin.entity';
import {
  AdminCredentials,
  AdminRepository,
  RegisterAdminInput,
} from '../../domain/admin.repository.interface';

const TABLE = 'tb_admin';

interface AdminRow {
  admin_id: number;
  email: string;
  password: string;
  name: string;
  login_attempts: number;
  last_login_at: string | null;
  created_at: string;
}

function toDomain(row: AdminRow): Admin {
  return new Admin(
    String(row.admin_id),
    row.email,
    row.name,
    row.login_attempts,
    row.last_login_at ? new Date(row.last_login_at) : null,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseAdminRepository implements AdminRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async register(input: RegisterAdminInput): Promise<Admin> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({ email: input.email, password: input.passwordHash, name: input.name })
      .select()
      .single<AdminRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '관리자 계정 생성에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Admin | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('admin_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<AdminRow>();
    return data ? toDomain(data) : null;
  }

  async existsByEmail(email: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('admin_id')
      .eq('email', email)
      .is('deleted_at', null)
      .maybeSingle<{ admin_id: number }>();
    return !!data;
  }

  async findCredentialsByEmail(email: string): Promise<AdminCredentials | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('email', email)
      .is('deleted_at', null)
      .maybeSingle<AdminRow>();
    return data ? { admin: toDomain(data), passwordHash: data.password } : null;
  }

  async recordLoginSuccess(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ login_attempts: 0, last_login_at: new Date().toISOString() })
      .eq('admin_id', Number(id));
  }

  async recordLoginFailure(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('login_attempts')
      .eq('admin_id', Number(id))
      .single<{ login_attempts: number }>();

    await client
      .from(TABLE)
      .update({ login_attempts: (data?.login_attempts ?? 0) + 1 })
      .eq('admin_id', Number(id));
  }
}
