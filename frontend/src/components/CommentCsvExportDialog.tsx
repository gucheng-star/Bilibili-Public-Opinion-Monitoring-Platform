import { useEffect, useMemo, useRef, useState } from 'react';
import type { CommentData } from '../types';
import {
  buildCommentCsvFromPrepared,
  DEFAULT_COMMENT_CSV_OPTIONS,
  prepareCommentCsv,
  type CommentCsvOptionalColumn,
  type CommentCsvOptions,
  type CommentCsvSource,
} from '../utils/commentCsvExport';

interface Props {
  comments: readonly CommentData[];
  allComments: readonly CommentData[];
  defaultSource?: CommentCsvSource;
  sources?: readonly CommentCsvSource[];
  onClose: () => void;
}

const OPTIONAL_COLUMNS: ReadonlyArray<{ key: CommentCsvOptionalColumn; label: string }> = [
  { key: 'llmSentiment', label: '大模型主情感' },
  { key: 'llmStyle', label: '大模型表达风格' },
  { key: 'nlpSentiment', label: '本地 NLP 情感' },
  { key: 'context', label: '导出评论上下文（根评论内容、父评论内容）' },
  { key: 'username', label: '用户名' },
  { key: 'ipLocation', label: 'IP 属地' },
  { key: 'gender', label: '性别' },
  { key: 'postTime', label: '发布时间' },
  { key: 'likes', label: '点赞数' },
];

function previewText(value: string): string {
  const characters = Array.from(value);
  return characters.length > 72 ? `${characters.slice(0, 72).join('')}…` : value;
}

function fileTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

export default function CommentCsvExportDialog({ comments, allComments, defaultSource, sources, onClose }: Props) {
  const [options, setOptions] = useState<CommentCsvOptions>({ ...DEFAULT_COMMENT_CSV_OPTIONS });
  const exportedAt = useRef(new Date());
  const dialogRef = useRef<HTMLDivElement>(null);
  const prepared = useMemo(() => prepareCommentCsv({
    comments,
    allComments,
    defaultSource,
    sources,
    exportedAt: exportedAt.current,
  }), [allComments, comments, defaultSource, sources]);
  const data = useMemo(() => buildCommentCsvFromPrepared(prepared, options), [options, prepared]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const updateOption = (key: CommentCsvOptionalColumn, checked: boolean) => {
    setOptions(current => ({ ...current, [key]: checked }));
  };

  const download = () => {
    const blob = new Blob([data.csv], { type: 'text/csv;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `bili-comments-${fileTimestamp(exportedAt.current)}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    onClose();
  };

  return (
    <div className="comment-csv-dialog" role="presentation" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="comment-csv-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="comment-csv-dialog-title"
        aria-describedby="comment-csv-dialog-description"
        tabIndex={-1}
        onMouseDown={event => event.stopPropagation()}
        onKeyDown={event => { if (event.key === 'Escape') onClose(); }}
      >
        <div className="comment-csv-dialog__header">
          <div>
            <h2 id="comment-csv-dialog-title">导出评论数据</h2>
            <p id="comment-csv-dialog-description">当前筛选与搜索后共 {comments.length.toLocaleString()} 条评论。导出为 UTF-8 CSV，适用于 Excel / WPS。</p>
          </div>
          <button type="button" className="comment-csv-dialog__close ui-secondary-action" onClick={onClose} aria-label="关闭导出评论数据弹窗">×</button>
        </div>

        <div className="comment-csv-dialog__body">
          <p className="comment-csv-dialog__fixed">固定包含：样本ID、视频BV号、视频标题、评论内容</p>
          <fieldset className="comment-csv-dialog__options">
            <legend>可选附加信息</legend>
            {OPTIONAL_COLUMNS.map(({ key, label }) => (
              <label key={key} className={key === 'context' ? 'comment-csv-dialog__option comment-csv-dialog__option--wide' : 'comment-csv-dialog__option'}>
                <input type="checkbox" checked={options[key]} onChange={event => updateOption(key, event.target.checked)} />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>
          <p className="comment-csv-dialog__privacy">文件仅在本机生成；如勾选用户名或 IP 属地，可能包含公开评论资料，分享时请自行判断范围。</p>

          <section className="comment-csv-dialog__preview" aria-labelledby="comment-csv-preview-title">
            <div className="comment-csv-dialog__preview-heading">
              <h3 id="comment-csv-preview-title">预览前 {Math.min(5, data.rows.length)} 条</h3>
              <span>{data.rows.length.toLocaleString()} 条将导出</span>
            </div>
            <div className="comment-csv-dialog__preview-scroll">
              <table>
                <thead><tr>{data.headers.map(header => <th key={header}>{header}</th>)}</tr></thead>
                <tbody>{data.rows.slice(0, 5).map((row, rowIndex) => (
                  <tr key={row[0] || rowIndex}>{row.map((value, columnIndex) => <td key={`${rowIndex}-${data.headers[columnIndex]}`}>{previewText(value)}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="comment-csv-dialog__actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="ui-secondary-action comment-csv-dialog__download" onClick={download}>导出 {comments.length.toLocaleString()} 条</button>
        </div>
      </div>
    </div>
  );
}
