import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { serviceCommunicationFailed } from '../../../../common/exceptions/error-messages';
import { resolveAntiCheatError } from '../../../../common/exceptions/anti-cheat-error-messages';
import { describeError } from '../../../../common/utils/describe-error.util';
import { extractAntiCheatError } from '../../../../common/utils/extract-anti-cheat-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  DetectEarphoneResult,
  EARPHONE_PROVIDER,
  EarphoneImageInput,
  EarphoneProviderPort,
} from '../../../ai/domain/ports/earphone-provider.port';
import { ExamSessionAccessService } from '../../../exam-session/application/services/exam-session-access.service';
import { EarphoneDetectResponseDto } from '../dto/earphone-detect-response.dto';

/**
 * anti-cheat의 message 필드는 아직 한국어 자유 문장이라(오류 코드처럼 code+params로
 * 안 옴) 그대로 번역하지 않고, 우리가 이미 구조화된 필드(inspectionComplete/
 * leftEarVisible/rightEarVisible/earphoneDetected)로 직접 영어 안내 문구를 만든다 —
 * anti-cheat 쪽 문구가 바뀌어도 이 안내는 안 깨진다.
 */
function buildGuidanceMessage(result: DetectEarphoneResult): string {
  if (!result.inspectionComplete) {
    if (!result.leftEarVisible && !result.rightEarVisible) {
      return 'Turn your face sideways so both ears are visible.';
    }
    if (!result.leftEarVisible) {
      return 'Turn your face to show your left ear.';
    }
    return 'Turn your face to show your right ear.';
  }
  return result.earphoneDetected
    ? 'An earphone was detected. Please remove it before continuing.'
    : 'No earphone was detected.';
}

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

    let result: DetectEarphoneResult;
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
      const antiCheatError = extractAntiCheatError(err);
      throw new ConflictDomainException(
        antiCheatError
          ? resolveAntiCheatError(antiCheatError)
          : serviceCommunicationFailed('earphone detection'),
      );
    }

    const client = this.supabaseService.getAdminClient();
    await client.from('tb_earphone_logs').insert({
      exam_session_id: Number(examSessionId),
      earphone_detected: result.earphoneDetected,
      inspection_complete: result.inspectionComplete,
      checked_at: new Date().toISOString(),
    });

    return { ...result, message: buildGuidanceMessage(result) };
  }

  /**
   * 게이트 체크(ExamSessionService.assertVerifiedSession)에서 쓰는 통과 여부 조회.
   * inspection_complete가 true인 판정만 인정한다 — 자세 문제로 검사가 불완전했던
   * 판정은 earphone_detected=false가 나와도 신뢰할 수 없기 때문이다.
   */
  async hasPassedCheck(examSessionId: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_earphone_logs')
      .select('earphone_log_id')
      .eq('exam_session_id', Number(examSessionId))
      .eq('earphone_detected', false)
      .eq('inspection_complete', true)
      .limit(1)
      .maybeSingle();

    return data !== null;
  }
}
