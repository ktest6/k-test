import {
  BadRequestException,
  Body,
  Controller,
  Post,
  UploadedFiles,
  UseInterceptors,
} from '@nestjs/common';
import { FileFieldsInterceptor } from '@nestjs/platform-express';
import { ApiBearerAuth, ApiBody, ApiConsumes, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { DetectEarphoneDto } from '../application/dto/detect-earphone.dto';
import { EarphoneDetectResponseDto } from '../application/dto/earphone-detect-response.dto';
import { EarphoneDetectionService } from '../application/services/earphone-detection.service';

const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;

interface EarphoneUploadedFiles {
  left_ear_image?: Express.Multer.File[];
  right_ear_image?: Express.Multer.File[];
}

/**
 * /verifications 아래 인증 타입별 고정 경로 중 하나 — 이어폰 착용 여부 확인.
 * id-card.controller.ts와 형제 컨트롤러(id-card.controller.ts 상단 주석 참고).
 */
@ApiBearerAuth()
@ApiTags('Verifications')
@ApiCommonErrorResponses()
@Controller('verifications/earphone')
export class EarphoneController {
  constructor(private readonly earphoneDetectionService: EarphoneDetectionService) {}

  @Post('detect')
  @UseInterceptors(
    FileFieldsInterceptor(
      [
        { name: 'left_ear_image', maxCount: 1 },
        { name: 'right_ear_image', maxCount: 1 },
      ],
      { limits: { fileSize: MAX_IMAGE_SIZE_BYTES } },
    ),
  )
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    schema: {
      type: 'object',
      required: ['examSessionId', 'left_ear_image', 'right_ear_image'],
      properties: {
        examSessionId: { type: 'string', example: '1' },
        left_ear_image: { type: 'string', format: 'binary', description: '왼쪽 귀 이미지' },
        right_ear_image: { type: 'string', format: 'binary', description: '오른쪽 귀 이미지' },
      },
    },
  })
  @ApiOperation({
    summary: '시험 시작 전 이어폰 착용 여부 감지',
    description:
      '양쪽 귀 이미지를 보내면 이어폰 감지 서비스에 판정을 요청한다. ' +
      'earphoneDetected만 보고 시험 시작 가능 여부를 결정할 수 있고, ' +
      '어느 쪽 귀에서 무엇이 탐지됐는지는 left/rightEarDetected·label·confidence로 확인할 수 있다.',
  })
  @ApiStandardResponse(EarphoneDetectResponseDto, {
    status: 201,
    message: 'Earphone detection completed',
  })
  async detect(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: DetectEarphoneDto,
    @UploadedFiles() files: EarphoneUploadedFiles,
  ): Promise<EarphoneDetectResponseDto> {
    const leftEarImage = files.left_ear_image?.[0];
    const rightEarImage = files.right_ear_image?.[0];
    if (!leftEarImage || !rightEarImage) {
      throw new BadRequestException('Both left_ear_image and right_ear_image files are required.');
    }

    return this.earphoneDetectionService.detect(
      user.id,
      dto.examSessionId,
      {
        buffer: leftEarImage.buffer,
        filename: leftEarImage.originalname,
        contentType: leftEarImage.mimetype,
      },
      {
        buffer: rightEarImage.buffer,
        filename: rightEarImage.originalname,
        contentType: rightEarImage.mimetype,
      },
    );
  }
}
