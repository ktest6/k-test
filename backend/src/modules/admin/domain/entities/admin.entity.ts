export class Admin {
  constructor(
    readonly id: string,
    readonly email: string,
    readonly name: string,
    readonly loginAttempts: number,
    readonly lastLoginAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
