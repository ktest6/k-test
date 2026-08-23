import { ApiProperty } from '@nestjs/swagger';
import { IsString, MinLength } from 'class-validator';

export class CalibrateGazeDto {
  @ApiProperty({ description: '응시 세션 ID', example: '1' })
  @IsString()
  @MinLength(1)
  examSessionId: string;
}
