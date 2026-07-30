import { applyDecorators } from '@nestjs/common';
import { ApiExtraModels, ApiResponse, getSchemaPath } from '@nestjs/swagger';
import { ApiErrorResponseDto } from '../dto/error-response.dto';

/**
 * 컨트롤러 단위로 붙여서 공통 에러 응답(HttpExceptionFilter가 만드는 형태)을
 * Swagger에 문서화한다. 인증이 필요 없는 컨트롤러는 401/403을 빼고 싶을 수
 * 있으니 옵션으로 제외할 상태코드를 받는다.
 */
export const ApiCommonErrorResponses = (exclude: number[] = []) => {
  const all = [
    { status: 400, description: '잘못된 요청 (유효성 검증 실패 등)' },
    { status: 401, description: '인증 필요 또는 토큰 만료' },
    { status: 403, description: '권한 없음' },
    { status: 404, description: '리소스를 찾을 수 없음' },
    { status: 500, description: '서버 내부 오류' },
  ].filter(({ status }) => !exclude.includes(status));

  return applyDecorators(
    ApiExtraModels(ApiErrorResponseDto),
    ...all.map(({ status, description }) =>
      ApiResponse({ status, description, schema: { $ref: getSchemaPath(ApiErrorResponseDto) } }),
    ),
  );
};
