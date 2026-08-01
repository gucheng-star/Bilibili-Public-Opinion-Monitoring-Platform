interface Props { title: string; play: number; totalComments: number; }

import './DataPanels.css';

export default function VideoInfo({ title, play, totalComments }: Props) {
  return <section className="video-observation-panel" aria-labelledby="video-observation-title">
    <div className="video-observation-panel__header"><span className="panel-status">LIVE OBSERVATION</span><span className="video-observation-panel__status-dot" aria-hidden="true" /></div>
    <div className="video-observation-panel__body min-w-0">
      <h2 id="video-observation-title" className="text-base font-semibold text-primary truncate" title={title}>{title}</h2>
      <div className="video-observation-panel__metrics text-xs text-secondary">
        <span>播放 {play.toLocaleString()}</span>
        <span>评论总数 {totalComments.toLocaleString()}</span>
      </div>
    </div>
  </section>;
}
