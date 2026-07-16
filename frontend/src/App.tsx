import { useState, useCallback, useEffect } from "react";
import * as echarts from "echarts";
import SearchBar from "./components/SearchBar";
import VideoInfo from "./components/VideoInfo";
import SentimentChart from "./components/SentimentChart";
import GenderChart from "./components/GenderChart";
import RegionMap from "./components/RegionMap";
import WordCloudCard from "./components/WordCloudCard";
import HeatTimeline from "./components/HeatTimeline";
import CommentTable from "./components/CommentTable";
import HistoryPanel from "./components/HistoryPanel";
import { startAnalysis, getStatus, getResults } from "./services/api";
import type { AnalysisResult } from "./types";

function App() {
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusText, setStatusText] = useState("");

  useEffect(() => {
    fetch("https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json")
      .then((r) => r.json())
      .then((geo) => {
        echarts.registerMap("china", geo);
      })
      .catch(() => {
        console.warn("China map load failed");
      });
  }, []);

  const handleAnalyze = useCallback(async (bv: string) => {
    setLoading(true);
    setError(null);
    setResults(null);
    setStatusText("正在获取视频信息...");

    try {
      const { analysis_id } = await startAnalysis(bv);
      setAnalysisId(analysis_id);
      setStatusText("正在抓取评论...");

      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            const status = await getStatus(analysis_id);
            if (status.status === "done") {
              setStatusText("分析完成，加载结果...");
              const data = await getResults(analysis_id);
              setResults(data);
              setLoading(false);
              return;
            }
            if (status.status === "error") {
              setError(status.error_msg || "分析失败");
              setLoading(false);
              return;
            }
            if (status.status === "fetching") {
              setStatusText("正在抓取评论 (" + status.total_comments + " 条)...");
            } else if (status.status === "analyzing") {
              setStatusText("正在分析数据...");
            }
          } catch {
            // ignore poll errors
          }
        }
        setError("分析超时，请重试");
        setLoading(false);
      };

      poll();
    } catch (e: any) {
      setError(e.message || "请求失败");
      setLoading(false);
    }
  }, []);

  const handleViewHistory = useCallback(async (id: number) => {
    setLoading(true);
    setError(null);
    setStatusText("加载历史数据...");
    try {
      const data = await getResults(id);
      setResults(data);
      setAnalysisId(id);
    } catch (e: any) {
      setError(e.message || "加载失败");
    }
    setLoading(false);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-xl font-bold text-gray-800">
              <span className="text-blue-500">B</span> Public Opinion Monitor
            </h1>
          </div>
          <SearchBar onAnalyze={handleAnalyze} loading={loading} />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        {loading && !results && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-500">
            <svg className="animate-spin h-10 w-10 mb-4 text-blue-500" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-sm">{statusText || "处理中..."}</p>
          </div>
        )}

        {!loading && !results && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <svg className="w-16 h-16 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <p className="text-sm">Enter a BV number to begin</p>
          </div>
        )}

        {results && (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            <div className="lg:col-span-1">
              <HistoryPanel onSelect={handleViewHistory} selectedId={analysisId} />
            </div>
            <div className="lg:col-span-3 space-y-4">
              <VideoInfo
                title={results.video_title}
                cover={results.video_cover}
                play={results.video_play}
                totalComments={results.total_comments}
              />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <SentimentChart {...results.sentiment} />
                <GenderChart {...results.gender} />
                <div className="md:col-span-2">
                  <RegionMap data={results.region} />
                </div>
                <WordCloudCard analysisId={results.analysis_id} keywords={results.keywords} />
                <HeatTimeline
                  timeline={results.heat.timeline}
                  hourlyDistribution={results.heat.hourly_distribution}
                  peakHour={results.heat.peak_hour}
                  peakCount={results.heat.peak_count}
                />
              </div>
              <CommentTable comments={results.comments} />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
