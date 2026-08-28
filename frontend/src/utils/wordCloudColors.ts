export function buildOpacityFamily(baseColor: string, minimumOpacity: number, steps = 6): string[] {
  const normalized = baseColor.trim().replace(/^#/, '');
  if (!/^[0-9a-fA-F]{6}$/.test(normalized) || steps <= 0) return [];

  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  const start = Math.max(0, Math.min(1, minimumOpacity));

  if (steps === 1) return [`rgba(${red}, ${green}, ${blue}, ${start.toFixed(2)})`];
  return Array.from({ length: steps }, (_, index) => {
    const opacity = start + (1 - start) * index / (steps - 1);
    return `rgba(${red}, ${green}, ${blue}, ${opacity.toFixed(2)})`;
  });
}
