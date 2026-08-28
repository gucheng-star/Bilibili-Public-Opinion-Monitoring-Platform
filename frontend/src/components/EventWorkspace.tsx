import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getGroupFilteredKeywords, getGroupReanalysisStatus, getGroupResults, reanalyzeGroup } from '../services/api';
import { activeFilterFields, recordBreadcrumb, setDiagnosticState } from '../services/devDiagnostics';
import type { CommentData, FilterState, GroupAnalysisResult, GroupReanalysisStatus, KeywordItem, SentimentLLM } from '../types';
import AISummaryCard from './AISummaryCard';
import AppErrorBoundary from './AppErrorBoundary';
import CommentTable from './CommentTable';
import EventInfo from './EventInfo';
import FilterBar from './FilterBar';
import GenderChart from './GenderChart';
import HeatTimeline from './HeatTimeline';
import RegionMap from './RegionMap';
import SentimentChart from './SentimentChart';
import SourceDistributionPanel from './SourceDistributionPanel';
import WordCloudCard from './WordCloudCard';

const PROVINCES = new Set(['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','海南','四川','贵州','云南','陕西','甘肃','青海','台湾','内蒙古','广西','西藏','宁夏','新疆','香港','澳门']);
const LLM_EMOTIONS: (keyof SentimentLLM)[] = ['neutral','joy','support','anticipation','surprise','anger','sadness','concern','disgust','sarcasm'];
const sourceKey = (comment: CommentData, suffix: string | number) => `${comment.source_analysis_id ?? 'unknown'}:${suffix}`;
const displayReanalysisError = (message: string) => message.includes('模型返回格式不符合要求')
  ? message
  : message.includes('LLM batch failed') && message.includes('invalid, duplicate, or unexpected item')
  ? '模型返回格式不符合要求（包含重复、缺失或意外条目）'
  : message;
const reanalysisErrorMessage = (status: GroupReanalysisStatus) => status.errors
  .map(item => `${item.video_title}：${displayReanalysisError(item.message)}`)
  .join('；') || '大模型分析失败，已保留已完成标签与 NLP 结果。';

function normalizeProvince(raw: string) { const value=(raw||'').replace(/^IP属地[：:]/,''); if(!value||value==='未知'||value==='其它'||value==='中国')return ''; if(PROVINCES.has(value))return value; for(const province of PROVINCES)if(value.startsWith(province))return province; return value.startsWith('中国')&&PROVINCES.has(value.slice(2))?value.slice(2):value; }

interface Props { groupId: number; initialFilters: FilterState; onFiltersChange: (filters: FilterState) => void; }

export default function EventWorkspace({ groupId, initialFilters, onFiltersChange }: Props) {
  const [result, setResult] = useState<GroupAnalysisResult|null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState<string|null>(null); const [mode, setMode] = useState<'nlp'|'llm'>('nlp'); const [filters, setFilters] = useState<FilterState>(() => initialFilters); const [keywords, setKeywords] = useState<KeywordItem[]>([]); const [keywordStatus, setKeywordStatus] = useState<'ready'|'loading'|'error'>('ready'); const [reanalysis, setReanalysis] = useState<GroupReanalysisStatus|null>(null); const [reanalyzeDialog, setReanalyzeDialog] = useState(false); const [showNlpDuringReanalysis, setShowNlpDuringReanalysis] = useState(false);
  const requestRef = useRef(0); const keywordRequestRef = useRef(0); const reanalysisRequestRef = useRef(0); const onFiltersChangeRef = useRef(onFiltersChange); const showNlpDuringReanalysisRef = useRef(false);
  onFiltersChangeRef.current = onFiltersChange;
  showNlpDuringReanalysisRef.current = showNlpDuringReanalysis;
  useEffect(() => {
    setDiagnosticState({
      route: '/',
      view_type: 'group',
      group_id: groupId,
      analysis_mode: mode,
      loading,
      reanalyzing: reanalysis?.status === 'analyzing',
      keyword_status: keywordStatus,
      active_filter_fields: activeFilterFields(filters),
    });
  }, [filters, groupId, keywordStatus, loading, mode, reanalysis?.status]);
  useEffect(() => {
    if (reanalysis?.status) recordBreadcrumb('task.poll_status_changed', { poll_status: reanalysis.status });
  }, [reanalysis?.status]);
  useEffect(() => {
    recordBreadcrumb('analysis.mode_changed', { analysis_mode: mode });
  }, [mode]);
  const load = useCallback(async (nextMode: 'nlp'|'llm') => { const request=++requestRef.current; setLoading(true); setError(null); try { const [data, status] = await Promise.all([getGroupResults(groupId,nextMode), getGroupReanalysisStatus(groupId)]); if(request!==requestRef.current)return; setResult(data); setMode(data.mode); setReanalysis(status.status==='analyzing'||status.status==='error'?status:null); setFilters(current => { if (current.sourceAnalysisId === 'all' || data.members.some(member => String(member.analysis_id) === current.sourceAnalysisId)) return current; const normalized = { ...current, sourceAnalysisId: 'all' }; onFiltersChangeRef.current(normalized); return normalized; }); } catch(reason) { if(request===requestRef.current)setError(reason instanceof Error?reason.message:'读取事件结果失败'); } finally { if(request===requestRef.current)setLoading(false); } }, [groupId]);
  useEffect(()=>{ reanalysisRequestRef.current++; setResult(null); setMode('nlp'); setReanalysis(null); setReanalyzeDialog(false); setShowNlpDuringReanalysis(false); void load('nlp'); },[groupId,load]);
  const duplicateFiltered = useMemo(()=>{ if(!result)return []; if(filters.duplicateMode==='deduplicate')return result.comments.filter(comment=>!comment.is_exact_duplicate||comment.is_duplicate_canonical); if(filters.duplicateMode==='exclude_groups')return result.comments.filter(comment=>!comment.is_exact_duplicate); return result.comments; },[result,filters.duplicateMode]);
  const filtered = useMemo(()=>{ let comments=[...duplicateFiltered]; if(filters.sourceAnalysisId!=='all')comments=comments.filter(comment=>String(comment.source_analysis_id)===filters.sourceAnalysisId); if(filters.gender==='male')comments=comments.filter(comment=>comment.gender==='男'); if(filters.gender==='female')comments=comments.filter(comment=>comment.gender==='女'); if(filters.dateFrom)comments=comments.filter(comment=>comment.post_time&&comment.post_time.slice(0,10)>=filters.dateFrom); if(filters.dateTo)comments=comments.filter(comment=>comment.post_time&&comment.post_time.slice(0,10)<=filters.dateTo); if(filters.region)comments=comments.filter(comment=>normalizeProvince(comment.ip_location)===filters.region); if(filters.sentiment!=='all')comments=mode==='llm'?comments.filter(comment=>comment.sentiment_llm_label===filters.sentiment):comments.filter(comment=>comment.sentiment_label===filters.sentiment); return comments; },[duplicateFiltered,filters,mode]);
  const duplicateGroups = useMemo(()=>{ const map=new Map<string,CommentData[]>(); (result?.comments||[]).forEach(comment=>{if(!comment.duplicate_group_key)return;const key=sourceKey(comment,comment.duplicate_group_key);map.set(key,[...(map.get(key)||[]),comment]);}); return Array.from(map.entries()).map(([key,members])=>({key,content:members[0]?.content||'',count:members.length,firstPostTime:members.reduce<string|null>((first,member)=>!member.post_time?first:!first||member.post_time<first?member.post_time:first,null),lastPostTime:members.reduce<string|null>((last,member)=>!member.post_time?last:!last||member.post_time>last?member.post_time:last,null)})).sort((left,right)=>right.count-left.count||left.key.localeCompare(right.key)); },[result]);
  const sentiment = useMemo(()=>({positive:filtered.filter(comment=>comment.sentiment_label==='positive').length,negative:filtered.filter(comment=>comment.sentiment_label==='negative').length,neutral:filtered.filter(comment=>comment.sentiment_label==='neutral').length}),[filtered]);
  const llm = useMemo<SentimentLLM>(()=>{const counts:SentimentLLM={neutral:0,joy:0,support:0,anticipation:0,surprise:0,anger:0,sadness:0,concern:0,disgust:0,sarcasm:0};filtered.forEach(comment=>{const label=comment.sentiment_llm_label as keyof SentimentLLM;if(LLM_EMOTIONS.includes(label))counts[label]++;});return counts;},[filtered]);
  const gender = useMemo(()=>({male:filtered.filter(comment=>comment.gender==='男').length,female:filtered.filter(comment=>comment.gender==='女').length,unknown:filtered.filter(comment=>comment.gender!=='男'&&comment.gender!=='女').length}),[filtered]);
  const region = useMemo(()=>{const map=new Map<string,number>();filtered.forEach(comment=>{const value=normalizeProvince(comment.ip_location);if(value)map.set(value,(map.get(value)||0)+1);});return Array.from(map.entries()).map(([region,count])=>({region,count,percentage:filtered.length?count/filtered.length*100:0}));},[filtered]);
  const heat = useMemo(()=>{const counts=new Map<string,number>();const hourly=new Array(24).fill(0);filtered.forEach(comment=>{if(!comment.post_time)return;const hour=comment.post_time.slice(0,13)+':00:00';counts.set(hour,(counts.get(hour)||0)+1);hourly[new Date(comment.post_time).getHours()]++;});const peak=Math.max(...hourly,0);const peakIndex=peak?hourly.indexOf(peak):-1;return {timeline:Array.from(counts.entries()).map(([time,count])=>({time,count})).sort((a,b)=>a.time.localeCompare(b.time)),peak_hour:peakIndex<0?null:`${peakIndex}`.padStart(2,'0')+':00',peak_count:peak,hourly_distribution:hourly.map((count,hour)=>({hour,count}))};},[filtered]);
  const regions = useMemo(()=>Array.from(new Set((result?.comments||[]).map(comment=>normalizeProvince(comment.ip_location)).filter(Boolean))).sort(),[result]);
  const commentKeys = useMemo(()=>new Set((result?.comments||[]).map(comment=>sourceKey(comment,comment.rpid))),[result]);
  useEffect(()=>{const request=++keywordRequestRef.current;if(!result)return;const full=filters.gender==='all'&&!filters.dateFrom&&!filters.dateTo&&!filters.region&&filters.sentiment==='all'&&filters.duplicateMode==='include'&&filters.sourceAnalysisId==='all';if(full){setKeywords(result.keywords);setKeywordStatus('ready');return;}setKeywords([]);setKeywordStatus('loading');getGroupFilteredKeywords(groupId,mode,filters).then(response=>{if(request!==keywordRequestRef.current)return;if(response.matched_count!==filtered.length)throw new Error('筛选集合计数不一致');setKeywords(response.keywords);setKeywordStatus('ready');}).catch(()=>{if(request===keywordRequestRef.current){setKeywords([]);setKeywordStatus('error');}});},[filtered.length,filters,groupId,mode,result]);
  const pollReanalysis = useCallback(async (request: number, isActive: () => boolean) => { while(isActive()&&request===reanalysisRequestRef.current){ await new Promise(resolve=>window.setTimeout(resolve,1500)); if(!isActive())return; try { const status=await getGroupReanalysisStatus(groupId); if(!isActive()||request!==reanalysisRequestRef.current)return; setReanalysis(current=>({ ...status, target_comments: current?.target_comments })); if(status.status==='done'&&status.ready){ setReanalysis(null); await load(showNlpDuringReanalysisRef.current?'nlp':'llm'); return; } if(status.status==='error'){ return; } } catch(reason) { if(isActive()&&request===reanalysisRequestRef.current)setError(reason instanceof Error?reason.message:'读取大模型进度失败'); } } },[groupId,load]);
  useEffect(()=>{ if(reanalysis?.status!=='analyzing')return; let active=true; const request=reanalysisRequestRef.current; void pollReanalysis(request,()=>active); return()=>{active=false;}; },[pollReanalysis,reanalysis?.status]);
  const confirmReanalysis = async () => { const request=++reanalysisRequestRef.current; setReanalyzeDialog(false); setShowNlpDuringReanalysis(false); setError(null); try { const status=await reanalyzeGroup(groupId); if(request!==reanalysisRequestRef.current)return; if(status.status==='done'&&status.ready){ await load('llm'); return; } setReanalysis(status); } catch(reason) { if(request===reanalysisRequestRef.current)setError(reason instanceof Error?reason.message:'启动大模型分析失败'); } };
  const showNlpAnalysis = () => { setShowNlpDuringReanalysis(true); if(mode!=='nlp')void load('nlp'); };
  const changeMode = (next:'nlp'|'llm') => { if(next==='llm'&&(reanalysis?.status==='analyzing'||reanalysis?.status==='error')){setShowNlpDuringReanalysis(false);return;} if(next==='llm'&&!result?.llm_readiness?.ready){setReanalyzeDialog(true);return;} void load(next); };
  const pendingLlmComments = useMemo(()=>result?.comments.filter(comment=>!LLM_EMOTIONS.includes(comment.sentiment_llm_label as keyof SentimentLLM)).length||0,[result]);
  const activeReanalysis = reanalysis?.status==='analyzing';
  const failedReanalysis = reanalysis?.status==='error';
  const reanalysisTotal = reanalysis?.target_comments ?? reanalysis?.total_comments ?? 0;
  const reanalysisCurrent = reanalysis?.target_comments === undefined ? reanalysis?.processed_comments ?? 0 : Math.max(0,(reanalysis?.processed_comments ?? 0)-((reanalysis?.total_comments ?? 0)-reanalysis.target_comments));
  const reanalysisPanel = !showNlpDuringReanalysis
    ? activeReanalysis
      ? {state:'running' as const,current:reanalysisCurrent,total:reanalysisTotal,statusText:`正在补齐 ${reanalysisTotal.toLocaleString()} 条未完成评论；已完成标签不会再次发送给模型。`,onShowNlp:showNlpAnalysis}
      : failedReanalysis
        ? {state:'error' as const,current:reanalysisCurrent,total:reanalysisTotal,statusText:`已保留 ${reanalysisCurrent.toLocaleString()} / ${reanalysisTotal.toLocaleString()} 条已完成标签。`,errorText:reanalysisErrorMessage(reanalysis),onRetry:()=>setReanalyzeDialog(true),onShowNlp:showNlpAnalysis}
        : undefined
    : undefined;
  const backgroundReanalysis = showNlpDuringReanalysis && (activeReanalysis||failedReanalysis)
    ? {state:(activeReanalysis?'running':'error') as 'running'|'error',current:reanalysisCurrent,total:reanalysisTotal,onShowDetails:()=>setShowNlpDuringReanalysis(false)}
    : undefined;
  if(loading&&!result)return <div className="app-state flex items-center justify-center py-20"><div className="pulse-dot app-state__pulse"/><p className="text-sm text-secondary">正在加载舆情事件…</p></div>;
  if(!result)return <div className="app-alert app-alert--error" role="alert">{error||'无法读取舆情事件。'}</div>;
  const applyFilters = (next: FilterState) => { setFilters(next); onFiltersChange(next); };
  return <AppErrorBoundary diagnosticState={{ route:'/', view_type:'group', group_id:groupId, analysis_mode:mode, loading, reanalyzing:activeReanalysis, keyword_status:keywordStatus, active_filter_fields:activeFilterFields(filters) }}><>{error&&<div className="app-alert app-alert--error" role="alert">{error}</div>}<div className="app-alert app-alert--status">舆情事件 · {mode==='llm'?'大模型十分类':'NLP 三分类'} · 共 {result.total_comments.toLocaleString()} 条评论</div><EventInfo result={result}/><FilterBar filters={filters} onApply={applyFilters} availableRegions={regions} mode={mode} duplicateStatistics={result.duplicate_statistics} duplicateGroups={duplicateGroups} originalCount={result.comments.length} duplicateRetainedCount={duplicateFiltered.length} sources={result.members}/><div className="card-enter mt-4"><AISummaryCard scope={{kind:'group',id:groupId}} filters={filters} matchedCount={filtered.length} mode={mode}/></div><div className="card-enter mt-4"><SourceDistributionPanel sources={result.source_distribution} filteredComments={filtered} mode={mode}/></div><div className="space-y-4 mt-4 distribution-chart-stack"><div className="card-enter"><SentimentChart positive={sentiment.positive} negative={sentiment.negative} neutral={sentiment.neutral} mode={mode} llm={mode==='llm'?llm:null} onModeChange={changeMode} reanalysis={reanalysisPanel} backgroundReanalysis={backgroundReanalysis}/></div><div className="card-enter"><GenderChart male={gender.male} female={gender.female} unknown={gender.unknown}/></div></div><div className="card-enter mt-4"><RegionMap data={region}/></div><div className="card-enter mt-4"><WordCloudCard keywords={keywords} status={keywordStatus} scopeKey={`group:${groupId}`}/></div><div className="card-enter mt-4"><HeatTimeline timeline={heat.timeline} hourlyDistribution={heat.hourly_distribution} peakHour={heat.peak_hour} peakCount={heat.peak_count}/></div><div className="card-enter mt-4"><CommentTable comments={filtered} mode={mode} allCommentRpids={commentKeys} showSource/></div>{reanalyzeDialog&&<div className="reanalyze-dialog" onClick={()=>setReanalyzeDialog(false)}><div className="reanalyze-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="event-reanalyze-title" onClick={event=>event.stopPropagation()}><h3 id="event-reanalyze-title">补齐事件的大模型情感分析</h3><p className="reanalyze-dialog__copy">将仅分析 {pendingLlmComments.toLocaleString()} 条尚未完成的评论；已具备合法大模型十分类标签的评论会保留，并仅作为同源回复上下文使用。</p><p className="reanalyze-dialog__notice">涉及来源：{(result.llm_readiness?.missing_members||[]).map(member=>member.video_title||member.bv).join('、')||'部分来源'}。调用设置中的情绪分析模型，可能产生少量费用。</p><div className="reanalyze-dialog__actions"><button type="button" onClick={()=>setReanalyzeDialog(false)} className="btn btn-ghost">取消</button><button type="button" onClick={()=>void confirmReanalysis()} className="btn btn-primary">确认补齐分析</button></div></div></div>}</></AppErrorBoundary>;
}
