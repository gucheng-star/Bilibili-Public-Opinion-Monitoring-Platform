import { useState, useMemo } from 'react';
import 'echarts-wordcloud';
import ReactECharts from 'echarts-for-react';
import type { KeywordItem } from '../types';
import { isDarkMode } from '../utils';

interface Props {
  keywords: KeywordItem[];
  className?: string;
}

export default function WordCloudCard({ keywords, className }: Props) {
  const dark = isDarkMode();
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  const activeKeywords = useMemo(
    () => keywords.filter(k => !excluded.has(k.word)).slice(0, 200),
    [keywords, excluded]
  );

  const toggleWord = (word: string) => {
    setExcluded(prev => {
      const next = new Set(prev);
      if (next.has(word)) next.delete(word);
      else next.add(word);
      return next;
    });
  };

  if (!keywords.length) return (
    <div className="card">
      <h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>{"\u8bcd\u4e91"}</h3>
      <div className="flex items-center justify-center h-64 text-muted text-sm">{"\u6682\u65e0\u5173\u952e\u8bcd"}</div>
    </div>
  );

  const colors = dark
    ? ['#FB7299','#38BDF8','#34D399','#FBBF24','#A78BFA','#F87171','#FB923C','#22D3EE','#C084FC']
    : ['#FB7299','#2563EB','#059669','#D97706','#7C3AED','#DC2626','#EA580C','#0891B2','#9333EA'];

  const cloudOption = {
    tooltip: { show: true, formatter: '{b}: {c} {"\u6b21"}' },
    series: [{
      type: 'wordCloud',
      shape: 'circle',
      left: 'center', top: 'center',
      width: '95%', height: '95%',
      sizeRange: [10, 56],
      rotationRange: [-45, 45],
      rotationStep: 15,
      gridSize: 6,
      drawOutOfBound: false,
      layoutAnimation: true,
      keepAspect: false,
      textStyle: {
        fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',
        fontWeight: 'normal',
        color: () => colors[Math.floor(Math.random() * colors.length)],
      },
      emphasis: {
        focus: 'self',
        textStyle: { textShadowBlur: 10, textShadowColor: dark ? 'rgba(251,114,153,.4)' : 'rgba(251,114,153,.3)' },
      },
      data: activeKeywords.map(k => ({ name: k.word, value: k.count })),
    }],
  };

  return (
    <div className={"card" + (className ? " " + className : "")}>
      <h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>{"\u8bcd\u4e91"}</h3>
      <div style={{display:'flex',gap:'.75rem',minHeight:'320px'}}>
        <div style={{flex:'1 1 60%',minWidth:0}}>
          {activeKeywords.length === 0 ? (
            <div className="flex items-center justify-center h-full text-muted text-sm">{"\u5df2\u5168\u90e8\u6392\u9664"}</div>
          ) : (
            <ReactECharts option={cloudOption} style={{height:'300px',width:'100%'}} />
          )}
        </div>
        <div style={{
          flex: '0 0 200px',
          borderLeft: '1px solid var(--border)',
          paddingLeft: '.75rem',
          overflowY: 'auto',
          maxHeight: '340px',
        }}>
          <div className="text-xs text-muted mb-2" style={{fontWeight:500}}>
            {"\u8bcd\u9891\u5217\u8868"} ({keywords.length})
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:'.25rem'}}>
            {keywords.map((k, i) => {
              const isExcluded = excluded.has(k.word);
              return (
                <button
                  key={k.word + "-" + i}
                  onClick={() => toggleWord(k.word)}
                  title={isExcluded ? "\u70b9\u51fb\u52a0\u5165\u8bcd\u4e91" : "\u70b9\u51fb\u6392\u9664"}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '.2rem .375rem', fontSize: '.6875rem',
                    borderRadius: '.25rem', cursor: 'pointer',
                    background: isExcluded ? 'var(--border)' : 'var(--accent-soft)',
                    color: isExcluded ? 'var(--text-muted)' : 'var(--text-primary)',
                    border: isExcluded ? '1px solid var(--border)' : '1px solid var(--border-accent)',
                    transition: 'all .12s ease',
                    textAlign: 'left',
                    width: '100%',
                    textDecoration: isExcluded ? 'line-through' : 'none',
                  }}
                >
                  <span style={{
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
                  }}>{k.word}</span>
                  <span style={{
                    marginLeft: '.5rem', fontSize: '.625rem',
                    color: isExcluded ? 'var(--text-muted)' : 'var(--text-secondary)',
                    flexShrink: 0,
                  }}>{k.count}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
