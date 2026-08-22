import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';
import { ExamService } from '../../../exam/application/services/exam.service';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamStatus } from '../../../exam/domain/enums/exam-status.enum';
import { computeExamStatus, isApplicationOpen } from '../../../exam/domain/exam-status.util';
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

/** 마감 임박(1시간 이내)에는 새로 시작할 수 없다 — 응시자가 사실상 완주할 수 없는 시간에 시작하는 걸 막는다. */
const START_BUFFER_BEFORE_CLOSE_MS = 60 * 60 * 1000;

export interface ExamSessionStatusResult {
  session: ExamSession;
  status: SessionStatus;
}

/**
 * 마이페이지 "내 시험 현황" 한 줄. 세션을 시작한 적 있으면 그 세션의 id/상태/제출일시.
 * 시작한 적 없고 마감 1시간 전(START_BUFFER_BEFORE_CLOSE_MS) 시작 데드라인도
 * 지났으면 id는 null, status는 EXPIRED — 신청만 하고 응시 기회를 놓친 경우다.
 * 그 외(아직 시작 데드라인 전)엔 session 자체가 null. examResultId/finalGrade는
 * 최종 리포트(/finalize)가 아직 안 나왔으면(채점 중이거나 세션이 없으면) 둘 다 null이다.
 */
export interface MyExamStatus {
  exam: Exam;
  examStatus: ExamStatus;
  appliedAt: Date;
  session: { id: string | null; status: SessionStatus; submittedAt: Date | null } | null;
  examResultId: string | null;
  finalGrade: string | null;
}

/**
 * "오늘 응시 가능한 시험" 한 줄 — 신청해서 아직 안 끝난(응시전/진행중) 시험 +
 * 아직 신청 안 했지만 신청 기간이 열려 있고 정원도 안 찬 시험. isApplied로 프런트가
 * "이어서 풀기"/"신청하기" 버튼을 구분한다.
 */
export interface AvailableExam {
  exam: Exam;
  isApplied: boolean;
  session: { id: string; status: SessionStatus } | null;
}

@Injectable()
export class ExamSessionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examService: ExamService,
    private readonly examApplicationService: ExamApplicationService,
    private readonly idCardVerificationService: IdCardVerificationService,
    private readonly earphoneDetectionService: EarphoneDetectionService,
    private readonly examResultService: ExamResultService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async start(examId: string, userId: string): Promise<ExamSession> {
    const exam = await this.examService.findById(examId);

    if (computeExamStatus(exam.openAt, exam.closeAt) !== ExamStatus.OPEN) {
      throw new ConflictDomainException('지금은 응시 기간이 아닙니다.');
    }

    const applied = await this.examApplicationService.hasActiveApplication(examId, userId);
    if (!applied) {
      throw new ForbiddenDomainException('신청한 회차가 아닙니다.');
    }

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

    if (exam.closeAt.getTime() - Date.now() < START_BUFFER_BEFORE_CLOSE_MS) {
      throw new ConflictDomainException('마감 1시간 전에는 새로 시작할 수 없습니다.');
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

  /**
   * 마이페이지 "내 시험 현황" — 신청한 회차별로 세션 상태를 함께 내려준다. 세션을
   * 시작한 적 있으면 그 상태 그대로, 시작한 적 없고 마감 1시간 전 시작 데드라인도
   * 지났으면 EXPIRED(신청만 하고 응시 기회를 놓친 경우), 그 전이면 null이다.
   */
  async listMine(userId: string): Promise<MyExamStatus[]> {
    const applications = await this.examApplicationService.listMine(userId);

    return Promise.all(
      applications.map(async (application) => {
        const [exam, session] = await Promise.all([
          this.examService.findById(application.examId),
          this.examSessionRepository.findByUserAndExam(userId, application.examId),
        ]);

        let sessionSummary: {
          id: string | null;
          status: SessionStatus;
          submittedAt: Date | null;
        } | null;
        if (session) {
          sessionSummary = {
            id: session.id,
            status: session.status,
            submittedAt: session.submittedAt,
          };
        } else if (exam.closeAt.getTime() - Date.now() < START_BUFFER_BEFORE_CLOSE_MS) {
          sessionSummary = { id: null, status: SessionStatus.EXPIRED, submittedAt: null };
        } else {
          sessionSummary = null;
        }

        const examResult = session
          ? await this.examResultService.findByExamSessionId(session.id)
          : null;

        return {
          exam,
          examStatus: computeExamStatus(exam.openAt, exam.closeAt),
          appliedAt: application.appliedAt,
          session: sessionSummary,
          examResultId: examResult?.id ?? null,
          finalGrade: examResult?.finalGrade ?? null,
        };
      }),
    );
  }

  /**
   * "오늘 응시 가능한 시험" — 신청해서 아직 안 끝난(세션 없음 또는 INPROGRESS) 시험과,
   * 아직 신청 안 했지만 지금 신청할 수 있는(신청 기간 내 + 정원 여유) 시험을 합쳐서 준다.
   * 이미 SUBMITTED/EXPIRED/DISQUALIFIED/BLOCKED인, 응시자 입장에서 더 할 게 없는 신청
   * 건은 제외한다.
   *
   * userId가 null이면(비로그인) "신청 가능한 시험"만 준다 — 누구 신청 내역인지 알 수
   * 없으니 isApplied는 항상 false, session은 항상 null이다.
   */
  async listAvailable(userId: string | null): Promise<AvailableExam[]> {
    const [applications, allExams] = await Promise.all([
      userId ? this.examApplicationService.listMine(userId) : Promise.resolve([]),
      this.examService.list(),
    ]);

    const applicationByExamId = new Map(
      applications.map((application) => [application.examId, application]),
    );

    const results = await Promise.all(
      allExams.map(async (exam): Promise<AvailableExam | null> => {
        const application = userId ? applicationByExamId.get(exam.id) : undefined;
        if (application && userId) {
          const session = await this.examSessionRepository.findByUserAndExam(userId, exam.id);
          if (session && session.status !== SessionStatus.INPROGRESS) {
            return null;
          }
          return {
            exam,
            isApplied: true,
            session: session ? { id: session.id, status: session.status } : null,
          };
        }

        if (!isApplicationOpen(exam.applicationOpenAt, exam.applicationCloseAt)) {
          return null;
        }
        const activeCount = await this.examApplicationService.countActive(exam.id);
        if (activeCount >= exam.capacity) {
          return null;
        }
        return { exam, isApplied: false, session: null };
      }),
    );

    return results.filter((result): result is AvailableExam => result !== null);
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
