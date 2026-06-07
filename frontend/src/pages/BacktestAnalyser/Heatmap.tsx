import { useMemo } from 'react';

interface HeatmapCell {
  row: string;
  col: string;
  value: number;
  label: string;
}

interface Props {
  rows: string[];
  columns: string[];
  cells: HeatmapCell[];
  valueLabel?: string;
  onCellClick?: (row: string, col: string) => void;
}

function interpolateColor(value: number, min: number, max: number): string {
  // Normalize to -1..+1 range (0 = neutral)
  const range = Math.max(Math.abs(min), Math.abs(max), 1);
  const normalized = Math.max(-1, Math.min(1, value / range));

  if (normalized >= 0) {
    // Green spectrum: 0 → subtle, +1 → vivid
    const intensity = normalized;
    return `rgba(16, 185, 129, ${0.08 + intensity * 0.45})`;
  } else {
    // Red spectrum: 0 → subtle, -1 → vivid
    const intensity = Math.abs(normalized);
    return `rgba(239, 68, 68, ${0.08 + intensity * 0.45})`;
  }
}

export default function Heatmap({ rows, columns, cells, valueLabel = 'PnL %', onCellClick }: Props) {
  const cellMap = useMemo(() => {
    const map = new Map<string, HeatmapCell>();
    for (const cell of cells) {
      map.set(`${cell.row}::${cell.col}`, cell);
    }
    return map;
  }, [cells]);

  const { min, max } = useMemo(() => {
    if (cells.length === 0) return { min: -1, max: 1 };
    const values = cells.map(c => c.value);
    return { min: Math.min(...values), max: Math.max(...values) };
  }, [cells]);

  if (rows.length === 0 || columns.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="p-2 text-left text-xs text-slate-500 font-medium sticky left-0 bg-slate-900 z-10">
              {valueLabel}
            </th>
            {columns.map(col => (
              <th key={col} className="p-2 text-center text-xs text-slate-400 font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row}>
              <td className="p-2 text-xs text-slate-300 font-medium whitespace-nowrap sticky left-0 bg-slate-900 z-10">
                {row}
              </td>
              {columns.map(col => {
                const cell = cellMap.get(`${row}::${col}`);
                const value = cell?.value ?? 0;
                const label = cell?.label ?? '—';
                const hasData = cell !== undefined;
                const bg = hasData ? interpolateColor(value, min, max) : 'rgba(51, 65, 85, 0.2)';

                return (
                  <td
                    key={col}
                    className={`p-2 text-center transition-all duration-200 ${
                      hasData && onCellClick
                        ? 'cursor-pointer hover:ring-2 hover:ring-emerald-400/40 hover:scale-105'
                        : ''
                    }`}
                    style={{ backgroundColor: bg }}
                    onClick={() => hasData && onCellClick?.(row, col)}
                  >
                    <span className={`text-xs font-semibold ${
                      !hasData ? 'text-slate-600' :
                      value > 0 ? 'text-emerald-300' :
                      value < 0 ? 'text-red-300' :
                      'text-slate-400'
                    }`}>
                      {label}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
