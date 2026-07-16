import 'echarts-wordcloud';
import ReactECharts from 'echarts-for-react';
import type { KeywordItem } from '../types';
import { isDarkMode } from '../utils';

interface Props { keywords: KeywordItem[]; }

export default function WordCloudCard({ keywords }: Props) {
  const dark = isDarkMode();
  if (!keywords.length) return <div className="card"><h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>词云</h3><div className="flex items-center justify-center h-64 text-muted text-sm">暂无关键词</div></div>;

  const colors = dark
    ? ['#FB7299','#38BDF8','#34D399','#FBBF24','#A78BFA','#F87171','#FB923C','#22D3EE','#C084FC']
    : ['#FB7299','#2563EB','#059669','#D97706','#7C3AED','#DC2626','#EA580C','#0891B2','#9333EA'];

  const option = {
    tooltip: { show:true, formatter:'{b}: {c} 次' },
    series: [{
      type:'wordCloud', shape:'circle', left:'center', top:'center', width:'95%', height:'95%',
      sizeRange:[10, 56], rotationRange:[-45,45], rotationStep:15,
      gridSize:6, drawOutOfBound:false, layoutAnimation:true,
      textStyle: { fontFamily:'-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif', fontWeight:'normal',
        color:()=>colors[Math.floor(Math.random()*colors.length)] },
      emphasis: { focus:'self', textStyle:{ textShadowBlur:10, textShadowColor:dark?'rgba(251,114,153,.4)':'rgba(251,114,153,.3)' } },
      data: keywords.slice(0, 80).map(k=>({name:k.word,value:k.count})),
    }],
  };

  return <div className="card"><h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>词云</h3><ReactECharts option={option} style={{height:300}}/></div>;
}