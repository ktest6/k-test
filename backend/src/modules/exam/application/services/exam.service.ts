import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../domain/entities/exam.entity';
import { EXAM_REPOSITORY, ExamRepository } from '../../domain/exam.repository.interface';

export interface CreateExamRequest {
  applicationOpenAt: Date;
  applicationCloseAt: Date;
  openAt: Date;
  closeAt: Date;
  capacity: number;
}

const ROUND_NAME_SEQUENCE_DIGITS = 2;

@Injectable()
export class ExamService {
  constructor(@Inject(EXAM_REPOSITORY) private readonly examRepository: ExamRepository) {}

  async create(input: CreateExamRequest): Promise<Exam> {
    if (input.closeAt.getTime() <= input.openAt.getTime()) {
      throw new ConflictDomainException('시험 마감 시각은 시작 시각보다 나중이어야 합니다.');
    }
    if (input.applicationCloseAt.getTime() <= input.applicationOpenAt.getTime()) {
      throw new ConflictDomainException('신청 마감 시각은 신청 시작 시각보다 나중이어야 합니다.');
    }
    if (input.applicationCloseAt.getTime() > input.openAt.getTime()) {
      throw new ConflictDomainException('신청 마감 시각은 시험 시작 시각보다 늦을 수 없습니다.');
    }

    const roundName = await this.generateRoundName(new Date().getFullYear());
    return this.examRepository.create({ ...input, roundName });
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

  /**
   * "{연도}{그 해 순차번호}" 형식(예: 202601)으로 회차명을 자동 생성한다.
   * 관리자가 직접 입력하지 않게 해서 오타로 인한 표기 불일치를 막는다.
   * 동시 생성 요청이 겹치면 드물게 같은 번호가 계산될 수 있는데, 그 경우
   * DB의 UNIQUE 제약(uq_exam_round_name)이 막고 409로 거부한다 — 관리자가
   * 재시도하면 다음 번호로 다시 계산되어 정상 생성된다.
   */
  private async generateRoundName(year: number): Promise<string> {
    const latest = await this.examRepository.findLatestRoundNameForYear(year);
    const nextSequence = latest ? Number(latest.slice(String(year).length)) + 1 : 1;
    return `${year}${String(nextSequence).padStart(ROUND_NAME_SEQUENCE_DIGITS, '0')}`;
  }
}
