import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../domain/entities/exam.entity';
import {
  CreateExamInput,
  EXAM_REPOSITORY,
  ExamRepository,
} from '../../domain/exam.repository.interface';

@Injectable()
export class ExamService {
  constructor(@Inject(EXAM_REPOSITORY) private readonly examRepository: ExamRepository) {}

  async create(input: CreateExamInput): Promise<Exam> {
    if (input.closeAt.getTime() <= input.openAt.getTime()) {
      throw new ConflictDomainException('마감 시각은 시작 시각보다 나중이어야 합니다.');
    }
    return this.examRepository.create(input);
  }

  async findById(id: string): Promise<Exam> {
    const exam = await this.examRepository.findById(id);
    if (!exam) {
      throw new NotFoundDomainException(`시험 회차(${id})를 찾을 수 없습니다.`);
    }
    return exam;
  }

  list(): Promise<Exam[]> {
    return this.examRepository.list();
  }
}
