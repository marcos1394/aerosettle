// Invalidate every outstanding verification when the selected context changes.
export class VerificationSession<T> {
  private generation = 0;
  private controller?: AbortController;

  invalidate(): void {
    this.generation++;
    this.controller?.abort();
    this.controller = undefined;
  }

  async run(contextKey: string, load: (signal: AbortSignal) => Promise<T>,
    apply: (result: T, contextKey: string) => void): Promise<void> {
    this.invalidate();
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    try {
      const result = await load(controller.signal);
      if (!controller.signal.aborted && generation === this.generation)
        apply(result, contextKey);
    } finally {
      if (generation === this.generation) this.controller = undefined;
    }
  }
}
