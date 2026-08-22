import { SetMetadata } from '@nestjs/common';

export const IS_OPTIONAL_AUTH_KEY = 'isOptionalAuth';

/**
 * @Public()과 달리 인증을 아예 안 하는 게 아니라, 토큰이 있으면 검증해서
 * request.user를 채우고 없거나 유효하지 않아도 막지 않는다(둘 다 통과) —
 * 로그인 여부에 따라 응답을 다르게 주는 라우트(예: 비로그인은 공개 목록만,
 * 로그인하면 개인화된 목록도 같이)에 쓴다.
 */
export const OptionalAuth = () => SetMetadata(IS_OPTIONAL_AUTH_KEY, true);
