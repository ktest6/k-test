import { ApiProperty } from '@nestjs/swagger';
import { IsEnum, IsIn, IsString, MinLength } from 'class-validator';
import { IdCardFileType } from '../../domain/enums/id-card-file-type.enum';

const ALLOWED_CONTENT_TYPES = ['image/jpeg', 'image/png', 'application/pdf'] as const;

export class RequestIdCardUploadUrlDto {
  @ApiProperty({ description: '응시 세션 ID', example: '1' })
  @IsString()
  @MinLength(1)
  examSessionId: string;

  @ApiProperty({ enum: IdCardFileType, description: '신분증/수험표인지 웹캠 캡처인지' })
  @IsEnum(IdCardFileType)
  fileType: IdCardFileType;

  @ApiProperty({
    enum: ALLOWED_CONTENT_TYPES,
    description: 'FACE는 이미지(jpeg/png)만 허용, ID_CARD는 pdf도 허용',
  })
  @IsIn(ALLOWED_CONTENT_TYPES)
  contentType: string;
}
