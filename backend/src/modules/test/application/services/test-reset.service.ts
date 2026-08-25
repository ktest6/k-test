import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';

const TABLE = 'tb_exam_session';

/**
 * 테스트 전용 — 모든 응시 세션을 INPROGRESS로 되돌린다. 반복 테스트 중
 * BLOCKED/DISQUALIFIED/SUBMITTED로 막혀 더 이상 진행할 수 없을 때 수동으로
 * 리셋하기 위한 용도. 인증 없이 호출되므로(@Public) 프로덕션에서는 절대
 * 동작하면 안 된다 — env가 production이면 무조건 거부한다.
 */
@Injectable()
export class TestResetService {
  constructor(
    private readonly supabaseService: SupabaseService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async resetAllSessionsToInProgress(): Promise<number> {
    if (this.config.env === 'production') {
      throw new ForbiddenDomainException('프로덕션 환경에서는 사용할 수 없습니다.');
    }

    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .update({ status: SessionStatus.INPROGRESS, resume_count: 0 })
      .not('exam_session_id', 'is', null)
      .select('exam_session_id');

    if (error) {
      throw new ForbiddenDomainException(error.message ?? '세션 리셋에 실패했습니다.');
    }
    return (data ?? []).length;
  }
}
