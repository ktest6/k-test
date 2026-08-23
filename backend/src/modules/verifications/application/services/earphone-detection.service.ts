import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  EARPHONE_PROVIDER,
  EarphoneImageInput,
  EarphoneProviderPort,
} from '../../../ai/domain/ports/earphone-provider.port';
import { ExamSessionAccessService } from '../../../exam-session/application/services/exam-session-access.service';
import { EarphoneDetectResponseDto } from '../dto/earphone-detect-response.dto';

/**
 * 시험 시작 후 이어폰 착용 여부 감지. id-card 인증과 마찬가지로 examSessionId
 * 기준(회차 없음, 세션 소유권 + 진행중 여부만 확인)이다. 이미지는 다른 인증
 * 흐름처럼 Storage에 올리지 않고 요청에 그대로 실어 보낸다 — 감사용으로
 * 남겨야 할 필요가 없는 일회성 판정이라 저장 없이 바로 전달만 한다.
 * 판정 "결과"는 남긴다 — 게이트(ExamSessionService.assertVerifiedSession,
 * REQUIRE_EARPHONE_CHECK)에서 "통과했는가"를 나중에 조회해야 하기 때문이다.
 *
 * id-card 인증처럼 보안 게이트이므로 FastAPI 호출 실패를 "탐지 안 됨"으로
 * 눙치지 않는다 — 실패를 통과로 처리하면 검사를 우회하는 셈이 된다.
 */
@Injectable()
export class EarphoneDetectionService {
  private readonly logger = new Logger(EarphoneDetectionService.name);

  constructor(
    private readonly examSessionAccessService: ExamSessionAccessService,
    private readonly supabaseService: SupabaseService,
    @Inject(EARPHONE_PROVIDER) private readonly earphoneProvider: EarphoneProviderPort,
  ) {}

  async detect(
    userId: string,
    examSessionId: string,
    leftEarImage: EarphoneImageInput,
    rightEarImage: EarphoneImageInput,
  ): Promise<EarphoneDetectResponseDto> {
    await this.examSessionAccessService.assertOwnedInProgress(examSessionId, userId);

    let result: EarphoneDetectResponseDto;
    try {
      result = await this.earphoneProvider.detect({
        // AI팀 외부 계약상 필드명은 examId지만, 회차가 없어져서 세션 id를 그대로 싣는다.
        examId: examSessionId,
        examineeId: userId,
        leftEarImage,
        rightEarImage,
      });
    } catch (err) {
      this.logger.warn(
        `이어폰 탐지 서비스 통신 실패 (examSessionId=${examSessionId}, userId=${userId}): ${describeError(err)}`,
      );
      throw new ConflictDomainException(
        '이어폰 탐지 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
      );
    }

    const client = this.supabaseService.getAdminClient();
    await client.from('tb_earphone_logs').insert({
      exam_session_id: Number(examSessionId),
      earphone_detected: result.earphoneDetected,
      checked_at: new Date().toISOString(),
    });

    return result;
  }

  /** 게이트 체크(ExamSessionService.assertVerifiedSession)에서 쓰는 통과 여부 조회. */
  async hasPassedCheck(examSessionId: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_earphone_logs')
      .select('earphone_log_id')
      .eq('exam_session_id', Number(examSessionId))
      .eq('earphone_detected', false)
      .limit(1)
      .maybeSingle();

    return data !== null;
  }
}
