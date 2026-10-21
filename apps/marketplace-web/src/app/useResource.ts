import { useCallback, useEffect, useRef, useState } from 'react';
// A route/filter change discards old data immediately. Late responses never replace a newer request.
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>
) {
  const loader = useRef(load);
  loader.current = load;
  const [revision, setRevision] = useState(0);
  const identity = `${key}:${revision}`;
  const [state, setState] = useState<{
    identity: string;
    data?: T;
    error?: string;
    loading: boolean;
  }>({ identity, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState({ identity, loading: true });
    void loader.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted)
          setState({ identity, data, loading: false });
      },
      (cause) => {
        if (!controller.signal.aborted)
          setState({
            identity,
            error: cause instanceof Error ? cause.message : String(cause),
            loading: false,
          });
      }
    );
    return () => controller.abort();
  }, [identity]);
  const reload = useCallback(() => setRevision((x) => x + 1), []);
  return {
    ...(state.identity === identity
      ? state
      : { loading: true, data: undefined, error: undefined }),
    reload,
  };
}
