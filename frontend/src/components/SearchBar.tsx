import { useState } from "react";

interface Props {
  onAnalyze: (bv: string) => void;
  loading: boolean;
}

export default function SearchBar({ onAnalyze, loading }: Props) {
  const [bv, setBv] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = bv.trim();
    if (trimmed && trimmed.startsWith("BV")) {
      onAnalyze(trimmed);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-3">
      <div className="flex-1 relative">
        <input
          type="text"
          value={bv}
          onChange={(e) => setBv(e.target.value)}
          placeholder="输入 B站视频 BV 号，如 BV1xx411c7mD"
          className="w-full h-12 px-4 pr-12 text-base border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 transition-shadow shadow-sm"
          disabled={loading}
        />
      </div>
      <button
        type="submit"
        disabled={loading || !bv.trim()}
        className="h-12 px-6 bg-gradient-to-r from-blue-500 to-blue-600 text-white font-medium rounded-lg hover:from-blue-600 hover:to-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm flex items-center gap-2"
      >
        {loading ? (
          <>
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            分析中...
          </>
        ) : (
          "开始分析"
        )}
      </button>
    </form>
  );
}
