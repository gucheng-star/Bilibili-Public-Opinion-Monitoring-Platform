import { useEffect, useRef, useState } from 'react';
import ThemeToggle from './ThemeToggle';
import { getAuthAccounts, getQRCode, getQRCodeStatus, switchAuthAccount } from '../services/api';
import './LoginPage.css';
import './LoginWorkbench.css';

interface Props { onLogin: () => void; }

interface Account { index: number; name: string; }

function isPngDataUrl(value: unknown): value is string {
  return typeof value === 'string' && /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/i.test(value);
}

export default function LoginPage({ onLogin }: Props) {
  const [step, setStep] = useState<'welcome'|'qrcode'>('welcome');
  const [qrImageDataUrl, setQrImageDataUrl] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadingAcc, setLoadingAcc] = useState(false);
  const [accountError, setAccountError] = useState('');
  const qrAttemptRef = useRef(0);

  useEffect(() => {
    getAuthAccounts().then(d=>setAccounts(d.accounts || [])).catch(()=>{});
  }, []);

  useEffect(() => () => { qrAttemptRef.current += 1; }, []);

  const startQrLogin = () => {
    const attempt = ++qrAttemptRef.current;
    setStep('qrcode'); setError(''); setAccountError(''); setQrImageDataUrl(''); setStatus('正在生成二维码...');
    getQRCode().then(d=>{
      if (attempt !== qrAttemptRef.current) return;
      if (d.error || !d.qrcode_key || !isPngDataUrl(d.image_data_url)) {
        setStatus('');
        setError(d.error || '二维码生成失败，请重试');
        return;
      }
      setQrImageDataUrl(d.image_data_url); setStatus('请使用B站App扫码登录');
      void pollStatus(d.qrcode_key, attempt);
    }).catch(()=>{
      if (attempt === qrAttemptRef.current) { setStatus(''); setError('网络错误，请重试'); }
    });
  };

  const pollStatus = async (key: string, attempt: number) => {
    for (let i=0;i<120;i++) {
      await new Promise(r=>setTimeout(r,2000));
      if (attempt !== qrAttemptRef.current) return;
      try {
        const d=await getQRCodeStatus(key);
        if (attempt !== qrAttemptRef.current) return;
        if (d.status==='success'){onLogin();return;}
        if (d.status==='scanned')setStatus('已扫码，请在手机上确认...');
        if (d.status==='expired'){setQrImageDataUrl('');setStatus('');setError('二维码已过期，请重新生成');return;}
        if (d.status==='error' || d.status==='unknown'){
          setQrImageDataUrl(''); setStatus('');
          setError(d.message || '登录状态异常，请重新生成二维码');
          return;
        }
      }catch{setQrImageDataUrl('');setStatus('');setError('网络错误，请重试');return;}
    }
    if (attempt === qrAttemptRef.current) {
      setQrImageDataUrl(''); setStatus(''); setError('二维码已超时，请重新生成');
    }
  };

  const handleQrImageError = (event: React.SyntheticEvent<HTMLImageElement>) => {
    event.currentTarget.style.visibility = 'hidden';
    qrAttemptRef.current += 1;
    setQrImageDataUrl('');
    setStatus('');
    setError('二维码加载失败，请重试');
  };

  const switchAccount = async (index: number) => {
    setAccountError('');
    setLoadingAcc(true);
    try {
      const d = await switchAuthAccount(index);
      if (d.ok) {
        onLogin();
        return;
      }
      setAccountError('切换账号失败。该登录信息可能已失效，请使用扫码登录。');
    } catch {
      setAccountError('暂时无法切换账号，请检查网络后重试，或使用扫码登录。');
    } finally {
      setLoadingAcc(false);
    }
  };

  return (
    <main className="login-page">
      <div className="login-workbench">
      <section className="login-intro" aria-label="平台介绍">
        <div className="login-intro-content">
          <div className="login-brand"><img className="login-brand-mark" src="/signal-observatory-icon.png" alt="" aria-hidden="true" /> SIGNAL OBSERVATORY</div>
          <p className="login-kicker">BILIBILI PUBLIC OPINION MONITORING</p>
          <h1>捕捉每一段<br/><em>正在发酵的声音。</em></h1>
          <p className="login-description">从评论区的微弱信号到可行动的舆情洞察，以清晰的视角观测视频内容的真实回响。</p>
          <div className="login-capabilities"><span>情感波形</span><span>热点追踪</span><span>地域洞察</span></div>
        </div><div className="login-scanline" aria-hidden="true"/><p className="login-intro-footer">VIDEO SIGNAL / 24H OBSERVATION</p>
      </section>
      <section className="login-access" aria-label="登录">
      <div className="login-theme-control">
        <span>界面外观</span>
        <ThemeToggle />
      </div>
      {step === 'welcome' ? (
        <div className="login-card">
          <header className="login-card-header"><p className="login-kicker">SECURE ACCESS</p><h2>进入观测台</h2><p>使用 B 站账号授权，开始分析评论区信号。</p></header>

          <p className="login-notice">
            分析B站视频评论区的舆情数据，包括情感倾向、地域分布、关键词云等维度的可视化展示。
          </p>

          <div className="login-privacy">
            <p className="text-xs">
              登录仅用于抓取B站评论区数据，不会获取您的个人信息，也不会进行任何其他操作。
            </p>
          </div>

          {accounts.length > 0 && (
            <div className="saved-accounts">
              <p className="saved-accounts-label">已保存的账号</p>
              <div className="saved-accounts-list">
                {accounts.map((acc) => (
                  <button key={acc.index} onClick={() => switchAccount(acc.index)} disabled={loadingAcc}
                    className="account-option"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
                    </svg>
                    <span>{acc.name}</span>
                    <span className="account-arrow" aria-hidden="true">{loadingAcc ? '切换中…' : '→'}</span>
                  </button>
                ))}
              </div>
              {accountError && <div className="login-error" role="alert">{accountError}</div>}
              <div className="login-divider"><span>或使用新账号</span></div>
            </div>
          )}

          <button onClick={startQrLogin} className="login-primary-button">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
              <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
            </svg>
            {accounts.length > 0 ? '新账号：B站App扫码登录' : '使用B站App扫码登录'}
          </button>
        </div>
      ) : (
        <div className="login-card">
          <header className="login-card-header login-qr-header"><p className="login-kicker">SCAN TO CONNECT</p><h2>扫码登录</h2><p>打开 B站 App，扫描下方二维码完成授权。</p></header>
          {error && <div className="login-error" role="alert">{error} <button onClick={startQrLogin}>重试</button></div>}
          <div className="qr-frame">{qrImageDataUrl && !error && <img src={qrImageDataUrl} alt="B站登录二维码" onError={handleQrImageError}/>} {!qrImageDataUrl && !error && <div className="pulse-dot" aria-label="正在生成二维码"/>}</div>
          <p className="login-status" aria-live="polite">{status}</p>
          <button onClick={()=>{ qrAttemptRef.current += 1; setQrImageDataUrl(''); setStep('welcome'); }} className="login-back-button">← 返回登录方式</button>
        </div>
      )}
      </section>
      </div>
    </main>
  );
}
