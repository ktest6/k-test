import { Exam } from './entities/exam.entity';

export interface CreateExamInput {
  roundName: string;
  openAt: Date;
  closeAt: Date;
  capacity: number;
}

export const EXAM_REPOSITORY = Symbol('EXAM_REPOSITORY');

export interface ExamRepository {
  create(input: CreateExamInput): Promise<Exam>;
  findById(id: string): Promise<Exam | null>;
  list(): Promise<Exam[]>;
}
