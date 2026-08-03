import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { AnswerStatus } from '../../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';

export class AnswerResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  questionId: string;

  @ApiProperty({ enum: AnswerType })
  type: AnswerType;

  @ApiPropertyOptional({ type: String, nullable: true })
  contentText: string | null;

  @ApiPropertyOptional({ type: String, nullable: true })
  audioFileUrl: string | null;

  @ApiProperty({ enum: AnswerStatus })
  status: AnswerStatus;

  @ApiProperty()
  modifiedAt: Date;

  @ApiProperty({ description: '채점 완료 여부' })
  graded: boolean;

  @ApiPropertyOptional({
    description: '채점 결과 원본 (채점 전이면 null)',
    type: Object,
    nullable: true,
  })
  score: Record<string, unknown> | null;
}
