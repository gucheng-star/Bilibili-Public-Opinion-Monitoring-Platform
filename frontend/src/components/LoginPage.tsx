import { useEffect, useState } from 'react';

interface Props { onLogin: () => void; }

interface Account { cookie: string; name: string; }

export default function LoginPage({ onLogin }: Props) {
  const [step, setStep] = useState<'welcome'|'qrcode'>('welcome');
  const [qrUrl, setQrUrl] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadingAcc, setLoadingAcc] = useState(false);

  useEffect(() => {
    fetch('/api/auth/accounts').then(r=>r.json()).then(d=>setAccounts(d.accounts||[])).catch(()=>{});
  }, []);

  const startQrLogin = () => {
    setStep('qrcode'); setError(''); setStatus('正在生成二维码...');
    fetch('/api/auth/qrcode').then(r=>r.json()).then(d=>{
      if (d.error) { setError(d.error); return; }
      setQrUrl(d.url); setStatus('请使用B站App扫码登录');
      pollStatus(d.qrcode_key);
    }).catch(()=>setError('网络错误'));
  };

  const pollStatus = async (key: string) => {
    for (let i=0;i<120;i++) {
      await new Promise(r=>setTimeout(r,2000));
      try {
        const r=await fetch('/api/auth/qrcode/status?qrcode_key='+key);
        const d=await r.json();
        if (d.status==='success'){onLogin();return;}
        if (d.status==='scanned')setStatus('已扫码，请在手机上确认...');
        if (d.status==='expired'){setError('二维码已过期');setStep('welcome');break;}
        if (d.status==='error'){setError('登录失败');break;}
      }catch{setError('网络错误');break;}
    }
  };

  const switchAccount = async (index: number) => {
    setLoadingAcc(true);
    try {
      const r = await fetch('/api/auth/accounts/' + index + '/switch', {method:'POST'});
      const d = await r.json();
      if (d.ok) onLogin();
    } catch {}
    setLoadingAcc(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center" style={{background:'var(--bg)'}}>
      {step === 'welcome' ? (
        <div className="card text-center" style={{maxWidth:'26rem',padding:'2.5rem 2rem'}}>
          <div style={{fontSize:'2rem',fontWeight:700,color:'var(--accent)',marginBottom:'.25rem'}}>B站</div>
          <div className="text-primary" style={{fontSize:'1.125rem',fontWeight:600,marginBottom:'1.5rem'}}>舆论监测平台</div>

          <p className="text-secondary text-sm mb-4" style={{lineHeight:1.6}}>
            分析B站视频评论区的舆情数据，包括情感倾向、地域分布、关键词云等维度的可视化展示。
          </p>

          <div style={{background:'var(--accent-soft)',border:'1px solid var(--border-accent)',borderRadius:'.5rem',padding:'.75rem 1rem',marginBottom:'1.5rem'}}>
            <p className="text-xs" style={{color:'var(--accent)',lineHeight:1.5}}>
              登录仅用于抓取B站评论区数据，不会获取您的个人信息，也不会进行任何其他操作。
            </p>
          </div>

          {accounts.length > 0 && (
            <div style={{marginBottom:'1.25rem'}}>
              <p className="text-xs text-muted mb-2">已保存的账号</p>
              <div className="space-y-2">
                {accounts.map((acc, i) => (
                  <button key={i} onClick={() => switchAccount(i)} disabled={loadingAcc}
                    style={{
                      width:'100%', padding:'.625rem 1rem', fontSize:'.8125rem', textAlign:'left',
                      background:'var(--bg-card)', border:'1px solid var(--border)',
                      borderRadius:'.5rem', cursor:'pointer', color:'var(--text-primary)',
                      display:'flex', alignItems:'center', gap:'.5rem',
                      transition:'all .15s ease',
                    }}
                    onMouseOver={e=>e.currentTarget.style.borderColor='var(--accent)'}
                    onMouseOut={e=>e.currentTarget.style.borderColor='var(--border)'}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
                    </svg>
                    <span>{acc.name}</span>
                    <span className="flex-1"/>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{color:'var(--text-muted)'}}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7"/>
                    </svg>
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3 mt-3">
                <div style={{flex:1,height:'1px',background:'var(--border)'}}/>
                <span className="text-xs text-muted">或</span>
                <div style={{flex:1,height:'1px',background:'var(--border)'}}/>
              </div>
            </div>
          )}

          <button onClick={startQrLogin} className="btn-analyze" style={{width:'100%',justifyContent:'center'}}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
              <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
            </svg>
            {accounts.length > 0 ? '新账号：B站App扫码登录' : '使用B站App扫码登录'}
          </button>
        </div>
      ) : (
        <div className="card text-center" style={{maxWidth:'22rem',padding:'2rem'}}>
          <div style={{fontSize:'1.25rem',fontWeight:700,color:'var(--accent)',marginBottom:'.25rem'}}>扫码登录</div>
          <p className="text-xs text-muted mb-4">登录仅用于抓取评论数据</p>
          {error && <div style={{padding:'.5rem',background:'var(--red-soft)',border:'1px solid var(--red)',borderRadius:'.375rem',color:'var(--red)',fontSize:'.75rem',marginBottom:'1rem'}}>{error} <button onClick={startQrLogin} style={{marginLeft:'.5rem',background:'none',border:'none',color:'var(--accent)',cursor:'pointer',fontSize:'.75rem'}}>重试</button></div>}
          {qrUrl && !error && <img src={'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data='+encodeURIComponent(qrUrl)} alt="QR" style={{width:'12.5rem',height:'12.5rem',borderRadius:'.5rem',margin:'0 auto',display:'block'}}/>}
          {!qrUrl && !error && <div className="pulse-dot" style={{margin:'0 auto'}}></div>}
          <div className="text-secondary text-sm mt-3">{status}</div>
          <button onClick={()=>setStep('welcome')} style={{marginTop:'1rem',fontSize:'.75rem',color:'var(--text-muted)',background:'none',border:'none',cursor:'pointer'}}>返回首页</button>
        </div>
      )}
    </div>
  );
}