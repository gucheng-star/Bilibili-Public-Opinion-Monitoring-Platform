import { Link } from 'react-router-dom';

interface Props {
  total: number;
  rootCount: number;
  replyCount: number;
  to: string;
  search?: string;
}

export default function CommentEntryCard({ total, rootCount, replyCount, to, search = '' }: Props) {
  return (
    <Link className="card comment-entry" to={{ pathname: to, search }} aria-label="查看全部评论明细">
      <div className="comment-entry__body">
        <h3 className="comment-entry__title">评论明细</h3>
        <p className="comment-entry__stats">
          {total > 0
            ? `当前筛选命中 ${total.toLocaleString()} 条评论 · ${rootCount.toLocaleString()} 个根评论 · ${replyCount.toLocaleString()} 条回复`
            : '当前筛选没有命中评论'}
        </p>
      </div>
      <span className="comment-entry__button" aria-hidden="true">查看全部评论 →</span>
    </Link>
  );
}
