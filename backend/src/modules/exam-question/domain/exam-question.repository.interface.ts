import { ExamQuestion } from './entities/exam-question.entity';

export interface CreateExamQuestionInput {
  examId: string;
  questionId: string;
  assignedBy: string | null;
}

export const EXAM_QUESTION_REPOSITORY = Symbol('EXAM_QUESTION_REPOSITORY');

export interface ExamQuestionRepository {
  create(input: CreateExamQuestionInput): Promise<ExamQuestion>;
  findActiveByExamAndQuestion(examId: string, questionId: string): Promise<ExamQuestion | null>;
  findActiveByExam(examId: string): Promise<ExamQuestion[]>;
  unassign(examQuestionId: string): Promise<void>;
}
