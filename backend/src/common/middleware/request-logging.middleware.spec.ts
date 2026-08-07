import { Logger } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';
import { RequestLoggingMiddleware } from './request-logging.middleware';

function buildRequest(overrides: Partial<Request> = {}): Request {
  return { method: 'GET', originalUrl: '/users/me', ...overrides } as Request;
}

function buildResponse(statusCode: number): Response {
  const handlers: Record<string, () => void> = {};
  return {
    statusCode,
    on: jest.fn((event: string, handler: () => void) => {
      handlers[event] = handler;
    }),
    // test-only helper to simulate the response actually finishing
    emitFinish: () => handlers.finish?.(),
  } as unknown as Response & { emitFinish: () => void };
}

describe('RequestLoggingMiddleware', () => {
  it('calls next immediately without waiting for the response to finish', () => {
    const middleware = new RequestLoggingMiddleware();
    const next = jest.fn() as NextFunction;

    middleware.use(buildRequest(), buildResponse(200), next);

    expect(next).toHaveBeenCalled();
  });

  it('logs a 2xx response at log level once the response finishes', () => {
    const middleware = new RequestLoggingMiddleware();
    const logSpy = jest.spyOn(Logger.prototype, 'log').mockImplementation(() => undefined);
    const response = buildResponse(200) as Response & { emitFinish: () => void };

    middleware.use(buildRequest({ method: 'GET', originalUrl: '/exams' }), response, jest.fn());
    response.emitFinish();

    expect(logSpy).toHaveBeenCalledWith(expect.stringContaining('GET /exams 200'));
  });

  it('logs a 4xx response at warn level', () => {
    const middleware = new RequestLoggingMiddleware();
    const warnSpy = jest.spyOn(Logger.prototype, 'warn').mockImplementation(() => undefined);
    const response = buildResponse(404) as Response & { emitFinish: () => void };

    middleware.use(buildRequest({ method: 'GET', originalUrl: '/exams/999' }), response, jest.fn());
    response.emitFinish();

    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('GET /exams/999 404'));
  });

  it('logs a 5xx response at error level', () => {
    const middleware = new RequestLoggingMiddleware();
    const errorSpy = jest.spyOn(Logger.prototype, 'error').mockImplementation(() => undefined);
    const response = buildResponse(500) as Response & { emitFinish: () => void };

    middleware.use(
      buildRequest({ method: 'POST', originalUrl: '/exam-sessions/1' }),
      response,
      jest.fn(),
    );
    response.emitFinish();

    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining('POST /exam-sessions/1 500'));
  });
});
