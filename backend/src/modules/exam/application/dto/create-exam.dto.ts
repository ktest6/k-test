import { ApiProperty } from '@nestjs/swagger';
import { IsDateString, IsInt, IsPositive, IsString, MaxLength, MinLength } from 'class-validator';

export class CreateExamDto {
  @ApiProperty({ example: '2026년 1회차', description: 'tb_exam.round_name — VARCHAR(20) 제한' })
  @IsString()
  @MinLength(1)
  @MaxLength(20)
  roundName: string;

  @ApiProperty({ example: '2026-08-01T00:00:00+09:00', description: '접수 시작 시각 (ISO 8601)' })
  @IsDateString()
  openAt: string;

  @ApiProperty({ example: '2026-08-14T23:59:59+09:00', description: '접수 마감 시각 (ISO 8601)' })
  @IsDateString()
  closeAt: string;

  @ApiProperty({ example: 100, description: '정원' })
  @IsInt()
  @IsPositive()
  capacity: number;
}
