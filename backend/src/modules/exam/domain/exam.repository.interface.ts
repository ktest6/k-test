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
  /** 그 해(soft-delete 포함) 가장 큰 round_name — 다음 순차번호 계산용. 없으면 null. */
  findLatestRoundNameForYear(year: number): Promise<string | null>;
}
