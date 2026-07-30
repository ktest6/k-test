import { ApiProperty } from '@nestjs/swagger';
import { ExamStatus } from '../../domain/enums/exam-status.enum';

/** 일반 응시자용 — capacity(정원)는 관리자만 보이므로 ExamAdminResponseDto에만 있음. */
export class ExamResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty()
  openAt: Date;

  @ApiProperty()
  closeAt: Date;

  @ApiProperty({ enum: ExamStatus, description: 'open_at/close_at 기준으로 매번 계산됨' })
  status: ExamStatus;
}
