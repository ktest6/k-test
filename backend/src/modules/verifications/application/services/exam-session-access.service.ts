import { Injectable } from '@nestjs/common';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';

interface ExamSessionOwnerRow {
  exam_session_id: number;
  user_id: number;
}

/**
 * 응시 세션이 실제로 이 사용자 소유인지 확인. /verifications 아래의 모든
 * 인증 타입(id-card, 추후 earphone 등)이 공통으로 쓰는 검증이라 여기서
 * 공유한다.
 */
@Injectable()
export class ExamSessionAccessService {
  constructor(private readonly supabaseService: SupabaseService) {}

  async assertOwnership(userId: string, sessionId: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    const { data: session } = await client
      .from('tb_exam_session')
      .select('exam_session_id, user_id')
      .eq('exam_session_id', Number(sessionId))
      .maybeSingle<ExamSessionOwnerRow>();

    if (!session || String(session.user_id) !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }
  }
}
