import { Link } from 'react-router-dom';
import './CommentDetail.css';

interface Props {
  total: number;
  partIndex: number;
  partTitle: string;
  to: string;
}

export default function DanmakuEntryCard({ total, partIndex, partTitle, to }: Props) {
  return (
    <Link className="card comment-entry" to={to} aria-label="查看全部弹幕明细">
      <div className="comment-entry__body">
        <h3 className="comment-entry__title">弹幕明细</h3>
        <p className="comment-entry__stats">
          已保存 {total.toLocaleString()} 条本地 NLP 抽样弹幕 · P{partIndex}{partTitle ? ` · ${partTitle}` : ''}
        </p>
      </div>
      <span className="ui-secondary-action comment-entry__button" aria-hidden="true">查看全部弹幕 →</span>
    </Link>
  );
}
