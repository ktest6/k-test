import { SetMetadata } from '@nestjs/common';

export const RESPONSE_MESSAGE_KEY = 'responseMessage';

/** 기본 메시지("OK", "Created" 등) 대신 라우트별 커스텀 성공 메시지를 지정할 때 사용. */
export const ResponseMessage = (message: string) => SetMetadata(RESPONSE_MESSAGE_KEY, message);
