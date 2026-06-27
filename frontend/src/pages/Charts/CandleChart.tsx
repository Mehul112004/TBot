import {
  useEffect,
  useRef,
  useState,
  useCallback,
  forwardRef,
  useImperativeHandle,
} from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  type IPrimitivePaneView,
  type IPrimitivePaneRenderer,
  type SeriesAttachedParameter,
  ColorType,
  type CandlestickData,
  type UTCTimestamp,
  type HistogramData,
  type LineData,
  type SeriesMarker,
  type Time,
  createSeriesMarkers,
} from "lightweight-charts";
import type {
  CandleData,
  SRZone,
  SMCZone,
  IndicatorSeriesPoint,
  PivotLevel,
  RoundNumber,
} from "../../api/client";
import type { LiveCandleEvent } from "../../types/signals";

/* ─── colour constants ─── */
const ZONE_COLORS: Record<string, { line: string; bg: string }> = {
  support: { line: "#10b981", bg: "rgba(16, 185, 129, 0.06)" },
  resistance: { line: "#ef4444", bg: "rgba(239, 68, 68, 0.06)" },
  both: { line: "#f59e0b", bg: "rgba(245, 158, 11, 0.06)" },
};

const SMC_COLORS: Record<string, { line: string; bg: string }> = {
  fvg_bullish: { line: "#22c55e", bg: "rgba(34, 197, 94, 0.08)" }, // green
  fvg_bearish: { line: "#f87171", bg: "rgba(248, 113, 113, 0.08)" }, // red
  ob_bullish: { line: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" }, // cyan
  ob_bearish: { line: "#f97316", bg: "rgba(249, 115, 22, 0.08)" }, // orange
  event: { line: "#a78bfa", bg: "rgba(167, 139, 250, 0.06)" }, // violet
};

const EMA_COLORS: Record<string, string> = {
  ema_9: "#f59e0b",
  ema_21: "#3b82f6",
  ema_50: "#8b5cf6",
  ema_100: "#ec4899", // pink
  ema_200: "#ef4444",
};

/* Pivot line colours: pivot=neutral, resistance=red, support=green */
const PIVOT_COLORS: Record<string, string> = {
  pivot: "#eab308", // yellow
  resistance: "#ef4444",
  support: "#10b981",
};

/* ─── helpers ─── */
function toUTC(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

function msToUTC(ms: number): UTCTimestamp {
  return Math.floor(ms / 1000) as UTCTimestamp;
}

/**
 * Convert a hex colour "#rrggbb" to an rgba() string with the given alpha.
 */
function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/* ─────────────────────────────────────────────────────────────────────────
   SR Band Primitive
   Draws a filled horizontal band (rectangle) between zone_lower and zone_upper
   for every S/R zone, spanning the full chart width. This replaces the old
   approach of three price-lines per zone (center + upper + lower) which
   cluttered the chart. Each band's fill opacity encodes its strength score;
   confluence / HTF zones get a brighter border.
   ───────────────────────────────────────────────────────────────────────── */

interface SRBand {
  upper: number;
  lower: number;
  color: string;        // base hex colour (by zone_type)
  fillAlpha: number;    // 0..1, derived from strength
  borderWidth: number;  // 1 (viewed TF) or 2 (HTF)
  borderColor: string;  // rgba string
}

/* Minimal structural types for the fancy-canvas draw target (not exported by
   lightweight-charts, so we declare just what we use). */
interface BitmapCoordinatesRenderingScope {
  readonly context: CanvasRenderingContext2D;
  readonly bitmapSize: { width: number; height: number };
  readonly horizontalPixelRatio: number;
  readonly verticalPixelRatio: number;
}
interface CanvasRenderingTarget2D {
  useBitmapCoordinateSpace<T>(f: (scope: BitmapCoordinatesRenderingScope) => T): T;
}

class SRBandPrimitive
  implements ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer
{
  private _series: ISeriesApi<"Candlestick"> | null = null;
  private _requestUpdate: (() => void) | null = null;
  private _bands: SRBand[] = [];

  attached(param: SeriesAttachedParameter): void {
    this._series = param.series as ISeriesApi<"Candlestick">;
    this._requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this._series = null;
    this._requestUpdate = null;
  }

  updateBands(bands: SRBand[]): void {
    this._bands = bands;
    if (this._requestUpdate) this._requestUpdate();
  }

  // ISeriesPrimitive
  paneViews(): readonly IPrimitivePaneView[] {
    return [this];
  }

  // IPrimitivePaneView
  renderer(): IPrimitivePaneRenderer | null {
    return this._bands.length > 0 ? this : null;
  }

  // IPrimitivePaneRenderer
  draw(target: CanvasRenderingTarget2D): void {
    const series = this._series;
    if (!series || this._bands.length === 0) return;

    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const vpr = scope.verticalPixelRatio;
      const width = scope.bitmapSize.width;

      for (const band of this._bands) {
        const yUpper = series.priceToCoordinate(band.upper);
        const yLower = series.priceToCoordinate(band.lower);
        if (yUpper === null || yLower === null) continue;

        const top = Math.min(yUpper, yLower) * vpr;
        const h = Math.abs(yUpper - yLower) * vpr;

        // Filled band
        ctx.fillStyle = withAlpha(band.color, band.fillAlpha);
        ctx.fillRect(0, top, width, Math.max(h, 1));

        // Borders (top + bottom)
        ctx.lineWidth = band.borderWidth * vpr;
        ctx.strokeStyle = band.borderColor;
        ctx.beginPath();
        ctx.moveTo(0, top);
        ctx.lineTo(width, top);
        ctx.moveTo(0, top + h);
        ctx.lineTo(width, top + h);
        ctx.stroke();
      }
    });
  }
}

/* ─── props ─── */
interface CandleChartProps {
  candles: CandleData[];
  srZones: SRZone[];
  showSRZones: boolean;
  smcZones: SMCZone[];
  showSMCZones: boolean;
  currentRegime?: string;
  emaLines: {
    ema_9: IndicatorSeriesPoint[];
    ema_21: IndicatorSeriesPoint[];
    ema_50: IndicatorSeriesPoint[];
    ema_100: IndicatorSeriesPoint[];
    ema_200: IndicatorSeriesPoint[];
  };
  showEMA: boolean;
  emaVisible: Record<string, boolean>;
  pivots: PivotLevel[];
  showPivots: boolean;
  roundNumbers: RoundNumber[];
  showRoundNumbers: boolean;
  viewedTimeframe: string;
  loading: boolean;
  error: string | null;
  symbol: string;
  timeframe: string;
  liveTick: LiveCandleEvent | null;
  closeTime: number | null;
}

export interface CandleChartRef {
  resetView: () => void;
}

const CandleChart = forwardRef<CandleChartRef, CandleChartProps>(
  (
    {
      candles,
      srZones,
      showSRZones,
      smcZones,
      showSMCZones,
      currentRegime,
      emaLines,
      showEMA,
      emaVisible,
      pivots,
      showPivots,
      roundNumbers,
      showRoundNumbers,
      viewedTimeframe,
      loading,
      error,
      symbol,
      timeframe,
      liveTick,
      closeTime,
    },
    ref,
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const emaSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
    const srPriceLinesRef = useRef<
      ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]
    >([]);
    const smcPriceLinesRef = useRef<
      ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]
    >([]);
    const pivotPriceLinesRef = useRef<
      ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]
    >([]);
    const roundNumberPriceLinesRef = useRef<
      ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]
    >([]);
    const srBandPrimitiveRef = useRef<SRBandPrimitive | null>(null);
    const seriesMarkersRef = useRef<any>(null);
    const legendRef = useRef<HTMLDivElement>(null);
    const chartInitialized = useRef(false);
    const lastChartConfig = useRef<string>("");

    /* ─── countdown timer (isolated state — no chart redraws) ─── */
    const [countdown, setCountdown] = useState<string | null>(null);

    useEffect(() => {
      if (closeTime == null) {
        setCountdown(null);
        return;
      }

      const tick = () => {
        const diff = closeTime - Date.now();
        if (diff <= 0) {
          setCountdown("00:00");
          return;
        }
        const totalSec = Math.floor(diff / 1000);
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        if (h > 0) {
          setCountdown(
            `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`,
          );
        } else {
          setCountdown(
            `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`,
          );
        }
      };

      tick(); // immediate first tick
      const id = setInterval(tick, 1000);
      return () => clearInterval(id);
    }, [closeTime]);

    /* ───────────────────── expose imperative handle ───────────────────── */
    useImperativeHandle(ref, () => ({
      resetView: () => {
        if (chartRef.current) {
          chartRef.current.timeScale().scrollToRealTime();
          chartRef.current.priceScale("right").applyOptions({
            autoScale: true,
          });
        }
      },
    }));

    /* ───────────────────── create chart instance ───────────────────── */
    const ensureChart = useCallback(() => {
      if (chartInitialized.current && chartRef.current) return; // already created
      if (!containerRef.current) return;

      // Cleanup if somehow stale
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
        volumeSeriesRef.current = null;
        emaSeriesRef.current = {};
        srPriceLinesRef.current = [];
        smcPriceLinesRef.current = [];
        pivotPriceLinesRef.current = [];
        roundNumberPriceLinesRef.current = [];
        srBandPrimitiveRef.current = null;
        seriesMarkersRef.current = null;
      }

      const chart = createChart(containerRef.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#94a3b8",
          fontFamily: "'Inter', -apple-system, sans-serif",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "rgba(51, 65, 85, 0.3)" },
          horzLines: { color: "rgba(51, 65, 85, 0.3)" },
        },
        crosshair: {
          vertLine: {
            color: "rgba(16, 185, 129, 0.25)",
            labelBackgroundColor: "#10b981",
          },
          horzLine: {
            color: "rgba(16, 185, 129, 0.25)",
            labelBackgroundColor: "#10b981",
          },
        },
        rightPriceScale: {
          borderColor: "rgba(51, 65, 85, 0.5)",
          scaleMargins: { top: 0.08, bottom: 0.16 },
        },
        timeScale: {
          borderColor: "rgba(51, 65, 85, 0.5)",
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 5,
          barSpacing: 8,
        },
      });

      chartRef.current = chart;

      // Candlestick series
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#10b981",
        wickDownColor: "#ef4444",
        wickUpColor: "#10b981",
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });
      candleSeriesRef.current = candleSeries;
      seriesMarkersRef.current = createSeriesMarkers(candleSeries);

      // SR band primitive (filled horizontal bands for S/R zones)
      const srBandPrimitive = new SRBandPrimitive();
      candleSeries.attachPrimitive(srBandPrimitive);
      srBandPrimitiveRef.current = srBandPrimitive;

      // Volume histogram (overlaid at bottom)
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      });
      volumeSeriesRef.current = volumeSeries;

      // OHLCV crosshair legend
      chart.subscribeCrosshairMove((param) => {
        if (!legendRef.current) return;

        if (
          !param.time ||
          !param.seriesData ||
          !param.seriesData.has(candleSeries)
        ) {
          legendRef.current.innerHTML = "";
          return;
        }

        const d = param.seriesData.get(candleSeries) as CandlestickData;
        if (!d) return;

        const change = d.close - d.open;
        const changePct = d.open !== 0 ? (change / d.open) * 100 : 0;
        const color = change >= 0 ? "#10b981" : "#ef4444";

        legendRef.current.innerHTML = `
        <span style="color:#94a3b8;margin-right:8px">O</span><span style="color:${color}">${d.open.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">H</span><span style="color:${color}">${d.high.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">L</span><span style="color:${color}">${d.low.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">C</span><span style="color:${color}">${d.close.toFixed(2)}</span>
        <span style="margin-left:14px;color:${color};font-weight:600">${change >= 0 ? "+" : ""}${changePct.toFixed(2)}%</span>
      `;
      });

      chartInitialized.current = true;
    }, []);

    /* ───────────────────── cleanup on unmount ───────────────────── */
    useEffect(() => {
      return () => {
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
          candleSeriesRef.current = null;
          volumeSeriesRef.current = null;
          emaSeriesRef.current = {};
          srPriceLinesRef.current = [];
          smcPriceLinesRef.current = [];
          pivotPriceLinesRef.current = [];
          roundNumberPriceLinesRef.current = [];
          srBandPrimitiveRef.current = null;
          seriesMarkersRef.current = null;
          chartInitialized.current = false;
        }
      };
    }, []);

    /* ───────────────────── update candle + volume data (full setData) ───────────────────── */
    useEffect(() => {
      if (candles.length === 0) return;

      // Lazily initialize chart the first time we have data + a real DOM node
      ensureChart();

      if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

      const candleData: CandlestickData[] = candles.map((c) => ({
        time: toUTC(c.open_time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

      const volumeData: HistogramData[] = candles.map((c) => ({
        time: toUTC(c.open_time),
        value: c.volume,
        color:
          c.close >= c.open
            ? "rgba(16, 185, 129, 0.18)"
            : "rgba(239, 68, 68, 0.18)",
      }));

      candleSeriesRef.current.setData(candleData);
      volumeSeriesRef.current.setData(volumeData);

      const configKey = `${symbol}-${timeframe}`;
      if (lastChartConfig.current !== configKey) {
        chartRef.current?.timeScale().fitContent();
        lastChartConfig.current = configKey;
      }
    }, [candles, symbol, timeframe, ensureChart]);

    /* ───────────────────── live tick via .update() ───────────────────── */
    useEffect(() => {
      if (!liveTick) return;
      if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

      const ts = msToUTC(liveTick.open_time);

      try {
        candleSeriesRef.current.update({
          time: ts,
          open: liveTick.open,
          high: liveTick.high,
          low: liveTick.low,
          close: liveTick.close,
        });

        volumeSeriesRef.current.update({
          time: ts,
          value: liveTick.volume,
          color:
            liveTick.close >= liveTick.open
              ? "rgba(16, 185, 129, 0.18)"
              : "rgba(239, 68, 68, 0.18)",
        });
      } catch {
        // Stale tick from previous timeframe — ignore during transition
      }
    }, [liveTick]);

    /* ───────────────────── S/R zone bands (primitive + labelled center line) ───────────────────── */
    useEffect(() => {
      const series = candleSeriesRef.current;
      const primitive = srBandPrimitiveRef.current;

      // Remove old center price lines
      if (series) {
        srPriceLinesRef.current.forEach((line) => {
          try {
            series.removePriceLine(line);
          } catch {
            /* already removed */
          }
        });
        srPriceLinesRef.current = [];
      }

      if (!primitive) return;
      if (!showSRZones || srZones.length === 0) {
        primitive.updateBands([]);
        return;
      }

      // Build bands for the primitive + one labelled center price line per zone.
      const bands: SRBand[] = [];
      for (const zone of srZones) {
        const colors = ZONE_COLORS[zone.zone_type] || ZONE_COLORS.both;
        const isHTF = zone.timeframe !== viewedTimeframe;
        const isConfluence = zone.confluence === true;

        // Fill opacity encodes strength: 0.06 (weak) → ~0.31 (strong)
        const fillAlpha = 0.06 + (zone.strength_score || 0) * 0.25;

        // HTF bands get a thicker border; confluence bands a brighter border.
        const borderWidth = isHTF ? 2 : 1;
        const borderAlpha = isConfluence ? 0.85 : isHTF ? 0.6 : 0.45;

        bands.push({
          upper: zone.zone_upper,
          lower: zone.zone_lower,
          color: colors.line,
          fillAlpha,
          borderWidth,
          borderColor: withAlpha(colors.line, borderAlpha),
        });

        // Labelled center line (axis label + compact title).
        // HTF zones are prefixed with their timeframe (e.g. "4H"); confluence
        // zones get a "*" marker.
        const typeTag =
          zone.zone_type === "support" ? "S" : zone.zone_type === "resistance" ? "R" : "SR";
        const tfTag = isHTF ? `${zone.timeframe.toUpperCase()} ` : "";
        const confTag = isConfluence ? "*" : "";
        const title = `${tfTag}${typeTag}${confTag} ${zone.price_level.toFixed(0)} (${zone.touch_count}×)`;

        const centerLine = series!.createPriceLine({
          price: zone.price_level,
          color: withAlpha(colors.line, isConfluence ? 0.9 : 0.7),
          lineWidth: isHTF ? 2 : 1,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
          title,
          lineVisible: true,
        });
        srPriceLinesRef.current.push(centerLine);
      }

      primitive.updateBands(bands);
    }, [showSRZones, srZones, viewedTimeframe]);

    /* ───────────────────── Pivot point price lines ───────────────────── */
    useEffect(() => {
      if (!candleSeriesRef.current) return;
      const series = candleSeriesRef.current;

      // Remove old pivot price lines
      pivotPriceLinesRef.current.forEach((line) => {
        try {
          series.removePriceLine(line);
        } catch {
          /* already removed */
        }
      });
      pivotPriceLinesRef.current = [];

      if (!showPivots || pivots.length === 0) return;

      for (const pv of pivots) {
        const color = PIVOT_COLORS[pv.direction] || PIVOT_COLORS.pivot;
        // Pivot P is solid; support/resistance levels are dashed.
        const isPivot = pv.direction === "pivot";
        const line = series.createPriceLine({
          price: pv.level,
          color: withAlpha(color, 0.6),
          lineWidth: 1,
          lineStyle: isPivot ? 0 : 2, // 0 = solid, 2 = dashed
          axisLabelVisible: true,
          title: pv.label,
          lineVisible: true,
        });
        pivotPriceLinesRef.current.push(line);
      }
    }, [showPivots, pivots]);

    /* ───────────────────── Psychological round-number lines (faint) ───────────────────── */
    useEffect(() => {
      if (!candleSeriesRef.current) return;
      const series = candleSeriesRef.current;

      // Remove old round-number price lines
      roundNumberPriceLinesRef.current.forEach((line) => {
        try {
          series.removePriceLine(line);
        } catch {
          /* already removed */
        }
      });
      roundNumberPriceLinesRef.current = [];

      if (!showRoundNumbers || roundNumbers.length === 0) return;

      for (const rn of roundNumbers) {
        const line = series.createPriceLine({
          price: rn.price_level,
          color: "rgba(245, 158, 11, 0.55)", // amber-500, subtle but readable
          lineWidth: 1,
          lineStyle: 2, // dashed
          axisLabelVisible: false,
          title: "",
          lineVisible: true,
        });
        roundNumberPriceLinesRef.current.push(line);
      }
    }, [showRoundNumbers, roundNumbers]);

    /* ───────────────────── SMC zone price lines (FVG / OB) ───────────────────── */
    useEffect(() => {
      if (!candleSeriesRef.current) return;
      const series = candleSeriesRef.current;

      // Remove old SMC price lines
      smcPriceLinesRef.current.forEach((line) => {
        try {
          series.removePriceLine(line);
        } catch {
          /* already removed */
        }
      });
      smcPriceLinesRef.current = [];

      if (!showSMCZones || smcZones.length === 0) return;

      // Deduplicate zones by exact type + direction + upper + lower
      const seen = new Set<string>();
      const uniqueZones = smcZones.filter((z) => {
        if (z.type === "event") return true; // Events are allowed, no deduplication needed
        if (!z.upper || !z.lower) return false;
        const key = `${z.type}_${z.direction}_${z.upper}_${z.lower}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });

      const markers: SeriesMarker<Time>[] = [];

      for (const zone of uniqueZones) {
        if (zone.type === "event" && zone.time) {
          markers.push({
            time: toUTC(zone.time),
            position:
              zone.direction === "bullish"
                ? "belowBar"
                : zone.direction === "bearish"
                  ? "aboveBar"
                  : "inBar",
            color:
              zone.direction === "bullish"
                ? "#10b981"
                : zone.direction === "bearish"
                  ? "#ef4444"
                  : "#a78bfa",
            shape:
              zone.direction === "bullish"
                ? "arrowUp"
                : zone.direction === "bearish"
                  ? "arrowDown"
                  : "circle",
            text: zone.label || "Event",
          });
          continue;
        }
        // Skip events without time (e.g. from older data shape)
        if (zone.type === "event") continue;
        if (!zone.upper || !zone.lower) continue;

        const colorKey = `${zone.type}_${zone.direction || "bullish"}`;
        const colors = SMC_COLORS[colorKey] || SMC_COLORS.event;
        const label = `${zone.type.toUpperCase()} ${(zone.direction || "?").toUpperCase()}`;

        // Center line (midpoint of zone)
        const mid = (zone.upper + zone.lower) / 2;
        const centerLine = series.createPriceLine({
          price: mid,
          color: colors.line,
          lineWidth: 2,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
          title: `${label} ${mid.toFixed(2)}`,
          lineVisible: true,
        });
        smcPriceLinesRef.current.push(centerLine);

        // Upper bound
        const upperLine = series.createPriceLine({
          price: zone.upper,
          color: colors.line + "60",
          lineWidth: 1,
          lineStyle: 3, // dotted
          axisLabelVisible: false,
          title: "",
          lineVisible: true,
        });
        smcPriceLinesRef.current.push(upperLine);

        // Lower bound
        const lowerLine = series.createPriceLine({
          price: zone.lower,
          color: colors.line + "60",
          lineWidth: 1,
          lineStyle: 3, // dotted
          axisLabelVisible: false,
          title: "",
          lineVisible: true,
        });
        smcPriceLinesRef.current.push(lowerLine);
      }

      // Sort markers by time as required by lightweight-charts
      markers.sort((a, b) => (a.time as number) - (b.time as number));
      seriesMarkersRef.current?.setMarkers(markers);
    }, [showSMCZones, smcZones]);

    /* ───────────────────── EMA line overlays ───────────────────── */
    useEffect(() => {
      if (!chartRef.current) return;

      // Remove old EMA series
      Object.values(emaSeriesRef.current).forEach((s) => {
        try {
          chartRef.current?.removeSeries(s);
        } catch {
          /* ok */
        }
      });
      emaSeriesRef.current = {};

      if (!showEMA) return;

      const emaKeys = [
        "ema_9",
        "ema_21",
        "ema_50",
        "ema_100",
        "ema_200",
      ] as const;

      for (const key of emaKeys) {
        if (!emaVisible[key]) continue;

        const points = emaLines[key];
        if (!points || points.length === 0) continue;

        const series = chartRef.current.addSeries(LineSeries, {
          color: EMA_COLORS[key],
          lineWidth: key === "ema_200" ? 2 : 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        const data: LineData[] = points
          .filter((p) => p.value !== null && p.value !== undefined && p.value !== "")
          .map((p) => ({
            time: toUTC(p.time),
            value: typeof p.value === "string" ? parseFloat(p.value) : (p.value as number),
          }));

        series.setData(data);
        emaSeriesRef.current[key] = series;
      }
    }, [showEMA, emaVisible, emaLines]);

    /* ─── derived values ─── */
    const hasCandles = candles.length > 0;
    const lastCandle = hasCandles ? candles[candles.length - 1] : null;
    const prevCandle = candles.length > 1 ? candles[candles.length - 2] : null;
    const priceChange =
      prevCandle && lastCandle ? lastCandle.close - prevCandle.close : 0;
    const priceChangePct =
      prevCandle && prevCandle.close !== 0
        ? (priceChange / prevCandle.close) * 100
        : 0;

    /* ───────────────────── RENDER ───────────────────── */
    return (
      <div className="relative flex flex-col flex-1 min-h-0" id="candle-chart">
        {/* Loading overlay */}
        {loading && !hasCandles && (
          <div
            className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80 backdrop-blur-sm"
            id="chart-loading"
          >
            <div className="text-center">
              <div className="mx-auto mb-4 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full w-10 h-10 animate-spin" />
              <p className="text-slate-400 text-sm">Loading chart data…</p>
              <p className="mt-1 text-slate-600 text-xs">
                {symbol} · {timeframe}
              </p>
            </div>
          </div>
        )}

        {/* Error overlay */}
        {error && !hasCandles && (
          <div
            className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80"
            id="chart-error"
          >
            <div className="bg-red-500/10 px-6 py-4 border border-red-500/30 rounded-xl max-w-md text-center">
              <p className="font-medium text-red-400">Chart Error</p>
              <p className="mt-1 text-red-300/70 text-sm">{error}</p>
            </div>
          </div>
        )}

        {/* Empty overlay */}
        {!hasCandles && !loading && !error && (
          <div
            className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80"
            id="chart-empty"
          >
            <div className="text-center text-slate-500">
              <div className="opacity-30 mb-4 text-5xl">📊</div>
              <p className="font-medium text-lg">No candle data</p>
              <p className="mt-1 text-sm">
                Select a symbol/timeframe with imported data
              </p>
            </div>
          </div>
        )}

        {/* Live price header */}
        {lastCandle && (
          <div
            className="top-3 left-4 z-10 absolute flex items-baseline gap-3 pointer-events-none"
            id="price-header"
          >
            <span className="font-bold text-2xl text-white tracking-tight">
              {lastCandle.close.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
            <span
              className={`text-sm font-semibold ${priceChange >= 0 ? "text-emerald-400" : "text-red-400"}`}
            >
              {priceChange >= 0 ? "+" : ""}
              {priceChangePct.toFixed(2)}%
            </span>
            {loading && (
              <div className="border-2 border-emerald-500/40 border-t-emerald-500 rounded-full w-3 h-3 animate-spin" />
            )}
          </div>
        )}

        {/* OHLCV crosshair legend */}
        <div
          ref={legendRef}
          className="top-11 left-4 z-10 absolute font-mono text-xs pointer-events-none"
          id="ohlcv-legend"
        />

        {/* Top-right overlay stack: countdown + regime + counts + EMA legend.
            All badges live in ONE flex-col container so the browser stacks
            them automatically — no manual `top:` offsets, no overlaps. */}
        <div
          className="top-3 right-4 z-20 absolute flex flex-col items-end gap-1.5 pointer-events-none"
          id="chart-overlay-stack"
        >
          {countdown && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 border rounded-md font-mono font-semibold text-xs tabular-nums"
              style={{
                background: "rgba(15, 23, 42, 0.85)",
                borderColor: "rgba(16, 185, 129, 0.3)",
                color: countdown === "00:00" ? "#f59e0b" : "#10b981",
                backdropFilter: "blur(4px)",
              }}
            >
              <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                fill="none"
                style={{ flexShrink: 0 }}
              >
                <circle
                  cx="5"
                  cy="5"
                  r="4"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  opacity="0.5"
                />
                <path
                  d="M5 2.5V5L6.5 6.5"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
              </svg>
              {countdown}
            </div>
          )}

          {currentRegime && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 border rounded-md font-bold font-mono text-xs uppercase tracking-wider"
              style={{
                background: "rgba(15, 23, 42, 0.85)",
                borderColor: currentRegime.includes("UP")
                  ? "rgba(16, 185, 129, 0.4)"
                  : currentRegime.includes("DOWN")
                    ? "rgba(239, 68, 68, 0.4)"
                    : "rgba(167, 139, 250, 0.4)",
                color: currentRegime.includes("UP")
                  ? "#10b981"
                  : currentRegime.includes("DOWN")
                    ? "#ef4444"
                    : "#a78bfa",
                backdropFilter: "blur(4px)",
              }}
            >
              {currentRegime.replace("_", " ")}
            </div>
          )}

          {/* SMC zone count */}
          {showSMCZones && smcZones.length > 0 && (
            <span className="bg-slate-800/80 px-2 py-1 border border-cyan-500/30 rounded text-[10px] text-cyan-400 backdrop-blur">
              {smcZones.length} SMC zone{smcZones.length !== 1 ? "s" : ""}
            </span>
          )}

          {/* Count badge: SR · Pivots · Psych — single compact pill */}
          {((showSRZones && srZones.length > 0) || (showPivots && pivots.length > 0) || (showRoundNumbers && roundNumbers.length > 0)) && (
            <span className="bg-slate-800/80 px-2 py-1 border border-slate-600/40 rounded text-[10px] text-slate-400 backdrop-blur">
              {[
                showSRZones && srZones.length > 0
                  ? `${srZones.length} S/R`
                  : null,
                showPivots && pivots.length > 0
                  ? `${pivots.length} Piv`
                  : null,
                showRoundNumbers && roundNumbers.length > 0
                  ? `${roundNumbers.length} Psych`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          )}

          {/* EMA legend — single row, right-aligned */}
          {showEMA && (
            <div className="flex gap-2 bg-slate-800/70 px-2 py-1 border border-slate-600/30 rounded backdrop-blur">
              {Object.entries(EMA_COLORS).map(([key, color]) =>
                emaVisible[key] ? (
                  <span
                    key={key}
                    className="font-bold text-[10px]"
                    style={{ color }}
                  >
                    {key.replace("ema_", "EMA ")}
                  </span>
                ) : null,
              )}
            </div>
          )}
        </div>

        {/* Chart container — ALWAYS rendered so containerRef is never null */}
        <div
          ref={containerRef}
          className="flex-1 w-full min-h-0"
          style={{ minHeight: "400px" }}
        />
      </div>
    );
  },
);

export default CandleChart;
