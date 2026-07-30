import { ApiProperty } from '@nestjs/swagger';
import { ExamStatus } from '../../domain/enums/exam-status.enum';

/** 관리자에게만 노출 — 일반 응시자용 ExamResponseDto에는 capacity가 없다. */
export class ExamAdminResponseDto {
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

  @ApiProperty({ description: '정원 — 관리자만 조회 가능' })
  capacity: number;

  @ApiProperty({ description: '현재 신청 인원(취소 제외) — 관리자만 조회 가능' })
  applicantCount: number;
}
