import { Type, applyDecorators } from '@nestjs/common';
import { ApiExtraModels, ApiResponse, getSchemaPath } from '@nestjs/swagger';
import { ApiSuccessResponseDto } from '../dto/api-response.dto';
import { ResponseMessage } from './response-message.decorator';

interface ApiStandardResponseOptions {
  /** 기본 200 */
  status?: number;
  /** data가 배열인 응답(목록 조회 등) */
  isArray?: boolean;
  description?: string;
  /**
   * 성공 메시지(예: '로그인 성공'). 넘기면 Swagger 문서의 `message` 예시와
   * 실제 런타임 응답 메시지(TransformResponseInterceptor가 참조하는
   * @ResponseMessage 메타데이터)에 동시에 반영된다 — 두 군데 따로 맞출 필요 없음.
   */
  message?: string;
}

/**
 * 실제 응답 DTO를 공통 성공 봉투(ApiSuccessResponseDto)의 `data` 자리에 끼워
 * Swagger 스키마를 만든다. 컨트롤러는 이전과 동일하게 실제 DTO를 리턴하면
 * 되고, 봉투로 감싸는 건 TransformResponseInterceptor가 런타임에 처리한다 —
 * 이 데코레이터는 문서만 실제 응답 모양과 맞춰준다.
 */
export const ApiStandardResponse = <TModel extends Type<unknown>>(
  model: TModel,
  options: ApiStandardResponseOptions = {},
) => {
  const { status = 200, isArray = false, description, message } = options;

  const decorators = [
    ApiExtraModels(ApiSuccessResponseDto, model),
    ApiResponse({
      status,
      description,
      schema: {
        allOf: [
          { $ref: getSchemaPath(ApiSuccessResponseDto) },
          {
            properties: {
              ...(message ? { message: { type: 'string', example: message } } : {}),
              data: isArray
                ? { type: 'array', items: { $ref: getSchemaPath(model) } }
                : { $ref: getSchemaPath(model) },
            },
          },
        ],
      },
    }),
  ];

  if (message) {
    decorators.push(ResponseMessage(message));
  }

  return applyDecorators(...decorators);
};
