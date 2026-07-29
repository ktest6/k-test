import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { CreateScoreDto } from '../application/dto/create-score.dto';
import { ScoreResponseDto } from '../application/dto/score-response.dto';
import { ScoringService } from '../application/services/scoring.service';

@ApiBearerAuth()
@ApiTags('Scoring')
@Controller('scoring')
export class ScoringController {
  constructor(private readonly scoringService: ScoringService) {}

  @Post()
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '채점 결과 등록 (관리자/채점 파이프라인)' })
  record(@Body() dto: CreateScoreDto): Promise<ScoreResponseDto> {
    return this.scoringService.record(dto);
  }

  @Get(':submissionId')
  @ApiOperation({ summary: '응시별 채점 결과 조회' })
  findBySubmission(@Param('submissionId') submissionId: string): Promise<ScoreResponseDto> {
    return this.scoringService.findBySubmissionId(submissionId);
  }
}
