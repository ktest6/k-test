import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamService } from '../../../exam/application/services/exam.service';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { EarphoneDetectionService } from '../../../verifications/application/services/earphone-detection.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';

/** 재개(재시작) 시도가 이 횟수에 도달하면 세션을 BLOCKED로 전환하고 더 이상 진행을 막는다. */
const RESUME_ATTEMPT_LIMIT = 3;

export interface ExamSessionStatusResult {
  session: ExamSession;
  status: SessionStatus;
}

/**
 * 마이페이지 "내 시험 현황" 한 줄 — 이 사용자가 시작한 적 있는 세션 하나에 대응된다.
 * 항시 응시 체제라 "신청만 하고 시작 안 함" 같은 중간 상태가 없다 — 목록에 있다는
 * 것 자체가 세션을 시작했다는 뜻이라 session은 항상 값이 있다. examResultId/
 * finalGrade는 최종 리포트(/finalize)가 아직 안 나왔으면(채점 중이거나 재시도
 * 대기중이면) 둘 다 null이다.
 */
export interface MyExamStatus {
  exam: Exam;
  session: { id: string; status: SessionStatus; startedAt: Date; submittedAt: Date | null };
  examResultId: string | null;
  finalGrade: string | null;
}

/**
 * "지금 응시 가능한 시험" 한 줄 — 전체 회차 목록에 이 사용자의 세션 상태를 얹어서
 * 준다(정원/신청기간 없음, 항시 응시). session이 없으면 아직 시작한 적 없다는
 * 뜻. canStart는 "지금 이 시험을 새로 시작할 수 있는가"로, 이미 이 시험 세션이
 * 있거나(재개는 SESSION-01을 그대로 다시 호출하면 되고 이 필드와 무관) 다른
 * 시험이 이미 INPROGRESS면 false다. userId가 null이면(비로그인) 판단할 수 없어
 * session/canStart 둘 다 null이다.
 */
export interface AvailableExam {
  exam: Exam;
  session: { id: string; status: SessionStatus } | null;
  canStart: boolean | null;
}

@Injectable()
export class ExamSessionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examService: ExamService,
    private readonly idCardVerificationService: IdCardVerificationService,
    private readonly earphoneDetectionService: EarphoneDetectionService,
    private readonly examResultService: ExamResultService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async start(examId: string, userId: string): Promise<ExamSession> {
    await this.examService.findById(examId);

    // AI팀 본인인증 서비스가 아직 배포되지 않은 기간 한정으로 REQUIRE_IDENTITY_VERIFICATION=false
    // 로 이 게이트를 임시 우회할 수 있다. 기본값은 강제(true) — 실제 서비스 배포 전 반드시 되돌릴 것.
    if (this.config.requireIdentityVerification) {
      const verified = await this.idCardVerificationService.hasVerifiedExam(examId, userId);
      if (!verified) {
        throw new ForbiddenDomainException('본인인증을 먼저 완료해야 합니다.');
      }
    }

    // requireIdentityVerification과 같은 이유(AI팀 서비스 미배포 기간)로 임시 우회 가능.
    // 기본값은 강제(true) — 실제 서비스 배포 전 반드시 되돌릴 것.
    if (this.config.requireEarphoneCheck) {
      const earphoneCheckPassed = await this.earphoneDetectionService.hasPassedCheck(
        examId,
        userId,
      );
      if (!earphoneCheckPassed) {
        throw new ForbiddenDomainException('이어폰 미착용 확인을 먼저 완료해야 합니다.');
      }
    }

    const existing = await this.examSessionRepository.findByUserAndExam(userId, examId);
    if (existing) {
      // 중간에 끊겼다가 다시 "시작"을 누른 경우 — 새로 만들지 않고 같은 세션을 이어서 준다.
      // 다만 반복 재접속은 악용(예: 준비/응답 시간 리셋 시도) 신호로 보고 횟수를 제한한다.
      if (existing.status === SessionStatus.INPROGRESS) {
        const nextResumeCount = existing.resumeCount + 1;
        if (nextResumeCount >= RESUME_ATTEMPT_LIMIT) {
          await this.examSessionRepository.updateStatus(existing.id, SessionStatus.BLOCKED);
          throw new ForbiddenDomainException('반복적인 재접속으로 시험 응시가 제한되었습니다.');
        }
        return this.examSessionRepository.updateResumeCount(existing.id, nextResumeCount);
      }
      throw new ConflictDomainException('이미 종료된 시험입니다.');
    }

    // 항시 응시 체제의 유일한 시작 제약 — 한 번에 한 시험만. 이 회차에 세션이
    // 없다는 건 위에서 이미 확인했으니, 여기서 걸리는 건 반드시 "다른" 회차의
    // INPROGRESS 세션이다.
    const inProgressElsewhere = await this.examSessionRepository.findInProgressByUser(userId);
    if (inProgressElsewhere) {
      throw new ConflictDomainException('이미 진행 중인 다른 시험이 있어 새로 시작할 수 없습니다.');
    }

    return this.examSessionRepository.create({ examId, userId });
  }

  async getStatus(examSessionId: string, userId: string): Promise<ExamSessionStatusResult> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }

    // 세션이 더 이상 진행중이 아니게 된 시점에 본인인증용 얼굴 이미지를 정리한다.
    // 채점 완료 여부와는 무관 — 얼굴 사진은 채점이 아니라 시험 중 모니터링의
    // 동일인 검사에만 쓰였으므로, 세션이 끝나는 순간 더 이상 쓸모가 없다.
    // 멱등한 정리라 상태 조회가 반복돼도 안전하다.
    if (session.status !== SessionStatus.INPROGRESS) {
      await this.idCardVerificationService.cleanupVerifiedFaceImage(session.examId, userId);
    }

    return { session, status: session.status };
  }

  /** 마이페이지 "내 시험 현황" — 이 사용자가 시작한 적 있는 세션들을 회차 정보와 함께 내려준다. */
  async listMine(userId: string): Promise<MyExamStatus[]> {
    const sessions = await this.examSessionRepository.findAllByUser(userId);

    return Promise.all(
      sessions.map(async (session) => {
        const [exam, examResult] = await Promise.all([
          this.examService.findById(session.examId),
          this.examResultService.findByExamSessionId(session.id),
        ]);

        return {
          exam,
          session: {
            id: session.id,
            status: session.status,
            startedAt: session.startedAt,
            submittedAt: session.submittedAt,
          },
          examResultId: examResult?.id ?? null,
          finalGrade: examResult?.finalGrade ?? null,
        };
      }),
    );
  }

  /**
   * "지금 응시 가능한 시험" — 전체 회차 목록에 이 사용자의 세션 상태를 얹어서 준다.
   * userId가 null이면(비로그인) 세션/canStart를 판단할 수 없어 전부 null로 준다.
   */
  async listAvailable(userId: string | null): Promise<AvailableExam[]> {
    const [allExams, inProgressElsewhere] = await Promise.all([
      this.examService.list(),
      userId ? this.examSessionRepository.findInProgressByUser(userId) : Promise.resolve(null),
    ]);

    return Promise.all(
      allExams.map(async (exam): Promise<AvailableExam> => {
        if (!userId) {
          return { exam, session: null, canStart: null };
        }

        const session = await this.examSessionRepository.findByUserAndExam(userId, exam.id);
        const hasOtherInProgress =
          inProgressElsewhere !== null && inProgressElsewhere.examId !== exam.id;

        return {
          exam,
          session: session ? { id: session.id, status: session.status } : null,
          canStart: !session && !hasOtherInProgress,
        };
      }),
    );
  }

  /** 답안 저장처럼 "지금 실제로 응시 중"이어야만 허용되는 동작들의 공통 게이트. */
  async assertActiveSession(examSessionId: string, userId: string): Promise<ExamSession> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('세션 소유자가 아닙니다.');
    }
    if (session.status !== SessionStatus.INPROGRESS) {
      throw new ConflictDomainException('이미 종료된 시험입니다.');
    }

    return session;
  }

  /**
   * 부정행위로 판단돼 세션을 실격 처리한다. 모니터링(듀얼 모니터 반복 감지 등)이
   * 자동으로 부르기도 하고, 관리자가 검토 후 수동으로 부르기도 한다(관리자 전용
   * 엔드포인트 참고). 이미 끝난 세션(SUBMITTED)은 실격으로 덮어쓰지 않는다 —
   * 이미 제출된 응시 결과를 뒤집을 이유가 없다. BLOCKED/이미 DISQUALIFIED된
   * 세션에 다시 걸어도 멱등하게 처리한다.
   */
  async disqualify(examSessionId: string): Promise<ExamSession> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(`응시 세션(${examSessionId})을 찾을 수 없습니다.`);
    }
    if (session.status === SessionStatus.DISQUALIFIED) {
      return session;
    }
    if (session.status === SessionStatus.SUBMITTED) {
      throw new ConflictDomainException(
        `응시 세션(${examSessionId})은 이미 종료되어 실격시킬 수 없습니다.`,
      );
    }

    return this.examSessionRepository.updateStatus(examSessionId, SessionStatus.DISQUALIFIED);
  }
}
