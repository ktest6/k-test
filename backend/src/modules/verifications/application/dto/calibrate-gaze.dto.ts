import { ApiProperty } from '@nestjs/swagger';
import { IsString, MinLength } from 'class-validator';

export class CalibrateGazeDto {
  @ApiProperty({ description: '응시 회차 ID (tb_exam.exam_id)', example: '1' })
  @IsString()
  @MinLength(1)
  examId: string;
}
