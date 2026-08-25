import {
  BadRequestException,
  Body,
  Controller,
  Post,
  UploadedFiles,
  UseInterceptors,
} from '@nestjs/common';
import { FilesInterceptor } from '@nestjs/platform-express';
import { ApiBearerAuth, ApiBody, ApiConsumes, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { CalibrateGazeDto } from '../application/dto/calibrate-gaze.dto';
import { GazeCalibrationResponseDto } from '../application/dto/gaze-calibration-response.dto';
import { GazeCalibrationService } from '../application/services/gaze-calibration.service';

const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;
const MAX_CALIBRATION_IMAGES = 10;

/**
 * /verifications 아래 인증 타입별 고정 경로 중 하나 — 시선 캘리브레이션.
 * id-card/earphone과 형제 컨트롤러(id-card.controller.ts 상단 주석 참고).
 */
@ApiBearerAuth()
@ApiTags('Verifications')
@ApiCommonErrorResponses()
@Controller('verifications/gaze-calibration')
export class GazeCalibrationController {
  constructor(private readonly gazeCalibrationService: GazeCalibrationService) {}

  @Post('calibrate')
  @UseInterceptors(
    FilesInterceptor('calibration_images', MAX_CALIBRATION_IMAGES, {
      limits: { fileSize: MAX_IMAGE_SIZE_BYTES },
    }),
  )
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    schema: {
      type: 'object',
      required: ['examSessionId', 'calibration_images'],
      properties: {
        examSessionId: { type: 'string', example: '1' },
        calibration_images: {
          type: 'array',
          items: { type: 'string', format: 'binary' },
          description: '화면 중앙을 응시한 이미지 여러 장 (같은 필드명으로 여러 개 전송)',
        },
      },
    },
  })
  @ApiOperation({
    summary: '시험 시작 전 시선 캘리브레이션',
    description:
      '화면 중앙을 응시한 이미지 여러 장으로 개인별 시선 기준값(eyeYawCenter/eyePitchCenter)을 뽑는다. ' +
      '결과는 저장해두고, 이후 모니터링(부정행위 감지) 프레임 분석마다 서버가 자동으로 실어 보낸다. ' +
      '선택 기능이라 시험 시작을 막지 않는다 — 안 해도 시험 진행에는 지장 없다.',
  })
  @ApiStandardResponse(GazeCalibrationResponseDto, {
    status: 201,
    message: '시선 캘리브레이션 완료',
  })
  async calibrate(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: CalibrateGazeDto,
    @UploadedFiles() files: Express.Multer.File[],
  ): Promise<GazeCalibrationResponseDto> {
    if (!files || files.length === 0) {
      throw new BadRequestException('At least one calibration_images file is required.');
    }

    return this.gazeCalibrationService.calibrate(
      user.id,
      dto.examSessionId,
      files.map((file) => ({
        buffer: file.buffer,
        filename: file.originalname,
        contentType: file.mimetype,
      })),
    );
  }
}
