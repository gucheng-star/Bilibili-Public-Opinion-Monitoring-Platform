import { useCallback, useEffect, useRef, useState } from 'react';
import type { EChartsType } from 'echarts';

export type DistributionChartType = 'donut' | 'pie' | 'rose';

const DEFAULT_UPDATE_DURATION = 500;
const SPIN_UPDATE_DURATION = 800;
const FULL_TURN = Math.PI * 2;

type SectorDisplayable = {
  type?: string;
  shape?: {
    startAngle?: number;
    endAngle?: number;
  };
  setShape?: (shape: { startAngle: number; endAngle: number }) => void;
};

function shouldReduceMotion() {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function preparePieSeriesForFullSpin(chart: EChartsType | undefined) {
  if (!chart) return;

  const displayList = chart.getZr().storage.getDisplayList() as unknown as SectorDisplayable[];
  displayList.forEach(element => {
    const startAngle = element.shape?.startAngle;
    const endAngle = element.shape?.endAngle;
    if (element.type !== 'sector'
      || typeof startAngle !== 'number'
      || typeof endAngle !== 'number'
      || !element.setShape) return;

    // A whole-turn offset renders at the exact same position. ECharts can then
    // interpolate these live sector angles back to its normalized final layout,
    // producing a genuine 360° spin without rotating labels or the legend.
    element.setShape({
      startAngle: startAngle - FULL_TURN,
      endAngle: endAngle - FULL_TURN,
    });
  });
}

export default function useDistributionChartTransition() {
  const [type, setType] = useState<DistributionChartType>('donut');
  const [isSpinning, setIsSpinning] = useState(false);
  const [spinRevision, setSpinRevision] = useState(0);
  const typeRef = useRef(type);

  useEffect(() => {
    if (!isSpinning) return undefined;

    const timeoutId = window.setTimeout(() => {
      setIsSpinning(false);
    }, SPIN_UPDATE_DURATION);

    return () => window.clearTimeout(timeoutId);
  }, [isSpinning, spinRevision]);

  const selectType = useCallback((next: DistributionChartType, chart?: EChartsType) => {
    const current = typeRef.current;
    if (next === current) return;

    typeRef.current = next;
    // The equality guard above leaves every genuine donut/pie/rose type change
    // eligible for the same full-turn transition.
    const spin = !shouldReduceMotion();

    setIsSpinning(spin);
    if (spin) {
      preparePieSeriesForFullSpin(chart);
      setSpinRevision(revision => revision + 1);
    }
    setType(next);
  }, []);

  return {
    type,
    selectType,
    animationDurationUpdate: isSpinning ? SPIN_UPDATE_DURATION : DEFAULT_UPDATE_DURATION,
  };
}
