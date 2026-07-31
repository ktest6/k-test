import { ApiProperty } from '@nestjs/swagger';
import { DocumentStatus } from '../../domain/enums/document-status.enum';

export class UploadDocumentResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({ enum: DocumentStatus, description: '생성 직후라 항상 UPLOADED' })
  status: DocumentStatus;
}
