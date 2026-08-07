import { Injectable, Logger, NestMiddleware } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';

/**
 * 모든 요청에 대해 METHOD 경로 상태코드 +응답시간ms 한 줄을 남긴다.
 * 인터셉터가 아니라 미들웨어인 이유 — 인터셉터는 예외 필터(HttpExceptionFilter)가
 * 응답 상태코드를 실제로 세팅하기 전 시점에 동작해서 에러 응답의 상태코드를
 * 정확히 못 읽는다. 미들웨어의 res.on('finish')는 응답이 실제로 다 나간 뒤에
 * 불려서, 성공/에러 상관없이 최종 상태코드를 그대로 읽을 수 있다.
 */
@Injectable()
export class RequestLoggingMiddleware implements NestMiddleware {
  private readonly logger = new Logger('HTTP');

  use(req: Request, res: Response, next: NextFunction): void {
    const start = Date.now();

    res.on('finish', () => {
      const elapsedMs = Date.now() - start;
      const line = `${req.method} ${req.originalUrl} ${res.statusCode} +${elapsedMs}ms`;

      if (res.statusCode >= 500) {
        this.logger.error(line);
      } else if (res.statusCode >= 400) {
        this.logger.warn(line);
      } else {
        this.logger.log(line);
      }
    });

    next();
  }
}
