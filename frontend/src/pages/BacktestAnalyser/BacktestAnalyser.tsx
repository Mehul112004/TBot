import { useState, useCallback } from 'react';
import { Layers } from 'lucide-react';
import type { LoadedBacktestFile, BacktestFileRun } from '../../types/backtestFile';
import FileUploadZone from './FileUploadZone';
import OverviewPanel from './OverviewPanel';
import RunDetailModal from './RunDetailModal';
import ComparePanel from './ComparePanel';

type ViewMode = 'single' | 'compare';

export default function BacktestAnalyser() {
  const [loadedFiles, setLoadedFiles] = useState<LoadedBacktestFile[]>([]);
  const [selectedRun, setSelectedRun] = useState<BacktestFileRun | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('single');
  const [activeFileIdx, setActiveFileIdx] = useState(0);

  const handleFilesLoaded = useCallback((newFiles: LoadedBacktestFile[]) => {
    setLoadedFiles(prev => {
      const updated = [...prev, ...newFiles];
      // Auto-switch to compare mode when 2+ files
      if (updated.length >= 2) setViewMode('compare');
      return updated;
    });
  }, []);

  const handleRemoveFile = useCallback((fileId: string) => {
    setLoadedFiles(prev => {
      const updated = prev.filter(f => f.fileId !== fileId);
      if (updated.length <= 1) setViewMode('single');
      return updated;
    });
    setActiveFileIdx(0);
  }, []);

  const hasFiles = loadedFiles.length > 0;

  return (
    <div className="h-full flex flex-col" id="backtest-analyser-page">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700 flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-white">Backtest Analyser</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Upload backtest JSON files to visualise insights & compare results
          </p>
        </div>

        <div className="flex items-center gap-3">
          {hasFiles && (
            <FileUploadZone onFilesLoaded={handleFilesLoaded} hasExistingFiles />
          )}

          {loadedFiles.length >= 2 && (
            <div className="flex items-center bg-slate-800 rounded-lg border border-slate-700 p-0.5">
              <button
                onClick={() => setViewMode('single')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  viewMode === 'single'
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Single
              </button>
              <button
                onClick={() => setViewMode('compare')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                  viewMode === 'compare'
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Layers size={12} />
                Compare
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {!hasFiles && (
          <FileUploadZone onFilesLoaded={handleFilesLoaded} hasExistingFiles={false} />
        )}

        {hasFiles && viewMode === 'single' && (
          <div className="p-6 space-y-4">
            {/* File tabs (when multiple files loaded) */}
            {loadedFiles.length > 1 && (
              <div className="flex gap-1 border-b border-slate-700 pb-0 overflow-x-auto scrollbar-none">
                {loadedFiles.map((f, idx) => (
                  <button
                    key={f.fileId}
                    onClick={() => setActiveFileIdx(idx)}
                    className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap flex items-center gap-2 ${
                      activeFileIdx === idx
                        ? 'bg-slate-700/60 text-emerald-400 border-b-2 border-emerald-400'
                        : 'text-slate-400 hover:text-white hover:bg-slate-700/30'
                    }`}
                  >
                    <span>{f.fileName.replace('.json', '')}</span>
                    {!f.isFull && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">brief</span>
                    )}
                  </button>
                ))}
              </div>
            )}

            <OverviewPanel
              loaded={loadedFiles[activeFileIdx]}
              onSelectRun={setSelectedRun}
            />
          </div>
        )}

        {hasFiles && viewMode === 'compare' && (
          <div className="p-6">
            <ComparePanel files={loadedFiles} onRemoveFile={handleRemoveFile} />
          </div>
        )}
      </div>

      {/* Run Detail Modal */}
      {selectedRun && (
        <RunDetailModal
          run={selectedRun}
          onClose={() => setSelectedRun(null)}
        />
      )}
    </div>
  );
}
