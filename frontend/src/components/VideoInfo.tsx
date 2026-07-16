interface Props {
  title: string;
  cover: string;
  play: number;
  totalComments: number;
}

export default function VideoInfo({ title, cover, play, totalComments }: Props) {
  return (
    <div className="flex items-center gap-4 p-4 bg-white rounded-lg shadow-sm border border-gray-100">
      {cover && (
        <img
          src={cover}
          alt={title}
          className="w-36 h-24 object-cover rounded-md flex-shrink-0"
        />
      )}
      <div className="min-w-0">
        <h2 className="text-lg font-semibold text-gray-800 truncate" title={title}>
          {title}
        </h2>
        <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
          <span>播放 {play.toLocaleString()}</span>
          <span>评论 {totalComments.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
}
