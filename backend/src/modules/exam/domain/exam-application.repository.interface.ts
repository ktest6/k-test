import { ExamApplication } from './entities/exam-application.entity';

export interface CreateExamApplicationInput {
  examId: string;
  userId: string;
}

export const EXAM_APPLICATION_REPOSITORY = Symbol('EXAM_APPLICATION_REPOSITORY');

export interface ExamApplicationRepository {
  create(input: CreateExamApplicationInput): Promise<ExamApplication>;
  /** 취소되지 않은(활성) 신청만 대상. */
  findActiveByExamAndUser(examId: string, userId: string): Promise<ExamApplication | null>;
  /** soft delete. 호출 전 존재/소유권 확인은 서비스 계층 책임. */
  cancel(applicationId: string): Promise<void>;
  countActiveByExam(examId: string): Promise<number>;
}
