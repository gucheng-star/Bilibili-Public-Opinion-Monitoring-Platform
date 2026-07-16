interface Props { title: string; play: number; totalComments: number; }

export default function VideoInfo({ title, play, totalComments }: Props) {
  return <div className="card">
    <div className="min-w-0">
      <h2 className="text-base font-semibold text-primary truncate" title={title}>{title}</h2>
      <div className="flex items-center gap-4 mt-2 text-xs text-secondary">
        <span>播放 {play.toLocaleString()}</span>
        <span>评论总数 {totalComments.toLocaleString()}</span>
      </div>
    </div>
  </div>;
}