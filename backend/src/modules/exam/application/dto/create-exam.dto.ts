import { ApiProperty } from '@nestjs/swagger';
import { IsDateString, IsInt, IsPositive } from 'class-validator';

/**
 * roundName은 받지 않는다 — 서버가 "{연도}{그 해 순차번호}"(예: 202601)로
 * 자동 생성한다 (ExamService.generateRoundName). 관리자 오타로 인한 표기
 * 불일치를 막기 위함.
 */
export class CreateExamDto {
  @ApiProperty({
    example: '2026-07-01T00:00:00+09:00',
    description: '신청 접수 시작 시각 (ISO 8601)',
  })
  @IsDateString()
  applicationOpenAt: string;

  @ApiProperty({
    example: '2026-07-14T23:59:59+09:00',
    description: '신청 접수 마감 시각 (ISO 8601)',
  })
  @IsDateString()
  applicationCloseAt: string;

  @ApiProperty({
    example: '2026-08-01T00:00:00+09:00',
    description: '시험 응시 시작 시각 (ISO 8601)',
  })
  @IsDateString()
  openAt: string;

  @ApiProperty({
    example: '2026-08-14T23:59:59+09:00',
    description: '시험 응시 마감 시각 (ISO 8601)',
  })
  @IsDateString()
  closeAt: string;

  @ApiProperty({ example: 100, description: '정원' })
  @IsInt()
  @IsPositive()
  capacity: number;
}
