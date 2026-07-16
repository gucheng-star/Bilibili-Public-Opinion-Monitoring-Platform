import { useEffect, useState } from "react";
import { getWordCloud } from "../services/api";
import type { KeywordItem } from "../types";

interface Props {
  analysisId: number;
  keywords: KeywordItem[];
}

export default function WordCloudCard({ analysisId, keywords }: Props) {
  const [imgSrc, setImgSrc] = useState<string>("");

  useEffect(() => {
    getWordCloud(analysisId)
      .then((data) => {
        if (data.base64) {
          setImgSrc(`data:image/png;base64,${data.base64}`);
        }
      })
      .catch(() => {});
  }, [analysisId]);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">词云</h3>
      {imgSrc ? (
        <img src={imgSrc} alt="词云" className="w-full h-auto rounded" />
      ) : (
        <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
          词云生成中...
        </div>
      )}
      {keywords.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {keywords.slice(0, 15).map((kw) => (
            <span
              key={kw.word}
              className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full"
            >
              {kw.word} {kw.count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
