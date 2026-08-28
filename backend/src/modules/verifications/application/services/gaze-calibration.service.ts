import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { serviceCommunicationFailed } from '../../../../common/exceptions/error-messages';
import { resolveAntiCheatError } from '../../../../common/exceptions/anti-cheat-error-messages';
import { describeError } from '../../../../common/utils/describe-error.util';
import { extractAntiCheatError } from '../../../../common/utils/extract-anti-cheat-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  CalibrateGazeResult,
  MONITORING_PROVIDER,
  MonitoringImageInput,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import { ExamSessionAccessService } from '../../../exam-session/application/services/exam-session-access.service';
import { GazeCalibrationResponseDto } from '../dto/gaze-calibration-response.dto';

interface GazeCalibrationRow {
  eye_yaw_center: number;
  eye_pitch_center: number;
  head_yaw_center: number;
  head_pitch_center: number;
}

const NEUTRAL_RESULT: GazeCalibrationResponseDto = {
  calibrated: false,
  sampleCount: 0,
  eyeYawCenter: 0,
  eyePitchCenter: 0,
  headYawCenter: 0,
  headPitchCenter: 0,
};

/**
 * 시험 시작 전 시선 캘리브레이션(화면 중앙 응시 이미지 여러 장 → 개인별
 * Eye/Head Yaw·Pitch 기준값). 결과가 있으면 이후 모니터링(부정행위 감지)
 * ANALYZE 요청마다 자동으로 실어 보낸다 — 본인인증 얼굴 사진을 동일인
 * 검사에 자동 재사용하는 것과 같은 패턴이다.
 *
 * 이어폰 감지와 마찬가지로 원본 이미지는 Storage에 올리지 않고 그대로
 * 전달만 한다 — 계산된 기준값 외에는 다시 쓸 일이 없는 일회성 판정이다.
 * anti-cheat의 ANALYZE가 이제 캘리브레이션 기준값 4개를 전부 필수로 요구해서
 * (하나라도 없으면 422), 본인인증/이어폰 확인과 동급의 게이트가 됐다
 * (REQUIRE_GAZE_CALIBRATION, ExamSessionService.assertVerifiedSession 참고).
 *
 * AI팀 모니터링 서비스가 아직 배포되지 않은 기간에는 REQUIRE_MONITORING_SERVICE=false로
 * 통신 실패를 에러 대신 "캘리브레이션 안 됨"으로 조용히 처리할 수 있다(analyze처럼).
 * 기본값은 강제(true, 실패 시 에러) — 실제 서비스 배포 전 반드시 되돌릴 것.
 */
@Injectable()
export class GazeCalibrationService {
  private readonly logger = new Logger(GazeCalibrationService.name);

  constructor(
    private readonly supabaseService: SupabaseService,
    private readonly examSessionAccessService: ExamSessionAccessService,
    @Inject(MONITORING_PROVIDER) private readonly monitoringProvider: MonitoringProviderPort,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async calibrate(
    userId: string,
    examSessionId: string,
    calibrationImages: MonitoringImageInput[],
  ): Promise<GazeCalibrationResponseDto> {
    await this.examSessionAccessService.assertOwnedInProgress(examSessionId, userId);

    let result: CalibrateGazeResult;
    try {
      result = await this.monitoringProvider.calibrate({
        // AI팀 외부 계약상 필드명은 examId지만, 회차가 없어져서 세션 id를 그대로 싣는다.
        examId: examSessionId,
        examineeId: userId,
        calibrationImages,
      });
    } catch (err) {
      this.logger.warn(
        `시선 캘리브레이션 서비스 통신 실패 (examSessionId=${examSessionId}, userId=${userId}): ${describeError(err)}`,
      );
      if (!this.config.requireMonitoringService) {
        return NEUTRAL_RESULT;
      }
      const antiCheatError = extractAntiCheatError(err);
      throw new ConflictDomainException(
        antiCheatError
          ? resolveAntiCheatError(antiCheatError)
          : serviceCommunicationFailed('gaze calibration'),
      );
    }

    if (result.calibrated) {
      const client = this.supabaseService.getAdminClient();
      await client.from('tb_gaze_calibrations').insert({
        exam_session_id: Number(examSessionId),
        eye_yaw_center: result.eyeYawCenter,
        eye_pitch_center: result.eyePitchCenter,
        head_yaw_center: result.headYawCenter,
        head_pitch_center: result.headPitchCenter,
        sample_count: result.sampleCount,
        calibrated_at: new Date().toISOString(),
      });
    }

    return result;
  }

  /**
   * 모니터링(부정행위 감지) ANALYZE 요청에 자동으로 실어 보낼 캘리브레이션 기준값 조회.
   * anti-cheat가 eye/head yaw·pitch 4개를 전부 필수로 요구하므로, 캘리브레이션 기록이
   * 있으면 네 값이 항상 다 있다고 가정한다.
   */
  async getLatestCalibration(examSessionId: string): Promise<{
    eyeYawCenter: number;
    eyePitchCenter: number;
    headYawCenter: number;
    headPitchCenter: number;
  } | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_gaze_calibrations')
      .select('eye_yaw_center, eye_pitch_center, head_yaw_center, head_pitch_center')
      .eq('exam_session_id', Number(examSessionId))
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle<GazeCalibrationRow>();

    if (!data) {
      return null;
    }
    return {
      eyeYawCenter: data.eye_yaw_center,
      eyePitchCenter: data.eye_pitch_center,
      headYawCenter: data.head_yaw_center,
      headPitchCenter: data.head_pitch_center,
    };
  }

  /** 시작 게이트(ExamSessionService.assertVerifiedSession)에서 쓰는 완료 여부 조회. */
  async hasCalibrated(examSessionId: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_gaze_calibrations')
      .select('gaze_calibration_id')
      .eq('exam_session_id', Number(examSessionId))
      .limit(1)
      .maybeSingle();

    return data !== null;
  }
}
