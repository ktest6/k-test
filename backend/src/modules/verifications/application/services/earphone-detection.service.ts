import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  EARPHONE_PROVIDER,
  EarphoneImageInput,
  EarphoneProviderPort,
} from '../../../ai/domain/ports/earphone-provider.port';
import { EarphoneDetectResponseDto } from '../dto/earphone-detect-response.dto';
import { ExamAccessService } from './exam-access.service';

/**
 * 시험 시작 전 이어폰 착용 여부 감지. id-card 인증과 마찬가지로 세션이
 * 생기기 전에 끝나야 하므로 신청 여부만 확인한다. 이미지는 다른 인증
 * 흐름처럼 Storage에 올리지 않고 요청에 그대로 실어 보낸다 — 감사용으로
 * 남겨야 할 필요가 없는 일회성 판정이라 저장 없이 바로 전달만 한다.
 * 판정 "결과"는 남긴다 — 시험 시작 게이트(ExamSessionService.start(),
 * REQUIRE_EARPHONE_CHECK)에서 "통과했는가"를 나중에 조회해야 하기 때문이다.
 *
 * id-card 인증처럼 보안 게이트이므로 FastAPI 호출 실패를 "탐지 안 됨"으로
 * 눙치지 않는다 — 실패를 통과로 처리하면 검사를 우회하는 셈이 된다.
 */
@Injectable()
export class EarphoneDetectionService {
  private readonly logger = new Logger(EarphoneDetectionService.name);

  constructor(
    private readonly examAccessService: ExamAccessService,
    private readonly supabaseService: SupabaseService,
    @Inject(EARPHONE_PROVIDER) private readonly earphoneProvider: EarphoneProviderPort,
  ) {}

  async detect(
    userId: string,
    examId: string,
    leftEarImage: EarphoneImageInput,
    rightEarImage: EarphoneImageInput,
  ): Promise<EarphoneDetectResponseDto> {
    await this.examAccessService.assertApplied(userId, examId);

    let result: EarphoneDetectResponseDto;
    try {
      result = await this.earphoneProvider.detect({
        examId,
        examineeId: userId,
        leftEarImage,
        rightEarImage,
      });
    } catch (err) {
      this.logger.warn(
        `이어폰 탐지 서비스 통신 실패 (examId=${examId}, userId=${userId}): ${describeError(err)}`,
      );
      throw new ConflictDomainException(
        '이어폰 탐지 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
      );
    }

    const client = this.supabaseService.getAdminClient();
    await client.from('tb_earphone_logs').insert({
      exam_id: Number(examId),
      user_id: Number(userId),
      earphone_detected: result.earphoneDetected,
      checked_at: new Date().toISOString(),
    });

    return result;
  }

  /** 시험 시작 전 게이트 체크(ExamSessionService.start)에서 쓰는 통과 여부 조회. */
  async hasPassedCheck(examId: string, userId: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_earphone_logs')
      .select('earphone_log_id')
      .eq('exam_id', Number(examId))
      .eq('user_id', Number(userId))
      .eq('earphone_detected', false)
      .limit(1)
      .maybeSingle();

    return data !== null;
  }
}
