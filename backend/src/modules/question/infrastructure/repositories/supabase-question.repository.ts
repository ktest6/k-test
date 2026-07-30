import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Question } from '../../domain/entities/question.entity';
import { QuestionType } from '../../domain/enums/question-type.enum';
import {
  CreateQuestionInput,
  QuestionRepository,
  UpdateQuestionInput,
} from '../../domain/question.repository.interface';

const TABLE = 'questions';

interface QuestionRow {
  id: string;
  test_id: string;
  type: QuestionType;
  content: string;
  choices: string[] | null;
  correct_answer: string | null;
  points: number;
  created_at: string;
}

function toDomain(row: QuestionRow): Question {
  return new Question(
    row.id,
    row.test_id,
    row.type,
    row.content,
    row.choices,
    row.correct_answer,
    row.points,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseQuestionRepository implements QuestionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateQuestionInput): Promise<Question> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        test_id: input.testId,
        type: input.type,
        content: input.content,
        choices: input.choices ?? null,
        correct_answer: input.correctAnswer ?? null,
        points: input.points,
      })
      .select()
      .single<QuestionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? '문제 생성에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Question | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('*').eq('id', id).maybeSingle<QuestionRow>();
    return data ? toDomain(data) : null;
  }

  async update(id: string, input: UpdateQuestionInput): Promise<Question> {
    const client = this.supabaseService.getAdminClient();
    const update: Record<string, unknown> = {};
    if (input.content !== undefined) update.content = input.content;
    if (input.choices !== undefined) update.choices = input.choices;
    if (input.correctAnswer !== undefined) update.correct_answer = input.correctAnswer;
    if (input.points !== undefined) update.points = input.points;

    const { data, error } = await client
      .from(TABLE)
      .update(update)
      .eq('id', id)
      .select()
      .single<QuestionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(`문제(${id})를 찾을 수 없습니다.`);
    }
    return toDomain(data);
  }

  async delete(id: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client.from(TABLE).delete().eq('id', id);
  }

  async listByTestId(testId: string): Promise<Question[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('test_id', testId)
      .returns<QuestionRow[]>();
    return (data ?? []).map(toDomain);
  }
}
