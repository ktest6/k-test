import { randomUUID } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  MONITORING_PROVIDER,
  MonitoringDetectedEvent,
  MonitoringImageInput,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { notFound, notOwnedByUser } from '../../../../common/exceptions/error-messages';
import { resolveAntiCheatRuleMessage } from '../../../../common/exceptions/anti-cheat-rule-messages';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  SignedUploadUrl,
  StorageUploadUrlService,
} from '../../../../infrastructure/supabase/storage-upload-url.service';
import { GazeCalibrationService } from '../../../verifications/application/services/gaze-calibration.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSessionService } from '../../../exam-session/application/services/exam-session.service';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import { ProctoringEvent, ProctoringSeverity } from '../../domain/entities/proctoring-event.entity';
import { ClientViolationType } from '../../domain/enums/client-violation-type.enum';
import {
  PROCTORING_EVENT_REPOSITORY,
  ProctoringEventRepository,
} from '../../domain/proctoring-event.repository.interface';
import { ReportViolationDto } from '../dto/report-violation.dto';

const IDENTITY_DOCS_BUCKET = 'identity-docs';
const PROCTORING_SNAPSHOTS_BUCKET = 'proctoring-snapshots';
const PROCTORING_CLIPS_BUCKET = 'proctoring-clips';

const CLIP_EXTENSION_BY_CONTENT_TYPE: Record<string, string> = {
  'video/webm': 'webm',
  'video/mp4': 'mp4',
  'video/quicktime': 'mov',
};

// 자동 실격 정책 초안 — 아직 확정 전이라 비활성 상태(주석)로만 둔다. 활성화하려면
// analyze() 안의 해당 블록 주석을 풀면 된다(추가 배선 필요 없음, 아래 상수만 조정).
// const AUTO_DISQUALIFY_HIGH_THRESHOLD = 3;

/** 프런트 부정행위 방지 플로우 기준 — 종류별 심각도. */
const CLIENT_VIOLATION_SEVERITY: Record<ClientViolationType, ProctoringSeverity> = {
  [ClientViolationType.DUAL_MONITOR]: 'HIGH',
  [ClientViolationType.WINDOW_CLOSE_ATTEMPT]: 'HIGH',
  [ClientViolationType.TAB_SWITCH]: 'MEDIUM',
  [ClientViolationType.PASTE]: 'MEDIUM',
  [ClientViolationType.BLUR]: 'LOW',
  [ClientViolationType.MOUSE_LEAVE]: 'LOW',
};

/**
 * 종류별로 이 횟수만큼 누적되면 자동으로 실격 처리한다(프런트 부정행위 방지 플로우 기준).
 * DUAL_MONITOR는 정상적인 시험 환경에서 나올 수 없는 명백한 부정행위 정황이라 1회만으로
 * 즉시 실격, 나머지는 오탐 여지가 있어 2회부터 실격한다.
 */
const CLIENT_VIOLATION_DISQUALIFY_THRESHOLD: Record<ClientViolationType, number> = {
  [ClientViolationType.DUAL_MONITOR]: 1,
  [ClientViolationType.WINDOW_CLOSE_ATTEMPT]: 2,
  [ClientViolationType.TAB_SWITCH]: 2,
  [ClientViolationType.PASTE]: 2,
  [ClientViolationType.BLUR]: 2,
  [ClientViolationType.MOUSE_LEAVE]: 2,
};

/** 실격 안내 메일(영문)에 실릴, 위반 종류별 사람이 읽을 수 있는 사유 문구. */
const CLIENT_VIOLATION_LABEL: Record<ClientViolationType, string> = {
  [ClientViolationType.TAB_SWITCH]: 'switching to another browser tab',
  [ClientViolationType.BLUR]: 'leaving the exam window focus',
  [ClientViolationType.WINDOW_CLOSE_ATTEMPT]: 'attempting to close the exam window',
  [ClientViolationType.MOUSE_LEAVE]: 'moving the mouse outside the exam screen',
  [ClientViolationType.PASTE]: 'pasting content into an answer',
  [ClientViolationType.DUAL_MONITOR]: 'using a dual-monitor setup',
};

export interface AnalyzeFrameCommand {
  capturedAt: string;
  elapsedMs: number;
  captureSequence: number;
  runIdentityCheck?: boolean;
}

export interface ReportViolationResult {
  event: ProctoringEvent;
  /** 이 위반 신고를 처리한 직후의 세션 상태 — DISQUALIFIED면 프런트가 바로 결과 화면으로 전환하면 된다. */
  sessionStatus: SessionStatus;
}

export interface AnalyzeFrameResult {
  severity: string;
  decision: string;
  createClip: boolean;
  eventCount: number;
  recordedEvents: ProctoringEvent[];
  /** 이번 요청에서 동일인 검사를 실제로 요청했는지. */
  identityCheckRequested: boolean;
  /**
   * 동일인 검사가 실제로 실행됐는지 — requested가 true여도 얼굴이 0명/여러 명이면
   * false가 될 수 있다. false면 프런트가 다음 프레임에서 같은 기준 이미지로
   * run_identity_check:true를 다시 요청해야 한다.
   */
  identityCheckExecuted: boolean;
}

const NEUTRAL_RESULT: Omit<AnalyzeFrameResult, 'recordedEvents'> = {
  severity: 'NORMAL',
  decision: 'NONE',
  createClip: false,
  eventCount: 0,
  identityCheckRequested: false,
  identityCheckExecuted: false,
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
    private readonly storageUploadUrlService: StorageUploadUrlService,
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
    const session = await this.examSessionService.assertVerifiedSession(examSessionId, userId);

    let runIdentityCheck = command.runIdentityCheck ?? false;
    let referenceImage: MonitoringImageInput | undefined;
    if (runIdentityCheck) {
      const facePath = await this.idCardVerificationService.getVerifiedFacePath(session.id);
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

    const calibration = await this.gazeCalibrationService.getLatestCalibration(session.id);
    if (!calibration) {
      // anti-cheat가 eye/head yaw·pitch 4개를 전부 필수로 요구해서, 캘리브레이션이
      // 없으면 호출 자체가 무조건 422로 실패한다 — 요청을 보내지 않고 조용히
      // "이상 없음"으로 처리한다(REQUIRE_GAZE_CALIBRATION=false로 게이트를 꺼둔
      // 과도기, 또는 캘리브레이션 API 호출 전 프런트가 먼저 analyze를 부른 경우).
      this.logger.warn(
        `시선 캘리브레이션 기록 없음, 모니터링 분석 건너뜀 (examSessionId=${examSessionId})`,
      );
      return { ...NEUTRAL_RESULT, recordedEvents: [] };
    }

    const previousGazeState = await this.getGazeState(examSessionId);

    let result: {
      eventSummary: AnalyzeFrameResult;
      events: MonitoringDetectedEvent[];
    };
    try {
      const analyzed = await this.monitoringProvider.analyze({
        // AI팀 외부 계약상 필드명은 examId지만, 회차가 없어져서 세션 id를 그대로 싣는다.
        examId: session.id,
        examineeId: userId,
        requestId: randomUUID(),
        capturedAt: command.capturedAt,
        elapsedMs: command.elapsedMs,
        captureSequence: command.captureSequence,
        runIdentityCheck,
        currentImage,
        referenceImage,
        eyeYawCenter: calibration.eyeYawCenter,
        eyePitchCenter: calibration.eyePitchCenter,
        headYawCenter: calibration.headYawCenter,
        headPitchCenter: calibration.headPitchCenter,
        previousGazeState,
      });
      await this.saveGazeState(examSessionId, analyzed.gazeState);
      result = {
        eventSummary: {
          severity: analyzed.eventSummary.severity,
          decision: analyzed.eventSummary.decision,
          createClip: analyzed.eventSummary.createClip,
          eventCount: analyzed.eventSummary.eventCount,
          recordedEvents: [],
          identityCheckRequested: analyzed.identityCheckRequested,
          identityCheckExecuted: analyzed.identityCheckExecuted,
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
      // 위반이 감지된 프레임만 스냅샷으로 남긴다 — 매 프레임을 다 저장하면 스토리지
      // 비용이 크게 늘어난다. 업로드 실패는 이벤트 기록 자체를 막을 이유가 아니라
      // snapshotPath만 null로 남긴다.
      const snapshotPath = await this.uploadSnapshot(examSessionId, currentImage);

      for (const event of result.events) {
        // 개별 이벤트는 자기 자신의 severity를 쓴다(프레임 전체 최고 severity와
        // 다를 수 있다) — ruleId/decision/message는 별도 컬럼 없이 meta에 details와
        // 함께 담는다(집계·필터링은 severity 컬럼만으로 충분하므로 마이그레이션 불필요).
        const saved = await this.proctoringEventRepository.create({
          examSessionId,
          eventType: event.eventType,
          severity: event.severity === 'NORMAL' ? severity : event.severity,
          meta: {
            ...event.details,
            ruleId: event.ruleId,
            decision: event.decision,
            message: resolveAntiCheatRuleMessage(event.ruleId, event.message),
          },
          snapshotPath,
        });
        recordedEvents.push(saved);
      }

      // 자동 실격 정책 초안(비활성) — 정책 확정 전까지 주석 처리. 활성화하려면
      // 파일 상단의 AUTO_DISQUALIFY_HIGH_THRESHOLD 상수 주석도 함께 풀 것.
      // if (severity === 'HIGH') {
      //   const events = await this.proctoringEventRepository.findByExamSessionId(examSessionId);
      //   const highCount = events.filter((e) => e.severity === 'HIGH').length;
      //   if (highCount >= AUTO_DISQUALIFY_HIGH_THRESHOLD) {
      //     await this.examSessionService.disqualify(examSessionId, 'AI monitoring — repeated high-risk cheating detected');
      //   }
      // }
    }

    return { ...result.eventSummary, recordedEvents };
  }

  /**
   * AI 모니터링(analyze)과 별개로, 프런트가 브라우저 이벤트(탭 이탈/포커스
   * 이탈/붙여넣기/듀얼 모니터 등)로 직접 감지한 위반을 기록한다. 웹캠 프레임이
   * 없는 신호라 스냅샷은 남기지 않는다. 같은 violationType이 종류별 정해진
   * 횟수(CLIENT_VIOLATION_DISQUALIFY_THRESHOLD, DUAL_MONITOR는 1회·나머지는
   * 2회)만큼 누적되면 자동 실격 — 종류별로 각각 따로 센다(예: TAB_SWITCH 1회 +
   * BLUR 1회는 합산되지 않음). 응답에 처리 직후의 세션 상태를 같이 실어줘서,
   * 프런트가 이 호출 하나로 "방금
   * 실격됐는지"까지 바로 알 수 있게 한다(별도 상태 조회 필요 없음).
   */
  async reportViolation(
    examSessionId: string,
    userId: string,
    dto: ReportViolationDto,
  ): Promise<ReportViolationResult> {
    const session = await this.examSessionService.assertActiveSession(examSessionId, userId);

    const saved = await this.proctoringEventRepository.create({
      examSessionId,
      eventType: dto.violationType,
      severity: CLIENT_VIOLATION_SEVERITY[dto.violationType],
      meta: dto.meta ?? {},
      snapshotPath: null,
    });

    let sessionStatus = session.status;
    const events = await this.proctoringEventRepository.findByExamSessionId(examSessionId);
    const violationEventType: string = dto.violationType;
    const violationCount = events.filter((event) => event.eventType === violationEventType).length;
    if (violationCount >= CLIENT_VIOLATION_DISQUALIFY_THRESHOLD[dto.violationType]) {
      const timeWord = violationCount === 1 ? 'time' : 'times';
      const reason = `Anti-cheating policy violation — ${CLIENT_VIOLATION_LABEL[dto.violationType]} was detected ${violationCount} ${timeWord}.`;
      const disqualified = await this.examSessionService.disqualify(examSessionId, reason);
      sessionStatus = disqualified.status;
    }

    return { event: saved, sessionStatus };
  }

  getEvents(examSessionId: string): Promise<ProctoringEvent[]> {
    return this.proctoringEventRepository.findByExamSessionId(examSessionId);
  }

  /**
   * AI가 createClip:true로 판단한 순간의 웹캠 영상 클립을 올릴 signed URL 발급.
   * 실제 녹화·버퍼링은 프런트가 하고(백엔드는 프레임 정지 이미지만 받으므로 영상
   * 자체를 만들 수 없다), 그 결과 파일을 여기로 올린 뒤 attachClip으로 이벤트에
   * 연결한다. 경로는 서버가 정해서 발급 단계부터 바꿔치기를 막는다.
   */
  async createClipUploadUrl(
    examSessionId: string,
    userId: string,
    eventId: string,
    contentType: string,
  ): Promise<SignedUploadUrl> {
    await this.assertOwnedEvent(examSessionId, userId, eventId);

    const extension = CLIP_EXTENSION_BY_CONTENT_TYPE[contentType];
    const path = `${userId}/${examSessionId}/${eventId}.${extension}`;

    return this.storageUploadUrlService.createSignedUploadUrl(PROCTORING_CLIPS_BUCKET, path, {
      upsert: true,
    });
  }

  /** 업로드가 끝난 영상 클립 경로를 해당 이벤트 로그에 연결한다. */
  async attachClip(
    examSessionId: string,
    userId: string,
    eventId: string,
    clipPath: string,
  ): Promise<ProctoringEvent> {
    await this.assertOwnedEvent(examSessionId, userId, eventId);

    const expectedPrefix = `${userId}/${examSessionId}/`;
    if (!clipPath.startsWith(expectedPrefix)) {
      throw new ForbiddenDomainException(notOwnedByUser("session's clip path"));
    }

    return this.proctoringEventRepository.updateClipPath(eventId, clipPath);
  }

  /** 이벤트가 실제로 이 세션 소속인지, 그 세션이 이 사용자 소유인지 확인한다. */
  private async assertOwnedEvent(
    examSessionId: string,
    userId: string,
    eventId: string,
  ): Promise<void> {
    await this.examSessionService.getStatus(examSessionId, userId);

    const event = await this.proctoringEventRepository.findById(eventId);
    if (!event || event.examSessionId !== examSessionId) {
      throw new NotFoundDomainException(notFound('Monitoring event', eventId));
    }
  }

  private async uploadSnapshot(
    examSessionId: string,
    image: { buffer: Buffer; contentType: string },
  ): Promise<string | null> {
    const client = this.supabaseService.getAdminClient();
    const path = `${examSessionId}/${Date.now()}-${randomUUID()}.jpg`;
    const { error } = await client.storage
      .from(PROCTORING_SNAPSHOTS_BUCKET)
      .upload(path, image.buffer, { contentType: image.contentType });
    if (error) {
      this.logger.warn(
        `부정행위 스냅샷 업로드 실패 (examSessionId=${examSessionId}): ${error.message}`,
      );
      return null;
    }
    return path;
  }

  /**
   * FastAPI는 연속 시선 상태를 메모리에 들고 있지 않으므로(무상태), 세션별
   * 최신 상태를 우리가 tb_exam_session.gaze_state에 저장했다가 다음 analyze
   * 요청에 previous_gaze_state로 그대로 돌려준다.
   */
  private async getGazeState(examSessionId: string): Promise<Record<string, unknown> | undefined> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('tb_exam_session')
      .select('gaze_state')
      .eq('exam_session_id', Number(examSessionId))
      .maybeSingle<{ gaze_state: Record<string, unknown> | null }>();

    return data?.gaze_state ?? undefined;
  }

  private async saveGazeState(
    examSessionId: string,
    gazeState: Record<string, unknown> | null,
  ): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    const { error } = await client
      .from('tb_exam_session')
      .update({ gaze_state: gazeState })
      .eq('exam_session_id', Number(examSessionId));

    if (error) {
      this.logger.warn(`시선 상태 저장 실패 (examSessionId=${examSessionId}): ${error.message}`);
    }
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
