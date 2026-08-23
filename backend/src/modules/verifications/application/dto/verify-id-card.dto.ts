import { ApiProperty } from '@nestjs/swagger';
import { IsDateString, IsString, MinLength } from 'class-validator';

export class VerifyIdCardDto {
  @ApiProperty({ description: '응시 세션 ID', example: '1' })
  @IsString()
  @MinLength(1)
  examSessionId: string;

  @ApiProperty({
    description: '웹캠 이미지를 촬영한 시각 (ISO 8601) — FastAPI 대조 요청에 그대로 전달됨',
    example: '2026-07-26T15:30:00+09:00',
  })
  @IsDateString()
  capturedAt: string;

  @ApiProperty({
    description: 'upload-url로 발급받아 업로드한 신분증/수험표 이미지 경로',
    example: '1/1/id-card.jpg',
  })
  @IsString()
  @MinLength(1)
  idCardPath: string;

  @ApiProperty({
    description: 'upload-url로 발급받아 업로드한 웹캠 캡처 이미지 경로',
    example: '1/1/face.jpg',
  })
  @IsString()
  @MinLength(1)
  facePath: string;
}
