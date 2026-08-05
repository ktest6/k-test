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

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description:
      '재생 가능한 완전한 URL(Supabase public URL). 답안 제출 시 보내는 audioFileUrl(Storage 경로)과 형태가 다르니 주의 — 재제출 시에는 이 값이 아니라 upload-url로 새로 받은 path를 써야 한다.',
  })
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
