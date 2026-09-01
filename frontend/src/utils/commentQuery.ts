import type { FilterState } from '../types';
import { EMPTY_FILTERS } from './commentFilters';

const GENDERS = new Set(['male', 'female']);
const DUPLICATE_MODES = new Set(['include', 'deduplicate', 'exclude_groups']);
const SENTIMENTS = new Set<string>([
  'positive', 'negative', 'neutral',
  'joy', 'support', 'anticipation', 'surprise', 'anger', 'sadness', 'concern', 'disgust', 'sarcasm',
]);
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type DetailSort = 'time' | 'likes';

export interface DetailState {
  q: string;
  sort: DetailSort;
  page: number;
}

export function filtersToSearchParams(filters: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.gender !== 'all') params.set('gender', filters.gender);
  if (filters.dateFrom) params.set('from', filters.dateFrom);
  if (filters.dateTo) params.set('to', filters.dateTo);
  if (filters.region) params.set('region', filters.region);
  if (filters.sentiment !== 'all') params.set('sentiment', filters.sentiment);
  if (filters.duplicateMode !== 'include') params.set('dup', filters.duplicateMode);
  if (filters.sourceAnalysisId !== 'all') params.set('source', filters.sourceAnalysisId);
  return params;
}

export function searchParamsToFilters(params: URLSearchParams, base: FilterState): FilterState {
  const filters: FilterState = { ...base };
  const gender = params.get('gender');
  if (gender && GENDERS.has(gender)) filters.gender = gender as 'male' | 'female';
  const from = params.get('from');
  if (from && DATE_PATTERN.test(from)) filters.dateFrom = from;
  const to = params.get('to');
  if (to && DATE_PATTERN.test(to)) filters.dateTo = to;
  const region = params.get('region');
  if (region) filters.region = region;
  const sentiment = params.get('sentiment');
  if (sentiment && SENTIMENTS.has(sentiment)) filters.sentiment = sentiment as FilterState['sentiment'];
  const duplicateMode = params.get('dup');
  if (duplicateMode && DUPLICATE_MODES.has(duplicateMode)) filters.duplicateMode = duplicateMode as FilterState['duplicateMode'];
  const source = params.get('source');
  if (source && /^\d+$/.test(source)) filters.sourceAnalysisId = source;
  return filters;
}

export function filtersEqual(left: FilterState, right: FilterState): boolean {
  return left.gender === right.gender
    && left.dateFrom === right.dateFrom
    && left.dateTo === right.dateTo
    && left.region === right.region
    && left.sentiment === right.sentiment
    && left.duplicateMode === right.duplicateMode
    && left.sourceAnalysisId === right.sourceAnalysisId;
}

export function filtersSearchString(filters: FilterState): string {
  const search = filtersToSearchParams(filters).toString();
  return search ? `?${search}` : '';
}

export function parseDetailState(params: URLSearchParams): DetailState {
  const sort = params.get('sort') === 'likes' ? 'likes' : 'time';
  const rawPage = Number(params.get('page'));
  const page = Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  return { q: params.get('q') ?? '', sort, page };
}

export function buildDetailSearch(filters: FilterState, detail: DetailState): string {
  const params = filtersToSearchParams(filters);
  if (detail.q) params.set('q', detail.q);
  if (detail.sort !== 'time') params.set('sort', detail.sort);
  if (detail.page > 1) params.set('page', String(detail.page));
  const search = params.toString();
  return search ? `?${search}` : '';
}

export function hasActiveFilters(filters: FilterState): boolean {
  return !filtersEqual(filters, EMPTY_FILTERS);
}
