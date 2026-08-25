import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { notFound, notOwnedByUser } from '../../../../common/exceptions/error-messages';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { EarphoneDetectionService } from '../../../verifications/application/services/earphone-detection.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import {
  EXAM_SESSION_REPOSITORY,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';
import { ExamSessionAccessService } from './exam-session-access.service';

/** 재개(재시작) 시도가 이 횟수에 도달하면 세션을 BLOCKED로 전환하고 더 이상 진행을 막는다. */
const RESUME_ATTEMPT_LIMIT = 3;

export interface ExamSessionStatusResult {
  session: ExamSession;
  status: SessionStatus;
}

/**
 * 마이페이지 "내 시험 현황" 한 줄 — 이 사용자가 시작한 적 있는 세션 하나에 대응된다.
 * 회차(Exam)가 없어졌고 같은 시험을 여러 번 볼 수 있어서, 목록에 세션이 여러 개
 * 있을 수 있다(전부 같은 시험). examResultId/finalGrade는 최종 리포트(/finalize)가
 * 아직 안 나왔으면(채점 중이거나 재시도 대기중) 둘 다 null이다.
 */
export interface MyExamStatus {
  session: { id: string; status: SessionStatus; startedAt: Date; submittedAt: Date | null };
  examResultId: string | null;
  finalGrade: string | null;
}

@Injectable()
export class ExamSessionService {
  constructor(
    @Inject(EXAM_SESSION_REPOSITORY) private readonly examSessionRepository: ExamSessionRepository,
    private readonly examSessionAccessService: ExamSessionAccessService,
    private readonly idCardVerificationService: IdCardVerificationService,
    private readonly earphoneDetectionService: EarphoneDetectionService,
    private readonly examResultService: ExamResultService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  /**
   * 회차(Exam) 선택이 없다 — "응시하기"는 항상 이 API 하나다. 이미 진행중인
   * 세션이 있으면 재개로 처리하고, 없으면 새 세션을 만든다. 본인인증/이어폰
   * 확인은 여기서 보지 않는다 — 세션부터 만들고 그 세션으로 검증을 진행한다
   * (assertVerifiedSession 참고).
   */
  async start(userId: string): Promise<ExamSession> {
    const existing = await this.examSessionRepository.findInProgressByUser(userId);
    if (existing) {
      // 중간에 끊겼다가 다시 "시작"을 누른 경우 — 새로 만들지 않고 같은 세션을 이어서 준다.
      // 다만 반복 재접속은 악용(예: 준비/응답 시간 리셋 시도) 신호로 보고 횟수를 제한한다.
      const nextResumeCount = existing.resumeCount + 1;
      if (nextResumeCount >= RESUME_ATTEMPT_LIMIT) {
        await this.examSessionRepository.updateStatus(existing.id, SessionStatus.BLOCKED);
        throw new ForbiddenDomainException(
          'Your exam access has been restricted due to repeated reconnection attempts.',
        );
      }
      return this.examSessionRepository.updateResumeCount(existing.id, nextResumeCount);
    }

    return this.examSessionRepository.create({ userId });
  }

  /** 홈 화면이 "이어서 풀기" vs "응시하기" 버튼을 결정하는 데 쓴다 — 없으면 null. */
  async getCurrentInProgress(userId: string): Promise<ExamSession | null> {
    return this.examSessionRepository.findInProgressByUser(userId);
  }

  async getStatus(examSessionId: string, userId: string): Promise<ExamSessionStatusResult> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(notFound('Exam session', examSessionId));
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException(notOwnedByUser('session'));
    }

    // 세션이 더 이상 진행중이 아니게 된 시점에 본인인증용 얼굴 이미지를 정리한다.
    // 채점 완료 여부와는 무관 — 얼굴 사진은 채점이 아니라 시험 중 모니터링의
    // 동일인 검사에만 쓰였으므로, 세션이 끝나는 순간 더 이상 쓸모가 없다.
    // 멱등한 정리라 상태 조회가 반복돼도 안전하다.
    if (session.status !== SessionStatus.INPROGRESS) {
      await this.idCardVerificationService.cleanupVerifiedFaceImage(session.id);
    }

    return { session, status: session.status };
  }

  /** 마이페이지 "내 시험 현황" — 이 사용자가 시작한 적 있는 세션들을 최신순으로 내려준다. */
  async listMine(userId: string): Promise<MyExamStatus[]> {
    const sessions = await this.examSessionRepository.findAllByUser(userId);

    return Promise.all(
      sessions.map(async (session) => {
        const examResult = await this.examResultService.findByExamSessionId(session.id);

        return {
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
   * 본인인증/이어폰 확인이 아직 안 끝났으면 그 이유 메시지를, 다 끝났으면
   * null을 반환한다. AI팀 서비스가 아직 배포되지 않은 기간에는 서버 환경변수
   * (REQUIRE_IDENTITY_VERIFICATION/REQUIRE_EARPHONE_CHECK)로 각 체크를 개별
   * 우회할 수 있다 — 기본값은 강제(true), 실제 서비스 배포 전 반드시 되돌릴 것.
   */
  private async findVerificationGap(examSessionId: string): Promise<string | null> {
    if (this.config.requireIdentityVerification) {
      const verified = await this.idCardVerificationService.hasVerifiedSession(examSessionId);
      if (!verified) {
        return 'You must complete identity verification first.';
      }
    }

    if (this.config.requireEarphoneCheck) {
      const earphoneCheckPassed = await this.earphoneDetectionService.hasPassedCheck(examSessionId);
      if (!earphoneCheckPassed) {
        return 'You must complete the earphone check first.';
      }
    }

    return null;
  }

  /** 세션 상태 응답에 실어주는 "지금 문항/답안에 접근 가능한가" 플래그. */
  async isVerified(examSessionId: string): Promise<boolean> {
    return (await this.findVerificationGap(examSessionId)) === null;
  }

  /** 세션 존재 여부만 확인한다(소유권/상태 무관) — 관리자 문항 조회 등 소유권 우회가 필요한 곳에서 쓴다. */
  async getSessionOrThrow(examSessionId: string): Promise<ExamSession> {
    const session = await this.examSessionRepository.findById(examSessionId);
    if (!session) {
      throw new NotFoundDomainException(notFound('Exam session', examSessionId));
    }
    return session;
  }

  /**
   * 본인인증·이어폰 확인처럼 "세션은 있어야 하지만 아직 검증 전이어도 되는"
   * 동작들의 공통 게이트 — 소유권 + INPROGRESS만 확인한다.
   */
  async assertActiveSession(examSessionId: string, userId: string): Promise<ExamSession> {
    return this.examSessionAccessService.assertOwnedInProgress(examSessionId, userId);
  }

  /**
   * 문항 조회·답안 제출처럼 "본인인증/이어폰 확인까지 다 끝나야만" 허용되는
   * 동작들의 공통 게이트. assertActiveSession에 검증 완료 여부 체크를 더한다.
   */
  async assertVerifiedSession(examSessionId: string, userId: string): Promise<ExamSession> {
    const session = await this.assertActiveSession(examSessionId, userId);

    const verificationGap = await this.findVerificationGap(examSessionId);
    if (verificationGap) {
      throw new ForbiddenDomainException(verificationGap);
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
      throw new NotFoundDomainException(notFound('Exam session', examSessionId));
    }
    if (session.status === SessionStatus.DISQUALIFIED) {
      return session;
    }
    if (session.status === SessionStatus.SUBMITTED) {
      throw new ConflictDomainException(
        `Exam session (${examSessionId}) has already ended and cannot be disqualified.`,
      );
    }

    return this.examSessionRepository.updateStatus(examSessionId, SessionStatus.DISQUALIFIED);
  }
}
