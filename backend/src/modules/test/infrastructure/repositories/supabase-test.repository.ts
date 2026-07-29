import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Test } from '../../domain/entities/test.entity';
import {
  CreateTestInput,
  TestRepository,
  UpdateTestInput,
} from '../../domain/test.repository.interface';

const TABLE = 'tests';

interface TestRow {
  id: string;
  title: string;
  description: string | null;
  duration_minutes: number;
  created_by: string;
  created_at: string;
}

function toDomain(row: TestRow): Test {
  return new Test(
    row.id,
    row.title,
    row.description,
    row.duration_minutes,
    row.created_by,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseTestRepository implements TestRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateTestInput): Promise<Test> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        title: input.title,
        description: input.description ?? null,
        duration_minutes: input.durationMinutes,
        created_by: input.createdBy,
      })
      .select()
      .single<TestRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? 'Failed to create test');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Test | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('*').eq('id', id).maybeSingle<TestRow>();
    return data ? toDomain(data) : null;
  }

  async update(id: string, input: UpdateTestInput): Promise<Test> {
    const client = this.supabaseService.getAdminClient();
    const update: Record<string, unknown> = {};
    if (input.title !== undefined) update.title = input.title;
    if (input.description !== undefined) update.description = input.description;
    if (input.durationMinutes !== undefined) update.duration_minutes = input.durationMinutes;

    const { data, error } = await client
      .from(TABLE)
      .update(update)
      .eq('id', id)
      .select()
      .single<TestRow>();

    if (error || !data) {
      throw new NotFoundDomainException(`Test ${id} not found`);
    }
    return toDomain(data);
  }

  async delete(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client.from(TABLE).delete().eq('id', id);
  }

  async list(): Promise<Test[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('*').returns<TestRow[]>();
    return (data ?? []).map(toDomain);
  }
}
