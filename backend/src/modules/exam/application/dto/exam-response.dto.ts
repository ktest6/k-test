import { ApiProperty } from '@nestjs/swagger';
import { ExamStatus } from '../../domain/enums/exam-status.enum';

/** 일반 응시자용 — capacity(정원)는 관리자만 보이므로 ExamAdminResponseDto에만 있음. */
export class ExamResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty({ description: '신청 접수 시작 시각' })
  applicationOpenAt: Date;

  @ApiProperty({ description: '신청 접수 마감 시각' })
  applicationCloseAt: Date;

  @ApiProperty({ description: '시험 응시 시작 시각' })
  openAt: Date;

  @ApiProperty({ description: '시험 응시 마감 시각' })
  closeAt: Date;

  @ApiProperty({ enum: ExamStatus, description: 'open_at/close_at 기준으로 매번 계산됨' })
  status: ExamStatus;

  @ApiProperty({
    description:
      '정원이 찼는지 여부(신청 인원 >= capacity). 실제 정원/신청 인원 숫자는 관리자만 볼 수 있어 ' +
      '이 필드로만 노출한다.',
  })
  isCapacityFull: boolean;
}
