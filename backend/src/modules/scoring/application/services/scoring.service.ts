import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { SubmissionService } from '../../../submission/application/services/submission.service';
import { Score } from '../../domain/entities/score.entity';
import {
  RecordScoreInput,
  SCORING_REPOSITORY,
  ScoringRepository,
} from '../../domain/scoring.repository.interface';

@Injectable()
export class ScoringService {
  constructor(
    @Inject(SCORING_REPOSITORY) private readonly scoringRepository: ScoringRepository,
    private readonly submissionService: SubmissionService,
  ) {}

  async record(input: RecordScoreInput): Promise<Score> {
    const score = await this.scoringRepository.record(input);
    await this.submissionService.markGraded(input.submissionId);
    return score;
  }

  async findBySubmissionId(submissionId: string): Promise<Score> {
    const score = await this.scoringRepository.findBySubmissionId(submissionId);
    if (!score) {
      throw new NotFoundDomainException(`응시(${submissionId})의 채점 결과를 찾을 수 없습니다.`);
    }
    return score;
  }
}
