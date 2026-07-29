import { Test } from './entities/test.entity';

export interface CreateTestInput {
  title: string;
  description?: string;
  durationMinutes: number;
  createdBy: string;
}

export interface UpdateTestInput {
  title?: string;
  description?: string;
  durationMinutes?: number;
}

export const TEST_REPOSITORY = Symbol('TEST_REPOSITORY');

export interface TestRepository {
  create(input: CreateTestInput): Promise<Test>;
  findById(id: string): Promise<Test | null>;
  update(id: string, input: UpdateTestInput): Promise<Test>;
  delete(id: string): Promise<void>;
  list(): Promise<Test[]>;
}
