/** Grants state-write access to the most recent user intent only. */
export class LatestRequestGuard {
  private epoch = 0;

  begin(): number {
    this.epoch += 1;
    return this.epoch;
  }

  invalidate(): void {
    this.epoch += 1;
  }

  isCurrent(ticket: number): boolean {
    return ticket === this.epoch;
  }
}

/**
 * Applies an externally confirmed state transition even when newer local work
 * started while the confirmation request was in flight.
 */
export async function runConfirmedWorkflowTransition<T>(
  guard: LatestRequestGuard,
  confirmation: Promise<T>,
  applyConfirmed: (value: T) => void | Promise<void>,
): Promise<T> {
  const value = await confirmation;
  guard.invalidate();
  await applyConfirmed(value);
  return value;
}
