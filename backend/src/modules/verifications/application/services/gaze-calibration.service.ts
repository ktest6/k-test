import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  CalibrateGazeResult,
  MONITORING_PROVIDER,
  MonitoringImageInput,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import { ExamService } from '../../../exam/application/services/exam.service';
import { GazeCalibrationResponseDto } from '../dto/gaze-calibration-response.dto';

interface GazeCalibrationRow {
  eye_yaw_center: number;
  eye_pitch_center: number;
}

const NEUTRAL_RESULT: GazeCalibrationResponseDto = {
  calibrated: false,
  sampleCount: 0,
  eyeYawCenter: 0,
  eyePitchCenter: 0,
};

/**
 * 시험 시작 전 시선 캘리브레이션(화면 중앙 응시 이미지 여러 장 → 개인별
 * Eye Yaw/Pitch 기준값). 결과가 있으면 이후 모니터링(부정행위 감지)
 * ANALYZE 요청마다 자동으로 실어 보낸다 — 본인인증 얼굴 사진을 동일인
 * 검사에 자동 재사용하는 것과 같은 패턴이다.
 *
 * 이어폰 감지와 마찬가지로 원본 이미지는 Storage에 올리지 않고 그대로
 * 전달만 한다 — 계산된 기준값 외에는 다시 쓸 일이 없는 일회성 판정이다.
 * 선택 기능이라(ANALYZE에서 eye_yaw_center/eye_pitch_center는 선택값)
 * 시험 시작을 막는 게이트는 아니다.
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
    private readonly examService: ExamService,
    @Inject(MONITORING_PROVIDER) private readonly monitoringProvider: MonitoringProviderPort,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async calibrate(
    userId: string,
    examId: string,
    calibrationImages: MonitoringImageInput[],
  ): Promise<GazeCalibrationResponseDto> {
    // 존재하는 회차인지 확인(항시 응시 — 신청 여부는 더 이상 확인하지 않는다)
    await this.examService.findById(examId);

    let result: CalibrateGazeResult;
    try {
      result = await this.monitoringProvider.calibrate({
        examId,
        examineeId: userId,
        calibrationImages,
      });
    } catch (err) {
      this.logger.warn(
        `시선 캘리브레이션 서비스 통신 실패 (examId=${examId}, userId=${userId}): ${describeError(err)}`,
      );
      if (!this.config.requireMonitoringService) {
        return NEUTRAL_RESULT;
      }
      throw new ConflictDomainException(
        '시선 캘리브레이션 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
      );
    }

    if (result.calibrated) {
      const client = this.supabaseService.getAdminClient();
      await client.from('tb_gaze_calibrations').insert({
        exam_id: Number(examId),
        user_id: Number(userId),
        eye_yaw_center: result.eyeYawCenter,
        eye_pitch_center: result.eyePitchCenter,
        sample_count: result.sampleCount,
        calibrated_at: new Date().toISOString(),
      });
    }

    return result;
  }

  /** 모니터링(부정행위 감지) ANALYZE 요청에 자동으로 실어 보낼 캘리브레이션 기준값 조회. */
  async getLatestCalibration(
    examId: string,
    userId: string,
  ): Promise<{ eyeYawCenter: number; eyePitchCenter: number } | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_gaze_calibrations')
      .select('eye_yaw_center, eye_pitch_center')
      .eq('exam_id', Number(examId))
      .eq('user_id', Number(userId))
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle<GazeCalibrationRow>();

    if (!data) {
      return null;
    }
    return { eyeYawCenter: data.eye_yaw_center, eyePitchCenter: data.eye_pitch_center };
  }
}
