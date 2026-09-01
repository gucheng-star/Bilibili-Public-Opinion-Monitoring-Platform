import type { CommentData } from '../types';

export const COMMENT_PAGE_SIZE = 30;
export const COMMENT_PREVIEW_LENGTH = 72;

export interface CommentNode {
  comment: CommentData;
  children: CommentNode[];
  parentHidden: boolean;
}

export function commentKey(comment: CommentData, rpid: number | string = comment.rpid): string {
  return `${comment.source_analysis_id ?? 'single'}:${rpid}`;
}

export function getCommentPreview(content: string): string {
  const characters = Array.from(content);
  return characters.length > COMMENT_PREVIEW_LENGTH
    ? `${characters.slice(0, COMMENT_PREVIEW_LENGTH).join('')}…`
    : content;
}

export function isLongComment(content: string): boolean {
  return Array.from(content).length > COMMENT_PREVIEW_LENGTH;
}

export function buildCommentTree(comments: CommentData[], allCommentRpids: ReadonlySet<string>): CommentNode[] {
  const nodesByRpid = new Map<string, CommentNode>();
  comments.forEach(comment => nodesByRpid.set(commentKey(comment), { comment, children: [], parentHidden: false }));
  const roots: CommentNode[] = [];
  nodesByRpid.forEach(node => {
    const parent = node.comment.parent_rpid ? nodesByRpid.get(commentKey(node.comment, node.comment.parent_rpid)) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else {
      node.parentHidden = Boolean(
        node.comment.parent_rpid
        && allCommentRpids.has(commentKey(node.comment, node.comment.parent_rpid))
        && !parent,
      );
      roots.push(node);
    }
  });
  return roots;
}
