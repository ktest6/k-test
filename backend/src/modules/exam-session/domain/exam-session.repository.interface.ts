import { ExamSession } from './entities/exam-session.entity';
import { SessionStatus } from './enums/session-status.enum';

export interface CreateExamSessionInput {
  userId: string;
}

export const EXAM_SESSION_REPOSITORY = Symbol('EXAM_SESSION_REPOSITORY');

export interface ExamSessionRepository {
  create(input: CreateExamSessionInput): Promise<ExamSession>;
  findById(id: string): Promise<ExamSession | null>;
  /** 항시 응시 체제의 "한 번에 한 시험만" 게이트 겸 재개 대상 조회용 — 이 사용자의 INPROGRESS 세션(있으면 최대 1개). */
  findInProgressByUser(userId: string): Promise<ExamSession | null>;
  /** 마이페이지 "내 시험 현황"용 — 이 사용자가 시작한 적 있는 모든 세션(같은 시험 재응시 포함, 최신순). */
  findAllByUser(userId: string): Promise<ExamSession[]>;
  updateResumeCount(id: string, resumeCount: number): Promise<ExamSession>;
  updateStatus(id: string, status: SessionStatus): Promise<ExamSession>;
  /** status를 SUBMITTED로, submittedAt을 지금 시각으로 함께 세팅한다. */
  markSubmitted(id: string): Promise<ExamSession>;
  /** 최종 리포트 제출 재시도 배치(ExamSessionReportRetryScheduler)용 — 전체를 통틀어 SUBMITTED인 세션. */
  findAllSubmitted(): Promise<ExamSession[]>;
  /** 방치 세션 정리 배치(ExamSessionExpiryScheduler)용 — 전체를 통틀어 INPROGRESS인 세션. */
  findAllInProgress(): Promise<ExamSession[]>;
}
