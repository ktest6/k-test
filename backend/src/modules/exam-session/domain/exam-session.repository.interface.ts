import { ExamSession } from './entities/exam-session.entity';
import { SessionStatus } from './enums/session-status.enum';

export interface CreateExamSessionInput {
  examId: string;
  userId: string;
}

export const EXAM_SESSION_REPOSITORY = Symbol('EXAM_SESSION_REPOSITORY');

export interface ExamSessionRepository {
  create(input: CreateExamSessionInput): Promise<ExamSession>;
  findById(id: string): Promise<ExamSession | null>;
  /** 응시자 1명당 회차 1개에 활성 세션은 최대 1개(재응시 없음). */
  findByUserAndExam(userId: string, examId: string): Promise<ExamSession | null>;
  updateResumeCount(id: string, resumeCount: number): Promise<ExamSession>;
  updateStatus(id: string, status: SessionStatus): Promise<ExamSession>;
  /** status를 SUBMITTED로, submittedAt을 지금 시각으로 함께 세팅한다. */
  markSubmitted(id: string): Promise<ExamSession>;
  /** 최종 리포트 제출 재시도 배치(ExamSessionReportRetryScheduler)용 — 전체 회차를 통틀어 SUBMITTED인 세션. */
  findAllSubmitted(): Promise<ExamSession[]>;
  /** 방치 세션 정리 배치(ExamSessionExpiryScheduler)용 — 전체 회차를 통틀어 INPROGRESS인 세션. */
  findAllInProgress(): Promise<ExamSession[]>;
  /** 항시 응시 체제의 "한 번에 한 시험만" 게이트용 — 이 사용자의 INPROGRESS 세션(회차 무관). */
  findInProgressByUser(userId: string): Promise<ExamSession | null>;
  /** 마이페이지 "내 시험 현황"용 — 이 사용자가 시작한 적 있는 모든 세션(회차 무관, 상태 무관). */
  findAllByUser(userId: string): Promise<ExamSession[]>;
}
