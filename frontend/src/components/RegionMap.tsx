import { useEffect, useState, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts';
import type { RegionItem } from '../types';
import { isDarkMode } from '../utils';
import DownloadChartButton from './DownloadChartButton';

interface Props { data: RegionItem[]; }

const NAME_MAP: Record<string, string> = {
  '北京':'北京市','天津':'天津市','上海':'上海市','重庆':'重庆市',
  '河北':'河北省','山西':'山西省','辽宁':'辽宁省','吉林':'吉林省',
  '黑龙江':'黑龙江省','江苏':'江苏省','浙江':'浙江省','安徽':'安徽省',
  '福建':'福建省','江西':'江西省','山东':'山东省','河南':'河南省',
  '湖北':'湖北省','湖南':'湖南省','广东':'广东省','海南':'海南省',
  '四川':'四川省','贵州':'贵州省','云南':'云南省','陕西':'陕西省',
  '甘肃':'甘肃省','青海':'青海省','台湾':'台湾省',
  '内蒙古':'内蒙古自治区','广西':'广西壮族自治区',
  '西藏':'西藏自治区','宁夏':'宁夏回族自治区',
  '新疆':'新疆维吾尔自治区','香港':'香港特别行政区','澳门':'澳门特别行政区',
};

export default function RegionMap({ data }: Props) {
  const [dark, setDark] = useState(isDarkMode());
  const [mapLoaded, setMapLoaded] = useState(false);
  const renderKey = useRef(0);
  const chartRef = useRef<ReactECharts | null>(null);

  useEffect(() => {
    fetch('/china.json').then(r=>r.json()).then(g=>{echarts.registerMap('china',g);setMapLoaded(true)}).catch(()=>setMapLoaded(false));
  }, []);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onThemeChange = () => { setDark(isDarkMode()); renderKey.current++; };
    mq.addEventListener('change', onThemeChange);
    const observer = new MutationObserver(onThemeChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { mq.removeEventListener('change', onThemeChange); observer.disconnect(); };
  }, []);

  const mapData = data.filter(d=>NAME_MAP[d.region]).map(d=>({name:NAME_MAP[d.region],value:d.count}));
  const rankedMapData = [...mapData].sort((a,b)=>b.value-a.value || a.name.localeCompare(b.name,'zh-CN'));
  const mapMax = Math.max(...mapData.map(d=>d.value),1);
  const labelColor = dark ? '#CBD5E1' : '#4B5563';
  const legendLabelSpan = 205;
  const uniqueValueRegions = rankedMapData.filter((region,index,regions)=>index===0 || region.value!==regions[index-1].value);
  const lowestUniqueRegion = uniqueValueRegions[uniqueValueRegions.length-1];
  const selectedRegionLabels = uniqueValueRegions.slice(0,-1).reduce<Array<{name:string;value:number;top:number}>>((selected,region)=>{
    if (selected.length>=5) return selected;
    const top = Math.round((1-region.value/mapMax)*legendLabelSpan);
    if (selected.every(item=>Math.abs(item.top-top)>=27)) selected.push({...region,top});
    return selected;
  },[]);
  if (lowestUniqueRegion) {
    const lowestLabel = {...lowestUniqueRegion,top:Math.round((1-lowestUniqueRegion.value/mapMax)*legendLabelSpan)};
    const lastSelected = selectedRegionLabels[selectedRegionLabels.length-1];
    if (!lastSelected || lowestLabel.top-lastSelected.top>=27) selectedRegionLabels.push(lowestLabel);
    else if (selectedRegionLabels.length>1) selectedRegionLabels[selectedRegionLabels.length-1]=lowestLabel;
  }
  const regionScaleGraphic = {
    type:'group', left:58, top:85, silent:true,
    children:selectedRegionLabels.map(region=>({
      type:'text',left:0,top:region.top,
      style:{text:`${region.name}  ${region.value} 条`,fill:labelColor,font:'500 10px sans-serif'},
    })),
  };

  if (!mapData.length) return <div className="card"><h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>地域分布</h3><div className="flex items-center justify-center h-64 text-muted text-sm">暂无省级地域数据</div></div>;

  const option = {
    tooltip:{trigger:'item',formatter:'{b}: {c} 条',backgroundColor:dark?'#1A2030':'#FFF',borderColor:dark?'rgba(148,163,184,.12)':'rgba(0,0,0,.08)',textStyle:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12}},
    visualMap:{min:0,max:mapMax,left:12,top:70,itemWidth:16,itemHeight:180,orient:'vertical',text:['高','低'],textGap:8,textStyle:{color:dark?'#94A3B8':'#6B7280'},inRange:{color:dark?['#1E293B','#FB7299','#FDF2F8']:['#FEF2F2','#FB7299','#9D174D']},calculable:false},
    graphic:[regionScaleGraphic],
    geo:{map:'china',roam:false,layoutCenter:['50%','52%'],layoutSize:'100%',itemStyle:{areaColor:dark?'#1A2030':'#F3F4F6',borderColor:dark?'rgba(148,163,184,.15)':'#D1D5DB'},emphasis:{itemStyle:{areaColor:dark?'#2D3A50':'#DBEAFE'}}},
    series:[{name:'地域',type:'map',map:'china',geoIndex:0,data:mapData}],
  };

  if (!mapLoaded) {
    const sorted = [...data].sort((a,b)=>b.count-a.count);
    return <div className="card"><div className="flex items-center justify-between mb-2"><h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>地域分布</h3><DownloadChartButton echartRefs={chartRef} /></div><ReactECharts ref={chartRef} key={'fallback-'+renderKey.current} option={{tooltip:{trigger:'axis',backgroundColor:dark?'#1A2030':'#FFF',borderColor:dark?'rgba(148,163,184,.12)':'rgba(0,0,0,.08)',textStyle:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12}},grid:{left:70,right:40,top:10,bottom:20},xAxis:{type:'value',axisLabel:{color:dark?'#94A3B8':'#6B7280'}},yAxis:{type:'category',data:sorted.map(d=>d.region),axisLabel:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12}},series:[{type:'bar',data:sorted.map(d=>d.count),barMaxWidth:36,itemStyle:{color:'#FB7299',borderRadius:[0,4,4,0]}}]}} style={{height:300}}/></div>;
  }

  return <div className="card"><div className="flex items-center justify-between mb-2"><h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>地域分布 ({mapData.length} 个省级地区)</h3><DownloadChartButton echartRefs={chartRef} /></div><ReactECharts ref={chartRef} key={'map-'+renderKey.current} option={option} style={{height:360}}/></div>;
}
