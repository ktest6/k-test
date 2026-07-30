import { ApiProperty } from '@nestjs/swagger';
import { IsString, MinLength } from 'class-validator';

export class VerifyIdCardDto {
  @ApiProperty({ description: '응시 세션 ID (tb_exam_session.exam_session_id)', example: '1' })
  @IsString()
  @MinLength(1)
  sessionId: string;

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
