import { useRef, useState, useCallback } from 'react';
import { Upload, FileJson, Plus } from 'lucide-react';
import type { BacktestFile, LoadedBacktestFile } from '../../types/backtestFile';

interface Props {
  onFilesLoaded: (files: LoadedBacktestFile[]) => void;
  hasExistingFiles: boolean;
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}

function validateBacktestFile(data: unknown): data is BacktestFile {
  if (typeof data !== 'object' || data === null) return false;
  const obj = data as Record<string, unknown>;
  return (
    typeof obj.date === 'string' &&
    typeof obj.config === 'object' &&
    obj.config !== null &&
    Array.isArray(obj.runs) &&
    obj.runs.length > 0
  );
}

export default function FileUploadZone({ onFilesLoaded, hasExistingFiles }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const processFiles = useCallback(async (fileList: FileList) => {
    setError(null);
    setIsProcessing(true);

    const results: LoadedBacktestFile[] = [];

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i];
      if (!file.name.endsWith('.json')) {
        setError(`"${file.name}" is not a JSON file. Only .json files are accepted.`);
        setIsProcessing(false);
        return;
      }

      try {
        const text = await file.text();
        const data = JSON.parse(text);

        if (!validateBacktestFile(data)) {
          setError(`"${file.name}" is not a valid backtest file. Expected config and runs[] fields.`);
          setIsProcessing(false);
          return;
        }

        const hasTradeData = data.runs.some(
          (r: { trades?: unknown[]; equity_curve?: unknown[] }) =>
            r.trades && r.trades.length > 0
        );

        results.push({
          file: data,
          fileName: file.name,
          fileId: generateId(),
          loadedAt: new Date(),
          isFull: hasTradeData,
        });
      } catch {
        setError(`Failed to parse "${file.name}". Ensure it's valid JSON.`);
        setIsProcessing(false);
        return;
      }
    }

    if (results.length > 0) {
      onFilesLoaded(results);
    }
    setIsProcessing(false);
  }, [onFilesLoaded]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files);
    }
  }, [processFiles]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
    }
  }, [processFiles]);

  // Compact "add another" button when files are already loaded
  if (hasExistingFiles) {
    return (
      <div className="flex items-center gap-3">
        <button
          onClick={() => inputRef.current?.click()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-700/60 border border-slate-600 text-slate-300 hover:text-white hover:bg-slate-700 hover:border-slate-500 transition-all text-sm font-medium"
          disabled={isProcessing}
        >
          <Plus size={16} />
          {isProcessing ? 'Processing...' : 'Add File'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".json"
          multiple
          className="hidden"
          onChange={handleFileSelect}
        />
        {error && <span className="text-red-400 text-xs">{error}</span>}
      </div>
    );
  }

  // Full drop zone for initial state
  return (
    <div className="flex flex-col items-center justify-center flex-1 p-8">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`
          w-full max-w-xl cursor-pointer rounded-2xl border-2 border-dashed p-12
          flex flex-col items-center gap-5 transition-all duration-300
          ${isDragging
            ? 'border-emerald-400 bg-emerald-500/10 scale-[1.02]'
            : 'border-slate-600 bg-slate-800/30 hover:border-slate-500 hover:bg-slate-800/50'
          }
        `}
      >
        <div className={`
          w-16 h-16 rounded-2xl flex items-center justify-center transition-colors
          ${isDragging ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700/60 text-slate-400'}
        `}>
          {isDragging ? <FileJson size={32} /> : <Upload size={32} />}
        </div>

        <div className="text-center">
          <p className="text-lg font-semibold text-white mb-1">
            {isDragging ? 'Drop your backtest file' : 'Upload Backtest Results'}
          </p>
          <p className="text-sm text-slate-400">
            Drag & drop a JSON file from <code className="text-slate-300 bg-slate-700/60 px-1.5 py-0.5 rounded text-xs">backtests/</code> or click to browse
          </p>
          <p className="text-xs text-slate-500 mt-2">
            Supports both full and brief backtest output files
          </p>
        </div>

        {isProcessing && (
          <div className="flex items-center gap-2 text-sm text-emerald-400">
            <div className="w-4 h-4 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
            Processing...
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 max-w-xl w-full">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".json"
        multiple
        className="hidden"
        onChange={handleFileSelect}
      />
    </div>
  );
}
