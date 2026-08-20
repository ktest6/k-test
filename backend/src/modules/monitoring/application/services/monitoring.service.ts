import { randomUUID } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  MONITORING_PROVIDER,
  MonitoringImageInput,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { GazeCalibrationService } from '../../../verifications/application/services/gaze-calibration.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSessionService } from '../../../exam-session/application/services/exam-session.service';
import { ProctoringEvent } from '../../domain/entities/proctoring-event.entity';
import {
  PROCTORING_EVENT_REPOSITORY,
  ProctoringEventRepository,
} from '../../domain/proctoring-event.repository.interface';

const IDENTITY_DOCS_BUCKET = 'identity-docs';

export interface AnalyzeFrameCommand {
  capturedAt: string;
  elapsedMs: number;
  captureSequence: number;
  runIdentityCheck?: boolean;
}

export interface AnalyzeFrameResult {
  severity: string;
  decision: string;
  createClip: boolean;
  eventCount: number;
  recordedEvents: ProctoringEvent[];
}

const NEUTRAL_RESULT: Omit<AnalyzeFrameResult, 'recordedEvents'> = {
  severity: 'NORMAL',
  decision: 'NONE',
  createClip: false,
  eventCount: 0,
};

/**
 * 시험 중 웹캠 프레임을 받아 모니터링(부정행위 감지) 서비스에 분석을
 * 요청하고, 탐지된 이벤트를 tb_proctoring_events에 기록한다. 모니터링
 * 서비스 호출이 실패해도(미배포/타임아웃 등) 응시 화면이 깨지면 안 되므로
 * 에러를 삼키고 "이상 없음"에 준하는 응답을 돌려준다 — 로그로만 남긴다.
 */
@Injectable()
export class MonitoringService {
  private readonly logger = new Logger(MonitoringService.name);

  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly idCardVerificationService: IdCardVerificationService,
    private readonly gazeCalibrationService: GazeCalibrationService,
    private readonly supabaseService: SupabaseService,
    @Inject(MONITORING_PROVIDER) private readonly monitoringProvider: MonitoringProviderPort,
    @Inject(PROCTORING_EVENT_REPOSITORY)
    private readonly proctoringEventRepository: ProctoringEventRepository,
  ) {}

  async analyze(
    examSessionId: string,
    userId: string,
    command: AnalyzeFrameCommand,
    currentImage: { buffer: Buffer; filename: string; contentType: string },
  ): Promise<AnalyzeFrameResult> {
    const session = await this.examSessionService.assertActiveSession(examSessionId, userId);

    let runIdentityCheck = command.runIdentityCheck ?? false;
    let referenceImage: MonitoringImageInput | undefined;
    if (runIdentityCheck) {
      const facePath = await this.idCardVerificationService.getVerifiedFacePath(
        session.examId,
        userId,
      );
      if (facePath) {
        referenceImage = await this.downloadReferenceImage(facePath);
      }
      // 모니터링 서비스 규격상 run_identity_check=true면 reference_image가 필수라,
      // 기준 이미지를 못 찾았거나(경로 없음) 못 받아왔으면(다운로드 실패) 이번
      // 프레임은 동일인 검사 없이 보낸다.
      if (!referenceImage) {
        runIdentityCheck = false;
      }
    }

    const calibration = await this.gazeCalibrationService.getLatestCalibration(
      session.examId,
      userId,
    );

    let result: {
      eventSummary: AnalyzeFrameResult;
      events: { eventType: string; details: Record<string, unknown> }[];
    };
    try {
      const analyzed = await this.monitoringProvider.analyze({
        examId: session.examId,
        examineeId: userId,
        requestId: randomUUID(),
        capturedAt: command.capturedAt,
        elapsedMs: command.elapsedMs,
        captureSequence: command.captureSequence,
        runIdentityCheck,
        currentImage,
        referenceImage,
        eyeYawCenter: calibration?.eyeYawCenter,
        eyePitchCenter: calibration?.eyePitchCenter,
      });
      result = {
        eventSummary: {
          severity: analyzed.eventSummary.severity,
          decision: analyzed.eventSummary.decision,
          createClip: analyzed.eventSummary.createClip,
          eventCount: analyzed.eventSummary.eventCount,
          recordedEvents: [],
        },
        events: analyzed.eventSummary.eventDetected ? analyzed.events : [],
      };
    } catch (err) {
      this.logger.error(
        `모니터링 분석 요청 실패 (examSessionId=${examSessionId}): ${describeError(err)}`,
      );
      return { ...NEUTRAL_RESULT, recordedEvents: [] };
    }

    const severity = result.eventSummary.severity;
    const recordedEvents: ProctoringEvent[] = [];
    if (severity === 'LOW' || severity === 'MEDIUM' || severity === 'HIGH') {
      for (const event of result.events) {
        const saved = await this.proctoringEventRepository.create({
          examSessionId,
          eventType: event.eventType,
          severity: severity,
          meta: event.details,
        });
        recordedEvents.push(saved);
      }
    }

    return { ...result.eventSummary, recordedEvents };
  }

  getEvents(examSessionId: string): Promise<ProctoringEvent[]> {
    return this.proctoringEventRepository.findByExamSessionId(examSessionId);
  }

  private async downloadReferenceImage(path: string): Promise<MonitoringImageInput | undefined> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client.storage.from(IDENTITY_DOCS_BUCKET).download(path);
    if (error || !data) {
      this.logger.warn(`기준 얼굴 이미지 다운로드 실패 (path=${path}): ${error?.message}`);
      return undefined;
    }

    const buffer = Buffer.from(await data.arrayBuffer());
    const filename = path.split('/').pop() ?? 'reference.jpg';
    return { buffer, filename, contentType: data.type || 'image/jpeg' };
  }
}
