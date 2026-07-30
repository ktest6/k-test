import { CallHandler, ExecutionContext, Injectable, NestInterceptor } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { Request, Response } from 'express';
import { Observable, map } from 'rxjs';
import { RESPONSE_MESSAGE_KEY } from '../decorators/response-message.decorator';
import { ApiResponse } from '../interfaces/api-response.interface';

const DEFAULT_MESSAGES: Record<number, string> = {
  200: 'OK',
  201: 'Created',
};

/**
 * 모든 성공 응답을 공통 봉투(ApiResponse)로 감싼다. 컨트롤러는 지금처럼
 * 순수 데이터(DTO)만 리턴하면 되고, 감싸는 작업은 여기서 전역으로 처리한다.
 * 204는 HTTP 스펙상 바디가 없어야 하므로 그대로 통과시킨다.
 */
@Injectable()
export class TransformResponseInterceptor implements NestInterceptor {
  constructor(private readonly reflector: Reflector) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const httpContext = context.switchToHttp();
    const response = httpContext.getResponse<Response>();
    const request = httpContext.getRequest<Request>();

    return next.handle().pipe(
      map((data: unknown) => {
        const statusCode = response.statusCode;
        if (statusCode === 204) {
          return data;
        }

        const customMessage = this.reflector.get<string | undefined>(
          RESPONSE_MESSAGE_KEY,
          context.getHandler(),
        );

        const body: ApiResponse = {
          success: true,
          statusCode,
          message: customMessage ?? DEFAULT_MESSAGES[statusCode] ?? 'OK',
          data: data ?? null,
          path: request.url,
          timestamp: new Date().toISOString(),
        };
        return body;
      }),
    );
  }
}
