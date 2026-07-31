import { Injectable } from '@nestjs/common';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';

interface ExamSessionOwnerRow {
  exam_session_id: number;
  exam_id: number;
  user_id: number;
}

export interface ExamSessionOwnership {
  examSessionId: string;
  examId: string;
}

/**
 * 응시 세션이 실제로 이 사용자 소유인지 확인. /verifications 아래의 모든
 * 인증 타입(id-card, 추후 earphone 등)이 공통으로 쓰는 검증이라 여기서
 * 공유한다. 소유권 확인 김에 examId도 같이 돌려줘서, 호출하는 쪽이 세션을
 * 또 조회할 필요 없게 한다(id-card 대조 요청에 exam_id가 필요함).
 */
@Injectable()
export class ExamSessionAccessService {
  constructor(private readonly supabaseService: SupabaseService) {}

  async assertOwnership(userId: string, examSessionId: string): Promise<ExamSessionOwnership> {
    const client = this.supabaseService.getAdminClient();
    const { data: session } = await client
      .from('tb_exam_session')
      .select('exam_session_id, exam_id, user_id')
      .eq('exam_session_id', Number(examSessionId))
      .maybeSingle<ExamSessionOwnerRow>();

    if (!session || String(session.user_id) !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }

    return { examSessionId: String(session.exam_session_id), examId: String(session.exam_id) };
  }
}
