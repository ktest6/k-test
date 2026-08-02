import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Score } from '../../domain/entities/score.entity';
import {
  RecordScoreInput,
  SCORING_REPOSITORY,
  ScoringRepository,
} from '../../domain/scoring.repository.interface';

@Injectable()
export class ScoringService {
  constructor(@Inject(SCORING_REPOSITORY) private readonly scoringRepository: ScoringRepository) {}

  record(input: RecordScoreInput): Promise<Score> {
    return this.scoringRepository.record(input);
  }

  async getByAnswerId(answerId: string): Promise<Score> {
    const score = await this.scoringRepository.findByAnswerId(answerId);
    if (!score) {
      throw new NotFoundDomainException(`답안(${answerId})의 채점 결과를 찾을 수 없습니다.`);
    }
    return score;
  }

  /** 채점 전일 수 있는 상황에서 쓰는 조회 — 없으면 null(에러 아님). */
  findByAnswerId(answerId: string): Promise<Score | null> {
    return this.scoringRepository.findByAnswerId(answerId);
  }
}
