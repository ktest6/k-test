import { ApiProperty } from '@nestjs/swagger';
import { ReportViolationResponseDto } from './report-response.dto';

/**
 * 실격(DISQUALIFIED) 세션 전용 — 채점 자체가 없으므로 등급/영역별 점수/문항별
 * 답변은 없고, 부정행위 신호를 종류·심각도별 건수로 집계한 것만 담는다.
 */
export class ViolationSummaryResponseDto {
  @ApiProperty()
  examSessionId: string;

  @ApiProperty()
  candidateName: string;

  @ApiProperty({ description: '응시 시작 시각' })
  startedAt: Date;

  @ApiProperty({ type: [ReportViolationResponseDto] })
  violations: ReportViolationResponseDto[];
}
