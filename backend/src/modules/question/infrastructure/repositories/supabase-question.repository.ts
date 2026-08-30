import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { operationFailed } from '../../../../common/exceptions/error-messages';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  Question,
  QuestionChecklistItem,
  QuestionContent,
} from '../../domain/entities/question.entity';
import { QuestionSectionType } from '../../domain/enums/question-section-type.enum';
import {
  CreateQuestionDraftInput,
  QuestionRepository,
} from '../../domain/question.repository.interface';

const QUESTION_TABLE = 'tb_question';
const CHECKLIST_TABLE = 'tb_question_checklist_item';

interface QuestionRow {
  question_id: number;
  part: QuestionSectionType;
  content: QuestionContent;
  document_id: number | null;
  created_at: string;
}

interface ChecklistItemRow {
  checklist_item_id: number;
  question_id: number;
  code: string;
  description: string;
  weight: number;
  display_order: number;
}

function toChecklistDomain(row: ChecklistItemRow): QuestionChecklistItem {
  return {
    id: String(row.checklist_item_id),
    code: row.code,
    description: row.description,
    weight: Number(row.weight),
    displayOrder: row.display_order,
  };
}

function toDomain(row: QuestionRow, checklistItems: QuestionChecklistItem[]): Question {
  return new Question(
    String(row.question_id),
    row.part,
    row.content,
    row.document_id !== null ? String(row.document_id) : null,
    checklistItems,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseQuestionRepository implements QuestionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async bulkCreateDrafts(
    documentId: string,
    items: CreateQuestionDraftInput[],
  ): Promise<Question[]> {
    const client = this.supabaseService.getAdminClient();

    const { data: questionRows, error } = await client
      .from(QUESTION_TABLE)
      .insert(
        items.map((item) => ({
          part: item.part,
          content: item.content,
          document_id: Number(documentId),
        })),
      )
      .select()
      .returns<QuestionRow[]>();

    if (error || !questionRows) {
      throw new ConflictDomainException(error?.message ?? operationFailed('create the questions'));
    }

    const checklistPayload = questionRows.flatMap((row, index) =>
      items[index].checklist.map((c, checklistIndex) => ({
        question_id: row.question_id,
        code: c.code,
        description: c.description,
        weight: c.weight,
        display_order: checklistIndex,
      })),
    );

    const { data: checklistRows, error: checklistError } = await client
      .from(CHECKLIST_TABLE)
      .insert(checklistPayload)
      .select()
      .returns<ChecklistItemRow[]>();

    if (checklistError || !checklistRows) {
      throw new ConflictDomainException(
        checklistError?.message ?? operationFailed('create the question checklist'),
      );
    }

    return questionRows.map((row) =>
      toDomain(
        row,
        checklistRows.filter((c) => c.question_id === row.question_id).map(toChecklistDomain),
      ),
    );
  }

  async findByDocumentId(documentId: string): Promise<Question[]> {
    const client = this.supabaseService.getAdminClient();
    const { data: questionRows } = await client
      .from(QUESTION_TABLE)
      .select('*')
      .eq('document_id', Number(documentId))
      .is('deleted_at', null)
      .order('question_id', { ascending: true })
      .returns<QuestionRow[]>();

    return this.attachChecklistItems(questionRows ?? []);
  }

  async findById(id: string): Promise<Question | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(QUESTION_TABLE)
      .select('*')
      .eq('question_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<QuestionRow>();

    if (!data) {
      return null;
    }
    const [question] = await this.attachChecklistItems([data]);
    return question;
  }

  async findByIds(ids: string[]): Promise<Question[]> {
    if (ids.length === 0) {
      return [];
    }
    const client = this.supabaseService.getAdminClient();
    const { data: questionRows } = await client
      .from(QUESTION_TABLE)
      .select('*')
      .in(
        'question_id',
        ids.map((id) => Number(id)),
      )
      .is('deleted_at', null)
      .order('question_id', { ascending: true })
      .returns<QuestionRow[]>();

    return this.attachChecklistItems(questionRows ?? []);
  }

  /** 세션 시작 시 문항 풀 랜덤 선택에 쓰인다 — used=false(검수 전 초안/테스트 문항)는 후보에서 뺀다. */
  async findByPart(part: QuestionSectionType): Promise<Question[]> {
    const client = this.supabaseService.getAdminClient();
    const { data: questionRows } = await client
      .from(QUESTION_TABLE)
      .select('*')
      .eq('part', part)
      .eq('used', true)
      .is('deleted_at', null)
      .order('question_id', { ascending: true })
      .returns<QuestionRow[]>();

    return this.attachChecklistItems(questionRows ?? []);
  }

  private async attachChecklistItems(questionRows: QuestionRow[]): Promise<Question[]> {
    if (questionRows.length === 0) {
      return [];
    }

    const client = this.supabaseService.getAdminClient();
    const { data: checklistRows } = await client
      .from(CHECKLIST_TABLE)
      .select('*')
      .in(
        'question_id',
        questionRows.map((row) => row.question_id),
      )
      .is('deleted_at', null)
      .order('display_order', { ascending: true })
      .returns<ChecklistItemRow[]>();

    return questionRows.map((row) =>
      toDomain(
        row,
        (checklistRows ?? [])
          .filter((c) => c.question_id === row.question_id)
          .map(toChecklistDomain),
      ),
    );
  }
}
