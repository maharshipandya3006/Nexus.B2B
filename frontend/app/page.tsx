'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';

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
    const nodeCount = subtle ? 18 : 30;
    const cols = 6;
    const rows = 5;

    // Node labels requested by user
    const labelsMap: Record<number, string> = {
      2: 'PARALLEL DISCOVERY',
      7: 'AI NEGOTIATION',
      11: 'RAZORPAY //01',
      16: 'MARGIN PROTECTION',
      24: 'HMAC //VALID',
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

      // Vertical lines
      for (let x = 0; x <= width; x += gridSpacing) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      // Horizontal lines
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

        // Smooth turnaround within boundaries
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

      // 3. Connect nodes across the entire canvas (whitespace, left, right, behind text)
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

      // 5. Draw precision radar nodes and ambient halos across entire canvas
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

        // Monospace telemetry tag: strictly RAZORPAY //01, DISCOVERY, HMAC //VALID
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

export default function LandingPage() {
  const [activeSegment, setActiveSegment] = useState<'merchant' | 'buyer'>('merchant');
  const [stagesVisible, setStagesVisible] = useState(false);
  const stagesRef = useRef<HTMLElement>(null);

  useEffect(() => {
    // If IntersectionObserver is unavailable, fallback immediately
    if (typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      setStagesVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setStagesVisible(true);
        }
      },
      { threshold: 0.05, rootMargin: '50px 0px 50px 0px' }
    );

    const currentEl = stagesRef.current;
    if (currentEl) {
      observer.observe(currentEl);
    }

    // Safety fallback: ensure cards animate in as soon as user scrolls near the section
    const handleScroll = () => {
      if (stagesRef.current) {
        const rect = stagesRef.current.getBoundingClientRect();
        if (rect.top < window.innerHeight * 0.95) {
          setStagesVisible(true);
        }
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    // Check initial position on mount
    handleScroll();

    return () => {
      if (currentEl) observer.unobserve(currentEl);
      window.removeEventListener('scroll', handleScroll);
    };
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[#ffffff] text-[#000000] antialiased selection:bg-[#0D94FB] selection:text-[#ffffff]">
      
      {/* 1. Full-Bleed Top Marquee Banner: 100% Seamless Infinite Loop with Zero Glitches */}
      <div 
        className="w-full bg-[#000000] text-[#ffffff] border-b border-[#000000] py-2.5 overflow-hidden select-none"
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

      <main className="flex-1">
        
        {/* SECTION 1: HERO */}
        <section className="relative bg-[#dceeff] text-[#000000] min-h-[calc(100vh-37px)] flex flex-col justify-center items-center py-10 px-6 sm:px-12 border-b border-[#000000] overflow-hidden">
          
          {/* Continuous Live Liquidity Mesh: Spans entire canvas (whitespaces, left/right margins, and behind text) */}
          <ContinuousLiquidityMesh />

          <div className="max-w-[1280px] w-full mx-auto text-center relative z-10 my-auto">
            
            {/* Centered Persona Toggle Pill */}
            <div 
              role="tablist"
              aria-label="Target persona"
              className="inline-flex p-1 rounded-full border border-[#000000] bg-[#ffffff] mb-6 sm:mb-8 shadow-xs"
            >
              <button
                role="tab"
                id="tab-persona-merchant"
                aria-selected={activeSegment === 'merchant'}
                onClick={() => setActiveSegment('merchant')}
                className={`px-5 py-2 rounded-full text-xs font-bold uppercase tracking-wider transition-all min-h-[38px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] active:scale-[0.98] ${
                  activeSegment === 'merchant'
                    ? 'bg-[#000000] text-[#ffffff]'
                    : 'text-[#000000] hover:bg-[#e9e9e9]'
                }`}
              >
                Wholesale Merchant
              </button>
              <button
                role="tab"
                id="tab-persona-buyer"
                aria-selected={activeSegment === 'buyer'}
                onClick={() => setActiveSegment('buyer')}
                className={`px-5 py-2 rounded-full text-xs font-bold uppercase tracking-wider transition-all min-h-[38px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] active:scale-[0.98] ${
                  activeSegment === 'buyer'
                    ? 'bg-[#000000] text-[#ffffff]'
                    : 'text-[#000000] hover:bg-[#e9e9e9]'
                }`}
              >
                Procurement Buyer
              </button>
            </div>

            {/* Display Headline: Increased size with NEXUS B2B on line 1 and EXCHANGE on line 2 */}
            <h1 className="text-5xl sm:text-6xl md:text-7xl lg:text-[88px] xl:text-[96px] font-extrabold tracking-[-0.03em] leading-[0.92] mb-6 sm:mb-8 max-w-5xl mx-auto uppercase">
              <span className="block">NEXUS B2B</span>
              <span className="block">EXCHANGE</span>
            </h1>


            {/* Tagline Subhead: Balanced and elegant */}
            <p className="text-base sm:text-lg md:text-xl tracking-normal font-normal leading-relaxed max-w-2xl md:max-w-3xl mx-auto mb-8 sm:mb-10 text-[#000000]/80">
              {activeSegment === 'merchant'
                ? 'Empower your wholesale business with AI agents that protect margins, automate bulk pricing, and reserve stock for 15 minutes.'
                : 'AI buyer agents that find wholesale inventory, negotiate better bulk prices, and finalize deals with human approval.'}
            </p>

            {/* Compulsory Authentication CTAs: Balanced proportions */}
            <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 justify-center items-center">
              <Link
                href="/auth"
                className="w-full sm:w-auto px-6 py-3 min-h-[46px] rounded-full border border-[#000000] bg-[#000000] text-[#ffffff] font-bold text-xs sm:text-sm uppercase tracking-wider hover:bg-[#000000]/85 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] transition-all inline-flex items-center justify-center gap-2"
              >
                <span>SIGN IN TO NEXUS TERMINAL</span>
                <span>→</span>
              </Link>

              <Link
                href="/auth?mode=register"
                className="w-full sm:w-auto px-6 py-3 min-h-[46px] rounded-full border border-[#000000] bg-[#ffffff] text-[#000000] font-bold text-xs sm:text-sm uppercase tracking-wider hover:bg-[#e9e9e9] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#000000] transition-all inline-flex items-center justify-center gap-2"
              >
                <span>Create Identity / Register</span>
                <span>→</span>
              </Link>
            </div>

          </div>

        </section>

        {/* SECTION 2: 5-STAGE ARCHITECTURE */}
        <section 
          id="protocol" 
          ref={stagesRef}
          className="bg-[#ffffff] text-[#000000] min-h-screen flex flex-col justify-center items-center py-12 sm:py-16 px-6 sm:px-12 border-b border-[#000000] scroll-mt-0 relative overflow-hidden"
        >
          {/* Subtle Continuous Liquidity Mesh in Background of Protocol Section */}
          <ContinuousLiquidityMesh subtle={true} />

          <div className="max-w-[1440px] w-full mx-auto my-auto flex flex-col justify-center relative z-10">
            
            {/* Header */}
            <div 
              className={`text-center max-w-3xl mx-auto mb-10 sm:mb-12 transition-all duration-700 ease-out ${
                stagesVisible 
                  ? 'opacity-100 translate-y-0' 
                  : 'opacity-0 translate-y-8'
              }`}
            >
              <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight leading-tight uppercase mb-3">
                Five Algorithmic Stages
              </h2>
              <p className="text-sm sm:text-base font-normal text-[#000000]/70 max-w-2xl mx-auto leading-relaxed">
                Engineered to eradicate procurement friction with autonomous yield and cryptographic guarantees.
              </p>
            </div>

            {/* 5 Cards all using matching #0D94FB color palette with staggered sliding animation */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 xl:gap-5 items-stretch">
              
              {/* Stage 1: Cobalt (#0D94FB) — Slides in from bottom-left */}
              <div 
                className={`p-5 sm:p-6 xl:p-7 rounded-2xl border border-[#000000] bg-[#ffffff] flex flex-col justify-between hover:bg-[#0D94FB]/5 hover:-translate-y-1 transition-all duration-700 delay-100 ease-out min-h-[290px] sm:min-h-[320px] ${
                  stagesVisible 
                    ? 'opacity-100 translate-y-0 translate-x-0' 
                    : 'opacity-0 translate-y-12 -translate-x-4'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="text-[11px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border border-[#000000] bg-[#0D94FB] text-[#ffffff]">
                      Stage 01
                    </span>
                  </div>
                  <h3 className="text-lg sm:text-xl font-bold tracking-tight uppercase mb-2 leading-snug">
                    Parallel Discovery
                  </h3>
                  <p className="text-xs sm:text-[13px] font-normal text-[#000000]/75 leading-relaxed">
                    Buyer agents search multiple registered merchants at once to find available stock and the best bulk prices in milliseconds.
                  </p>
                </div>
                <div className="mt-6 pt-3 border-t border-[#000000]/15 text-[11px] font-bold uppercase tracking-wider text-[#000000]">
                  <span>Multi-Merchant Routing</span>
                </div>
              </div>

              {/* Stage 2: Cobalt (#0D94FB) — Slides in from bottom */}
              <div 
                className={`p-5 sm:p-6 xl:p-7 rounded-2xl border border-[#000000] bg-[#ffffff] flex flex-col justify-between hover:bg-[#0D94FB]/5 hover:-translate-y-1 transition-all duration-700 delay-200 ease-out min-h-[290px] sm:min-h-[320px] ${
                  stagesVisible 
                    ? 'opacity-100 translate-y-0' 
                    : 'opacity-0 translate-y-12'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="text-[11px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border border-[#000000] bg-[#0D94FB] text-[#ffffff]">
                      Stage 02
                    </span>
                  </div>
                  <h3 className="text-lg sm:text-xl font-bold tracking-tight uppercase mb-2 leading-snug">
                    AI Negotiation
                  </h3>
                  <p className="text-xs sm:text-[13px] font-normal text-[#000000]/75 leading-relaxed">
                    Buyer and merchant agents negotiate directly, adjusting offers based on volume, pricing, and each side’s limits.
                  </p>
                </div>
                <div className="mt-6 pt-3 border-t border-[#000000]/15 text-[11px] font-bold uppercase tracking-wider text-[#000000]">
                  <span>Bilateral Agent Swarm</span>
                </div>
              </div>

              {/* Stage 3: Cobalt (#0D94FB) — Slides in from bottom */}
              <div 
                className={`p-5 sm:p-6 xl:p-7 rounded-2xl border border-[#000000] bg-[#ffffff] flex flex-col justify-between hover:bg-[#0D94FB]/5 hover:-translate-y-1 transition-all duration-700 delay-300 ease-out min-h-[290px] sm:min-h-[320px] ${
                  stagesVisible 
                    ? 'opacity-100 translate-y-0' 
                    : 'opacity-0 translate-y-12'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="text-[11px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border border-[#000000] bg-[#0D94FB] text-[#ffffff]">
                      Stage 03
                    </span>
                  </div>
                  <h3 className="text-lg sm:text-xl font-bold tracking-tight uppercase mb-2 leading-snug">
                    Margin Protection
                  </h3>
                  <p className="text-xs sm:text-[13px] font-normal text-[#000000]/75 leading-relaxed">
                    Merchant agents negotiate in the seller’s best interest while keeping confidential minimum prices private.
                  </p>
                </div>
                <div className="mt-6 pt-3 border-t border-[#000000]/15 text-[11px] font-bold uppercase tracking-wider text-[#000000]">
                  <span>Zero Floor Leakage</span>
                </div>
              </div>

              {/* Stage 4: Cobalt (#0D94FB) — Slides in from bottom */}
              <div 
                className={`p-5 sm:p-6 xl:p-7 rounded-2xl border border-[#000000] bg-[#ffffff] flex flex-col justify-between hover:bg-[#0D94FB]/5 hover:-translate-y-1 transition-all duration-700 delay-400 ease-out min-h-[290px] sm:min-h-[320px] ${
                  stagesVisible 
                    ? 'opacity-100 translate-y-0' 
                    : 'opacity-0 translate-y-12'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="text-[11px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border border-[#000000] bg-[#0D94FB] text-[#ffffff]">
                      Stage 04
                    </span>
                  </div>
                  <h3 className="text-lg sm:text-xl font-bold tracking-tight uppercase mb-2 leading-snug">
                    Mutual Approval
                  </h3>
                  <p className="text-xs sm:text-[13px] font-normal text-[#000000]/75 leading-relaxed">
                    AI cannot finalize a deal on its own. Both the buyer and merchant must approve the final price or submit a counter offer.
                  </p>
                </div>
                <div className="mt-6 pt-3 border-t border-[#000000]/15 text-[11px] font-bold uppercase tracking-wider text-[#000000]">
                  <span>9-State Consensus Matrix</span>
                </div>
              </div>

              {/* Stage 5: Cobalt (#0D94FB) matching Stage 01 & 03 — Slides in from bottom-right */}
              <div 
                className={`p-5 sm:p-6 xl:p-7 rounded-2xl border border-[#000000] bg-[#ffffff] flex flex-col justify-between hover:bg-[#0D94FB]/5 hover:-translate-y-1 transition-all duration-700 delay-500 ease-out min-h-[290px] sm:min-h-[320px] md:col-span-2 md:max-w-md md:mx-auto lg:col-span-1 lg:max-w-none lg:mx-0 w-full ${
                  stagesVisible 
                    ? 'opacity-100 translate-y-0 translate-x-0' 
                    : 'opacity-0 translate-y-12 translate-x-4'
                }`}
              >
                <div>
                  <div className="flex justify-between items-start mb-4">
                    <span className="text-[11px] font-mono font-bold uppercase px-2.5 py-0.5 rounded-full border border-[#000000] bg-[#0D94FB] text-[#ffffff]">
                      Stage 05
                    </span>
                  </div>
                  <h3 className="text-lg sm:text-xl font-bold tracking-tight uppercase mb-2 leading-snug">
                    Razorpay Mandate
                  </h3>
                  <p className="text-xs sm:text-[13px] font-normal text-[#000000]/75 leading-relaxed">
                    Once both sides agree, the deal is securely locked and stock is reserved for 15 minutes while Razorpay processes the payment.
                  </p>
                </div>
                <div className="mt-6 pt-3 border-t border-[#000000]/15 text-[11px] font-bold uppercase tracking-wider text-[#000000]">
                  <span>HMAC SHA-256 Signatures</span>
                </div>
              </div>

            </div>
          </div>
        </section>


      </main>

      {/* Footer */}
      <footer className="bg-[#ffffff] border-t border-[#000000] py-10 px-6 sm:px-12">
        <div className="max-w-[1440px] mx-auto flex flex-col sm:flex-row justify-between items-center gap-6 text-[13px] font-bold uppercase tracking-[0.032em]">
          <div className="flex items-center gap-3">
            <span className="font-extrabold text-[#000000]">Nexus B2B Exchange</span>
            <span>•</span>
            <span className="text-[#000000]/60">Razorpay Buildathon Track 1</span>
          </div>
          <div className="flex gap-4">
            <Link 
              href="/auth" 
              className="px-4 py-2 rounded-[1600px] border border-[#000000] bg-[#ffffff] hover:bg-[#e9e9e9] transition-colors"
            >
              Sign In
            </Link>
            <Link 
              href="/auth?mode=register" 
              className="px-4 py-2 rounded-[1600px] border border-[#000000] bg-[#ffffff] hover:bg-[#e9e9e9] transition-colors"
            >
              Register
            </Link>
          </div>
        </div>
      </footer>

    </div>
  );
}
