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

  const rankedRegions = data
    .filter(item=>NAME_MAP[item.region])
    .map(item=>({...item,percentage:Number(item.percentage.toFixed(2))}))
    .sort((a,b)=>b.percentage-a.percentage || b.count-a.count || a.region.localeCompare(b.region,'zh-CN'));
  const mapData = rankedRegions.map(item=>({
    name:NAME_MAP[item.region],
    value:item.percentage,
    count:item.count,
  }));

  if (!mapData.length) return <div className="card"><h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>地域分布</h3><div className="flex items-center justify-center h-64 text-muted text-sm">暂无省级地域数据</div></div>;

  const option = {
    tooltip:{
      trigger:'item',
      formatter:(params:unknown)=>{
        const item=params as {name?:string;data?:{count?:number;value?:number}};
        if (!item.data) return `${item.name||''}<br/>暂无地域数据`;
        return `${item.name||''}<br/>评论数：${(item.data.count||0).toLocaleString()} 条<br/>占比：${(item.data.value||0).toFixed(2)}%`;
      },
      backgroundColor:dark?'#1A2030':'#FFF',borderColor:dark?'rgba(148,163,184,.12)':'rgba(0,0,0,.08)',textStyle:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12},
    },
    visualMap:{
      type:'piecewise',left:4,bottom:14,orient:'vertical',itemWidth:20,itemHeight:11,itemGap:10,
      textStyle:{color:dark?'#94A3B8':'#6B7280',fontSize:11},
      pieces:[
        {gt:13,label:'>13%',color:'#9D174D'},
        {gte:9,lte:13,label:'9%–13%',color:'#D9467A'},
        {gte:6,lt:9,label:'6%–9%',color:'#FB7299'},
        {gte:3,lt:6,label:'3%–6%',color:'#F9B4C8'},
        {lt:3,label:'<3%',color:'#FDF2F8'},
      ],
      selectedMode:'multiple',
    },
    geo:{map:'china',roam:false,layoutCenter:['59%','50%'],layoutSize:'98%',itemStyle:{areaColor:'#F3F4F6',borderColor:dark?'rgba(148,163,184,.22)':'#D1D5DB'},label:{color:dark?'#FFF':'#1A1A2E'},emphasis:{itemStyle:{areaColor:dark?'#2D3A50':'#FCE7EF'},label:{color:dark?'#FFF':'#1A1A2E'}}},
    series:[{name:'地域',type:'map',map:'china',geoIndex:0,data:mapData,label:{color:dark?'#FFF':'#1A1A2E'},emphasis:{label:{color:dark?'#FFF':'#1A1A2E'}}}],
  };

  const fallbackOption = {
    tooltip:{trigger:'axis',backgroundColor:dark?'#1A2030':'#FFF',borderColor:dark?'rgba(148,163,184,.12)':'rgba(0,0,0,.08)',textStyle:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12}},
    grid:{left:70,right:24,top:12,bottom:28},
    xAxis:{type:'value',axisLabel:{color:dark?'#94A3B8':'#6B7280'}},
    yAxis:{type:'category',data:rankedRegions.map(item=>item.region),axisLabel:{color:dark?'#E2E8F0':'#1A1A2E',fontSize:12}},
    series:[{type:'bar',data:rankedRegions.map(item=>item.count),barMaxWidth:28,itemStyle:{color:'#FB7299',borderRadius:[0,4,4,0]}}],
  };

  return <div className="card region-distribution-card">
    <div className="flex items-center justify-between mb-2 region-distribution__header">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>地域分布 ({mapData.length} 个省级地区)</h3>
      <DownloadChartButton echartRefs={chartRef} />
    </div>
    <div className="region-distribution__body">
      <div className="region-distribution__map">
        <ReactECharts ref={chartRef} key={(mapLoaded?'map-':'fallback-')+renderKey.current} option={mapLoaded?option:fallbackOption} style={{height:'100%',width:'100%'}}/>
      </div>
      <div className="region-ranking" tabIndex={0} aria-label="地域占比排行，可滚动查看全部地区">
        <table className="region-ranking__table" aria-label="地域占比排行">
          <thead><tr><th scope="col">地区</th><th scope="col">占比</th></tr></thead>
          <tbody>
            {rankedRegions.map(item=><tr key={item.region} title={`${item.count.toLocaleString()} 条评论`}>
              <td>{item.region}</td>
              <td>{item.percentage.toFixed(2)}%</td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  </div>;
}
