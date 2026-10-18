'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

/* Continuous Live Liquidity Mesh Component */
function ContinuousLiquidityMesh({ subtle = false }: { subtle?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = 0;
    let height = 0;
    let dpr = 1;

    const updateDimensions = () => {
      if (!canvas) return;
      dpr = window.devicePixelRatio || 1;
      width = canvas.offsetWidth;
      height = canvas.offsetHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);

    // Distributed nodes filling entire canvas (left whitespace, right whitespace, center, top, bottom)
    const nodeCount = subtle ? 18 : 28;
    const cols = 6;
    const rows = 5;

    // Node labels matching the homepage
    const labelsMap: Record<number, string> = {
      2: 'PARALLEL DISCOVERY',
      7: 'AI NEGOTIATION',
      11: 'RAZORPAY //01',
      16: 'MARGIN PROTECTION',
      22: 'HMAC //VALID',
    };

    const nodes = Array.from({ length: nodeCount }, (_, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const baseX = ((col + 0.5) / cols) * width;
      const baseY = ((row + 0.5) / rows) * height;

      return {
        x: Math.max(30, Math.min(width - 30, baseX + (Math.random() - 0.5) * (width / cols) * 0.8)),
        y: Math.max(30, Math.min(height - 30, baseY + (Math.random() - 0.5) * (height / rows) * 0.8)),
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        radius: subtle ? 3 : 4,
        phase: Math.random() * Math.PI * 2,
        label: !subtle ? labelsMap[i] || null : null,
      };
    });

    // Luminous moving packets traveling between connected nodes
    interface Packet {
      from: number;
      to: number;
      progress: number;
      speed: number;
    }
    const packets: Packet[] = [];

    const maxDistance = subtle ? 280 : 340;
    const gridSpacing = 96;

    let lastTime = performance.now();

    const render = (currentTime: number) => {
      const dt = Math.min((currentTime - lastTime) / 1000, 0.1);
      lastTime = currentTime;

      ctx.clearRect(0, 0, width, height);

      // 1. Background Cartesian grid spanning entire whitespace
      ctx.strokeStyle = 'rgba(13, 148, 251, 0.07)';
      ctx.lineWidth = 0.75;

      for (let x = 0; x <= width; x += gridSpacing) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y <= height; y += gridSpacing) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Crosshairs at grid intersections
      ctx.strokeStyle = 'rgba(13, 148, 251, 0.25)';
      ctx.lineWidth = 1;
      const crossSize = 3;
      for (let x = 0; x <= width; x += gridSpacing) {
        for (let y = 0; y <= height; y += gridSpacing) {
          ctx.beginPath();
          ctx.moveTo(x - crossSize, y);
          ctx.lineTo(x + crossSize, y);
          ctx.moveTo(x, y - crossSize);
          ctx.lineTo(x, y + crossSize);
          ctx.stroke();
        }
      }

      // 2. Continuous smooth physics for nodes (No snaps, soft boundary turnaround)
      for (const node of nodes) {
        node.x += node.vx;
        node.y += node.vy;

        if (node.x < 30) {
          node.x = 30;
          node.vx = Math.abs(node.vx);
        } else if (node.x > width - 30) {
          node.x = width - 30;
          node.vx = -Math.abs(node.vx);
        }

        if (node.y < 30) {
          node.y = 30;
          node.vy = Math.abs(node.vy);
        } else if (node.y > height - 30) {
          node.y = height - 30;
          node.vy = -Math.abs(node.vy);
        }

        node.phase += dt * 1.5;
      }

      // 3. Connect nodes across the entire canvas (whitespace and behind terminal box)
      const activeConnections: [number, number][] = [];

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);

          if (dist < maxDistance) {
            activeConnections.push([i, j]);
            const alpha = (1 - dist / maxDistance) * (subtle ? 0.14 : 0.24);

            ctx.strokeStyle = `rgba(13, 148, 251, ${alpha})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      // Maintain continuous flowing packets
      while (packets.length < (subtle ? 3 : 7) && activeConnections.length > 0) {
        const randConn = activeConnections[Math.floor(Math.random() * activeConnections.length)];
        packets.push({
          from: randConn[0],
          to: randConn[1],
          progress: 0,
          speed: 0.12 + Math.random() * 0.15,
        });
      }

      // 4. Update and draw flowing signal packets
      for (let p = packets.length - 1; p >= 0; p--) {
        const pkt = packets[p];
        pkt.progress += pkt.speed * dt;

        if (pkt.progress >= 1) {
          packets.splice(p, 1);
          continue;
        }

        const nodeA = nodes[pkt.from];
        const nodeB = nodes[pkt.to];
        if (!nodeA || !nodeB) {
          packets.splice(p, 1);
          continue;
        }

        const px = nodeA.x + (nodeB.x - nodeA.x) * pkt.progress;
        const py = nodeA.y + (nodeB.y - nodeA.y) * pkt.progress;

        ctx.fillStyle = '#0D94FB';
        ctx.shadowColor = '#0D94FB';
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.arc(px, py, 2.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // 5. Draw precision radar nodes and ambient halos
      for (const node of nodes) {
        const pulse = Math.sin(node.phase) * 0.5 + 0.5;
        const haloRadius = 14 + pulse * 7;

        // Outer soft glow
        const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, haloRadius);
        glow.addColorStop(0, 'rgba(13, 148, 251, 0.42)');
        glow.addColorStop(0.5, 'rgba(13, 148, 251, 0.11)');
        glow.addColorStop(1, 'rgba(13, 148, 251, 0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(node.x, node.y, haloRadius, 0, Math.PI * 2);
        ctx.fill();

        // Concentric radar ring
        ctx.strokeStyle = `rgba(13, 148, 251, ${0.3 + pulse * 0.35})`;
        ctx.lineWidth = 0.75;
        ctx.beginPath();
        ctx.arc(node.x, node.y, subtle ? 9 : 12, 0, Math.PI * 2);
        ctx.stroke();

        // Node center core
        ctx.fillStyle = '#0D94FB';
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fill();

        // Inner white ping dot
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius * 0.45, 0, Math.PI * 2);
        ctx.fill();

        // Monospace telemetry tags
        if (node.label && !subtle) {
          ctx.fillStyle = 'rgba(13, 148, 251, 0.75)';
          ctx.font = `bold 9px monospace`;
          ctx.fillText(node.label, node.x + 14, node.y + 3);
        }
      }

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', updateDimensions);
    };
  }, [subtle]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none select-none"
      aria-hidden="true"
    />
  );
}

export default function AuthPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('buyer'); // Only used for registration
  const [loading, setLoading] = useState(false);
  const [slowLoading, setSlowLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const router = useRouter();

  // Monitor loading duration to inform users if backend is cold-starting
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (loading) {
      timer = setTimeout(() => setSlowLoading(true), 3000);
    } else {
      setSlowLoading(false);
    }
    return () => clearTimeout(timer);
  }, [loading]);

  const fillDemo = (demoUser: string, demoPass: string, demoRole: 'buyer' | 'merchant') => {
    setIsLogin(true);
    setUsername(demoUser);
    setPassword(demoPass);
    setRole(demoRole);
    setError('');
    setSuccess('');
  };

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.get('mode') === 'register') {
        setIsLogin(false);
      }

      // Check if user already has an active authenticated session
      const token = localStorage.getItem('token');
      if (token) {
        api.getMe()
          .then((user) => {
            if (user && user.role) {
              if (user.role === 'merchant') {
                router.replace('/merchant');
              } else {
                router.replace('/buyer');
              }
            }
          })
          .catch(() => {
            // Token is invalid and silent refresh failed; cleanly purge
            localStorage.removeItem('token');
            localStorage.removeItem('role');
          });
      }
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    try {
      // Defense-in-depth client-side validation
      const cleanedUsername = username.trim();
      if (cleanedUsername.length < 3 || cleanedUsername.length > 30) {
        setError('Username must be between 3 and 30 characters.');
        setLoading(false);
        return;
      }
      if (!/^[a-zA-Z0-9_]+$/.test(cleanedUsername)) {
        setError('Username can only contain alphanumeric characters and underscores.');
        setLoading(false);
        return;
      }
      if (password.length < 6) {
        setError('Password must be at least 6 characters long.');
        setLoading(false);
        return;
      }

      if (isLogin) {
        const formData = new FormData();
        formData.append('username', cleanedUsername);
        formData.append('password', password);

        const data = await api.login(formData);
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('role', data.role);

        // Redirect based on role
        if (data.role === 'merchant') {
          router.push('/merchant');
        } else {
          router.push('/buyer');
        }
      } else {
        // Register flow
        await api.register({ username: cleanedUsername, password, role });
        setSuccess('Registration successful! Please sign in with your credentials.');
        setIsLogin(true);
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#dceeff] text-[#000000] antialiased selection:bg-[#0D94FB] selection:text-[#ffffff] relative overflow-hidden">
      
      {/* 1. Full-Bleed Top Marquee Banner: 100% Seamless Infinite Loop with Zero Glitches */}
      <div 
        className="w-full bg-[#000000] text-[#ffffff] border-b border-[#000000] py-2.5 overflow-hidden select-none relative z-30"
        aria-hidden="true"
      >
        <div className="animate-slush-marquee flex w-max">
          {/* Track 1 */}
          <div className="flex shrink-0 items-center gap-8 px-4 text-[12px] font-bold uppercase tracking-[0.032em] whitespace-nowrap">
            <span>ZERO LEAKAGE MARGIN FLOORS</span>
            <span>•</span>
            <span>AUTONOMOUS AI NEGOTIATION</span>
            <span>•</span>
            <span>HMAC SHA-256 CART MANDATES</span>
            <span>•</span>
            <span>DUAL HUMAN MUTUAL CONSENSUS</span>
            <span>•</span>
            <span>RAZORPAY STANDARD SETTLEMENT</span>
            <span>•</span>
            <span>15 MINUTE INVENTORY LOCK</span>
            <span>•</span>
            <span>AUTONOMOUS MULTI MERCHANT SOURCING</span>
            <span>•</span>
            <span>ZERO LEAKAGE MARGIN FLOORS</span>
            <span>•</span>
            <span>AUTONOMOUS AI NEGOTIATION</span>
            <span>•</span>
            <span>HMAC SHA-256 CART MANDATES</span>
            <span>•</span>
            <span>DUAL HUMAN MUTUAL CONSENSUS</span>
            <span>•</span>
            <span>RAZORPAY STANDARD SETTLEMENT</span>
            <span>•</span>
            <span>15 MINUTE INVENTORY LOCK</span>
            <span>•</span>
            <span>AUTONOMOUS MULTI MERCHANT SOURCING</span>
            <span>•</span>
          </div>

          {/* Track 2: Exact duplicate for infinite seamless mathematical wrapping */}
          <div className="flex shrink-0 items-center gap-8 px-4 text-[12px] font-bold uppercase tracking-[0.032em] whitespace-nowrap" aria-hidden="true">
            <span>ZERO LEAKAGE MARGIN FLOORS</span>
            <span>•</span>
            <span>AUTONOMOUS AI NEGOTIATION</span>
            <span>•</span>
            <span>HMAC SHA-256 CART MANDATES</span>
            <span>•</span>
            <span>DUAL HUMAN MUTUAL CONSENSUS</span>
            <span>•</span>
            <span>RAZORPAY STANDARD SETTLEMENT</span>
            <span>•</span>
            <span>15 MINUTE INVENTORY LOCK</span>
            <span>•</span>
            <span>AUTONOMOUS MULTI MERCHANT SOURCING</span>
            <span>•</span>
            <span>ZERO LEAKAGE MARGIN FLOORS</span>
            <span>•</span>
            <span>AUTONOMOUS AI NEGOTIATION</span>
            <span>•</span>
            <span>HMAC SHA-256 CART MANDATES</span>
            <span>•</span>
            <span>DUAL HUMAN MUTUAL CONSENSUS</span>
            <span>•</span>
            <span>RAZORPAY STANDARD SETTLEMENT</span>
            <span>•</span>
            <span>15 MINUTE INVENTORY LOCK</span>
            <span>•</span>
            <span>AUTONOMOUS MULTI MERCHANT SOURCING</span>
            <span>•</span>
          </div>
        </div>
      </div>

      {/* 2. Top-Right Corner "Back to Home" Button */}
      <div className="w-full flex justify-end px-6 sm:px-12 py-3 relative z-20">
        <Link
          href="/"
          className="px-4 py-2 min-h-[38px] inline-flex items-center justify-center text-xs font-bold tracking-wider uppercase rounded-full border border-[#000000] bg-[#ffffff] text-[#000000] hover:bg-[#e9e9e9] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] transition-all gap-1.5 shadow-xs"
        >
          <span>←</span>
          <span>Back to Home</span>
        </Link>
      </div>

      {/* 3. Main Auth Canvas with Continuous Liquidity Mesh and Normal Proportional Nexus Terminal Box */}
      <main className="flex-1 flex items-center justify-center p-6 relative overflow-hidden">
        
        {/* Continuous Live Liquidity Mesh across entire canvas */}
        <ContinuousLiquidityMesh />

        {/* Normal Proportional Nexus Terminal Box (max-w-md / 448px with clean balanced padding) */}
        <div className="w-full max-w-md bg-[#ffffff] border border-[#000000] rounded-2xl p-6 sm:p-8 relative z-10 shadow-lg">
          
          <div className="text-center mb-6">
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight uppercase leading-tight text-[#000000]">
              Nexus Terminal
            </h1>
          </div>

          {/* Quick Demo Access Bar */}
          <div className="mb-5 p-3 rounded-xl bg-slate-50 border border-slate-200">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2 flex items-center justify-between">
              <span>Quick Demo Identities</span>
              <span className="text-[9px] font-mono text-slate-400">1-click fill</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              <button
                type="button"
                onClick={() => fillDemo('retail_purchaser', 'retail_purchaser', 'buyer')}
                className="px-2 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-[#0D94FB]/10 hover:border-[#0D94FB] text-slate-800 text-[11px] font-bold tracking-tight text-center transition-all truncate"
                title="Buyer: retail_purchaser"
              >
                Buyer
              </button>
              <button
                type="button"
                onClick={() => fillDemo('nexus_wholesaler', 'nexus_wholesaler', 'merchant')}
                className="px-2 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-[#0D94FB]/10 hover:border-[#0D94FB] text-slate-800 text-[11px] font-bold tracking-tight text-center transition-all truncate"
                title="Merchant A: nexus_wholesaler"
              >
                Merchant A
              </button>
              <button
                type="button"
                onClick={() => fillDemo('apex_distributor', 'apex_distributor', 'merchant')}
                className="px-2 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-[#0D94FB]/10 hover:border-[#0D94FB] text-slate-800 text-[11px] font-bold tracking-tight text-center transition-all truncate"
                title="Merchant B: apex_distributor"
              >
                Merchant B
              </button>
            </div>
          </div>

          {/* Mode Switcher Pill */}
          <div 
            role="tablist"
            aria-label="Authentication Mode"
            className="flex p-1 rounded-full border border-[#000000] bg-[#f0f0f0] mb-6"
          >
            <button
              type="button"
              role="tab"
              id="tab-auth-login"
              aria-selected={isLogin}
              onClick={() => { setIsLogin(true); setError(''); setSuccess(''); }}
              className={`flex-1 py-2 rounded-full text-xs font-bold tracking-wider uppercase transition-all min-h-[38px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] active:scale-[0.98] ${
                isLogin
                  ? 'bg-[#000000] text-[#ffffff]'
                  : 'text-[#000000] hover:bg-[#ffffff]/60'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              role="tab"
              id="tab-auth-register"
              aria-selected={!isLogin}
              onClick={() => { setIsLogin(false); setError(''); setSuccess(''); }}
              className={`flex-1 py-2 rounded-full text-xs font-bold tracking-wider uppercase transition-all min-h-[38px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] active:scale-[0.98] ${
                !isLogin
                  ? 'bg-[#000000] text-[#ffffff]'
                  : 'text-[#000000] hover:bg-[#ffffff]/60'
              }`}
            >
              Register
            </button>
          </div>

          {/* Error Banner */}
          {error && (
            <div 
              role="alert"
              aria-live="assertive"
              className="mb-4 p-3 bg-[#ffffff] border border-red-300 text-red-700 text-xs font-mono font-medium rounded-xl"
            >
              {error}
            </div>
          )}

          {/* Success Banner */}
          {success && (
            <div 
              role="status"
              aria-live="polite"
              className="mb-4 p-3 bg-[#ffffff] border border-emerald-300 text-emerald-800 text-xs font-mono font-medium rounded-xl"
            >
              {success}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label 
                htmlFor="auth-username"
                className="block text-xs uppercase font-bold tracking-wider text-[#000000] mb-1.5"
              >
                Identity Protocol (Username)
              </label>
              <input
                id="auth-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. retail_purchaser"
                className="w-full py-2.5 px-3.5 rounded-xl bg-[#ffffff] border border-slate-300 focus:border-[#000000] text-[#000000] font-mono text-sm placeholder:text-[#000000]/35 focus:outline-none focus:ring-1 focus:ring-[#000000] transition-all"
                required
              />
              <p className="mt-1 text-[11px] text-slate-500 font-mono">
                3–30 characters, alphanumeric & underscores only
              </p>
            </div>

            <div>
              <label 
                htmlFor="auth-password"
                className="block text-xs uppercase font-bold tracking-wider text-[#000000] mb-1.5"
              >
                Access Key (Password)
              </label>
              <input
                id="auth-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full py-2.5 px-3.5 rounded-xl bg-[#ffffff] border border-slate-300 focus:border-[#000000] text-[#000000] font-mono text-sm placeholder:text-[#000000]/35 focus:outline-none focus:ring-1 focus:ring-[#000000] transition-all"
                required
              />
              <p className="mt-1 text-[11px] text-slate-500 font-mono">
                Minimum 6 characters
              </p>
            </div>

            {!isLogin && (
              <div>
                <label 
                  htmlFor="auth-role"
                  className="block text-xs uppercase font-bold tracking-wider text-[#000000] mb-1.5"
                >
                  Network Role
                </label>
                <select
                  id="auth-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full py-2.5 px-3.5 rounded-xl bg-[#ffffff] border border-slate-300 focus:border-[#000000] text-[#000000] font-mono text-sm focus:outline-none focus:ring-1 focus:ring-[#000000] transition-all"
                >
                  <option value="buyer">Procurement Agent (Buyer)</option>
                  <option value="merchant">Wholesaler Node (Merchant)</option>
                </select>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-5 rounded-full border border-[#000000] bg-[#000000] text-[#ffffff] font-bold text-xs sm:text-sm uppercase tracking-wider hover:bg-[#000000]/85 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] transition-all disabled:opacity-50 mt-2 flex flex-col items-center justify-center gap-1 shadow-xs min-h-[48px]"
            >
              {loading ? (
                <>
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Authenticating Node...
                  </span>
                  {slowLoading && (
                    <span className="text-[10px] text-amber-300 font-mono normal-case tracking-normal">
                      Server warming up (first request takes ~30s on Render free tier)...
                    </span>
                  )}
                </>
              ) : (
                <div className="flex items-center gap-2">
                  <span>{isLogin ? 'Initialize Session' : 'Create Identity'}</span>
                  <span>→</span>
                </div>
              )}
            </button>
          </form>

        </div>

      </main>

      {/* 4. Slush Minimalist Footer */}
      <footer className="bg-[#ffffff] border-t border-[#000000] py-6 px-6 sm:px-12 text-center text-[12px] font-bold uppercase tracking-[0.032em] text-[#000000]/70 relative z-20">
        <span>Nexus B2B Exchange • Razorpay Buildathon</span>
      </footer>

    </div>
  );
}
