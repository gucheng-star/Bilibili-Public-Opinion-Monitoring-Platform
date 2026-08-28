import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import WordCloudCard from './components/WordCloudCard';
import './index.css';

const baseWords = [
  '舆情', '热点', '评论', '情绪', '支持', '关注', '讨论', '视频', '传播', '用户',
  '趋势', '观点', '内容', '分析', '事件', '反馈', '话题', '数据', '观察', '研判',
];
const words = Array.from({ length: 200 }, (_, index) => ({
  word: `${baseWords[index % baseWords.length]}${index + 1}`,
  count: 300 - index,
}));

function Harness() {
  const [status, setStatus] = useState<'ready' | 'loading'>('ready');
  const [scope, setScope] = useState('analysis:1');
  return <main style={{ maxWidth: '1080px', margin: '24px auto', padding: '0 16px' }}>
    <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
      <button type="button" onClick={() => setStatus('loading')}>切换筛选加载</button>
      <button type="button" onClick={() => setStatus('ready')}>恢复筛选结果</button>
      <button type="button" onClick={() => setScope(current => current === 'analysis:1' ? 'analysis:2' : 'analysis:1')}>切换分析</button>
    </div>
    <WordCloudCard keywords={status === 'ready' ? words : []} status={status} scopeKey={scope} />
  </main>;
}

createRoot(document.getElementById('root')!).render(<Harness />);
