export type DanmakuTaskPhase = 'pending' | 'fetching' | 'analyzing' | 'done' | 'partial' | 'error';

export function isActiveDanmakuTask(status: DanmakuTaskPhase): boolean {
  return status === 'pending' || status === 'fetching' || status === 'analyzing';
}

export function isCurrentDanmakuRequest(
  requestToken: number,
  currentToken: number,
  originAnalysisId: number,
  currentAnalysisId: number | null,
): boolean {
  return requestToken === currentToken && originAnalysisId === currentAnalysisId;
}
