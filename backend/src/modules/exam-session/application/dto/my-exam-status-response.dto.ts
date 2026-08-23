import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

/** 마이페이지 "내 시험 현황" 한 줄 — 시작한 적 있는 세션 하나에 대응된다. */
export class MyExamStatusResponseDto {
  @ApiProperty()
  examId: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty()
  examSessionId: string;

  @ApiProperty({ enum: SessionStatus })
  sessionStatus: SessionStatus;

  @ApiProperty({ description: '시험을 시작한 시각' })
  startedAt: Date;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '시험을 제출(완료)한 시각. 아직 제출 전이면 null.',
  })
  submittedAt: Date | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description:
      '최종 리포트(/finalize) id. 아직 채점 결과가 없으면(진행중이거나 재시도 대기중) null.',
  })
  examResultId: string | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description:
      '최종 등급(A~F). examResultId는 있는데 이 값이 F면 assessment가 채점 커버리지 부족으로 ' +
      '등급을 확정하지 못한 경우일 수 있다(예: 스킵을 너무 많이 한 경우) — 완주하지 못한 것으로 ' +
      '간주해 F로 확정한다.',
  })
  finalGrade: string | null;
}
