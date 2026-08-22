import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

/** "오늘 응시 가능한 시험" 한 줄 — 신청해서 아직 안 끝난 시험 + 신청 가능한 시험. */
export class AvailableExamResponseDto {
  @ApiProperty()
  examId: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty({ description: '시험 응시 시작 시각' })
  openAt: Date;

  @ApiProperty({ description: '시험 응시 마감 시각' })
  closeAt: Date;

  @ApiProperty({ description: '신청 접수 시작 시각' })
  applicationOpenAt: Date;

  @ApiProperty({ description: '신청 접수 마감 시각' })
  applicationCloseAt: Date;

  @ApiProperty({
    description:
      '이 회차에 이미 신청했는지 여부. false면 examSessionId/sessionStatus는 항상 null이고 ' +
      '프런트는 [신청하기]를, true면 [이어서 풀기]/[시작하기]를 보여주면 된다.',
  })
  isApplied: boolean;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '신청은 했지만 아직 세션을 시작한 적 없으면 null.',
  })
  examSessionId: string | null;

  @ApiPropertyOptional({
    enum: SessionStatus,
    nullable: true,
    description: '신청은 했지만 아직 세션을 시작한 적 없으면 null. 있으면 항상 INPROGRESS다.',
  })
  sessionStatus: SessionStatus | null;
}
