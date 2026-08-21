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
  /** 마감 지난 세션 동기화 배치(ExamSessionExpiryScheduler)용 — 전체 회차를 통틀어 INPROGRESS인 세션. */
  findAllInProgress(): Promise<ExamSession[]>;
  updateResumeCount(id: string, resumeCount: number): Promise<ExamSession>;
  updateStatus(id: string, status: SessionStatus): Promise<ExamSession>;
}
