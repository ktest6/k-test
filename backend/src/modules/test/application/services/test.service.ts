import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Test } from '../../domain/entities/test.entity';
import {
  CreateTestInput,
  TEST_REPOSITORY,
  TestRepository,
  UpdateTestInput,
} from '../../domain/test.repository.interface';

@Injectable()
export class TestService {
  constructor(@Inject(TEST_REPOSITORY) private readonly testRepository: TestRepository) {}

  create(input: CreateTestInput): Promise<Test> {
    return this.testRepository.create(input);
  }

  async findById(id: string): Promise<Test> {
    const test = await this.testRepository.findById(id);
    if (!test) {
      throw new NotFoundDomainException(`시험(${id})을 찾을 수 없습니다.`);
    }
    return test;
  }

  update(id: string, input: UpdateTestInput): Promise<Test> {
    return this.testRepository.update(id, input);
  }

  delete(id: string): Promise<void> {
    return this.testRepository.delete(id);
  }

  list(): Promise<Test[]> {
    return this.testRepository.list();
  }
}
