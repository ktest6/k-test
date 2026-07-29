import { HttpStatus } from '@nestjs/common';

/**
 * Base class for errors raised by application/domain services. The
 * exception filter maps these to HTTP responses so use-cases never
 * depend on `@nestjs/common` HTTP exceptions directly.
 */
export class DomainException extends Error {
  constructor(
    message: string,
    readonly httpStatus: HttpStatus = HttpStatus.BAD_REQUEST,
    readonly code: string = 'DOMAIN_ERROR',
  ) {
    super(message);
    this.name = new.target.name;
  }
}

export class NotFoundDomainException extends DomainException {
  constructor(message: string) {
    super(message, HttpStatus.NOT_FOUND, 'NOT_FOUND');
  }
}

export class ForbiddenDomainException extends DomainException {
  constructor(message: string) {
    super(message, HttpStatus.FORBIDDEN, 'FORBIDDEN');
  }
}

export class ConflictDomainException extends DomainException {
  constructor(message: string) {
    super(message, HttpStatus.CONFLICT, 'CONFLICT');
  }
}

export class UnauthorizedDomainException extends DomainException {
  constructor(message: string) {
    super(message, HttpStatus.UNAUTHORIZED, 'UNAUTHORIZED');
  }
}
