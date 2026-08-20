import { ApiProperty } from '@nestjs/swagger';

export class GazeCalibrationResponseDto {
  @ApiProperty({ description: 'Calibration 성공 여부', example: true })
  calibrated: boolean;

  @ApiProperty({ description: 'Calibration에 실제로 쓰인 유효 이미지 수', example: 6 })
  sampleCount: number;

  @ApiProperty({ description: '화면 중앙 응시 시 Eye Yaw 기준값', example: -2.1937 })
  eyeYawCenter: number;

  @ApiProperty({ description: '화면 중앙 응시 시 Eye Pitch 기준값', example: -20.7994 })
  eyePitchCenter: number;
}
