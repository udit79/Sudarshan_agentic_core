import { useEffect, useRef } from 'react';
import { User, Briefcase, Zap } from 'lucide-react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function MemoryScopes() {
  const containerRef = useRef<HTMLDivElement>(null);
  const ring1Ref = useRef<HTMLDivElement>(null);
  const ring2Ref = useRef<HTMLDivElement>(null);
  const ring3Ref = useRef<HTMLDivElement>(null);
  const coreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const ctx = gsap.context(() => {
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top 60%',
          end: '+=400',
          scrub: 1,
        }
      });

      gsap.set([ring1Ref.current, ring2Ref.current, ring3Ref.current], {
        z: 0,
        opacity: 0,
        scale: 0.8
      });
      gsap.set(coreRef.current, { opacity: 0, scaleY: 0 });

      tl.to(ring3Ref.current, { z: 0, opacity: 1, scale: 1, duration: 1 }, 0)
        .to(ring2Ref.current, { z: 80, opacity: 1, scale: 1, duration: 1 }, 0.2)
        .to(ring1Ref.current, { z: 160, opacity: 1, scale: 1, duration: 1 }, 0.4)
        .to(coreRef.current, { opacity: 1, scaleY: 1, duration: 1 }, 0.4);

    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <section className="py-24 lg:py-32 px-6 lg:px-12 relative z-10 overflow-hidden" ref={containerRef}>
      <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-blue-electric/20 to-transparent"></div>
      <div className="absolute inset-0 z-[-1] bg-[radial-gradient(ellipse_at_bottom,_var(--color-bg)_0%,_transparent_100%)] opacity-80"></div>
      
      <div className="max-w-[1600px] mx-auto flex flex-col lg:flex-row items-center gap-16 lg:gap-8">
        
        {/* Left Side */}
        <div className="flex-1 max-w-xl flex flex-col items-start gap-4 z-20">
          <div className="uppercase tracking-[0.3em] text-[10px] font-bold text-text-muted">Memory</div>
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-black tracking-tighter text-white uppercase leading-[1.1]">
            Intelligence <br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-accent-orange to-orange-200">That Remembers.</span>
          </h2>
          <p className="text-sm md:text-base text-text-muted font-light leading-relaxed mt-2 max-w-md">
            Sudarshan separates memory into user, case and task contexts — so the right knowledge is always at hand, without the noise.
          </p>
        </div>

        {/* Center: 3D Stack */}
        <div className="flex-[1.5] w-full flex justify-center items-center relative py-32 z-10" style={{ perspective: '1200px' }}>
          
          {/* Main 3D Container */}
          <div 
            className="relative w-[320px] h-[320px]" 
            style={{ 
              transformStyle: 'preserve-3d', 
              transform: 'rotateX(65deg) rotateZ(-20deg)' 
            }}
          >
            
            {/* USER Layer Parent */}
            <div ref={ring1Ref} className="absolute inset-0" style={{ transformStyle: 'preserve-3d' }}>
              <div className="absolute inset-0 rounded-full border-[3px] border-blue-400/50 bg-blue-500/10 shadow-[0_0_50px_rgba(59,130,246,0.3)] backdrop-blur-md"></div>
              <div className="absolute inset-2 rounded-full border border-blue-300/30"></div>
              {/* Text sibling - Translated Z +40px so it floats ABOVE the glass ring and avoids z-clipping */}
              <div className="absolute left-1/2 top-1/2 flex items-center gap-2" style={{ transform: 'translate(-50%, -50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                <User className="w-5 h-5 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                <span className="text-sm font-bold tracking-widest text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]">USER</span>
              </div>
              <div className="absolute -right-24 top-1/2 text-[10px] text-blue-100/90 tracking-wider hidden md:block drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" style={{ transform: 'translateY(-50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                Preferences<br/>Conventions<br/>Long-term context
              </div>
            </div>

            {/* CASE Layer Parent */}
            <div ref={ring2Ref} className="absolute inset-0" style={{ transformStyle: 'preserve-3d' }}>
              <div className="absolute inset-0 rounded-full border-[3px] border-cyan-400/50 bg-cyan-500/10 shadow-[0_0_50px_rgba(34,211,238,0.2)] backdrop-blur-md"></div>
              <div className="absolute inset-2 rounded-full border border-cyan-300/30"></div>
              <div className="absolute left-1/2 top-1/2 flex items-center gap-2" style={{ transform: 'translate(-50%, -50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                <Briefcase className="w-5 h-5 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                <span className="text-sm font-bold tracking-widest text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]">CASE</span>
              </div>
              <div className="absolute -right-24 top-1/2 text-[10px] text-cyan-100/90 tracking-wider hidden md:block drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" style={{ transform: 'translateY(-50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                Facts<br/>Sources<br/>Decisions
              </div>
            </div>

            {/* TASK Layer Parent */}
            <div ref={ring3Ref} className="absolute inset-0" style={{ transformStyle: 'preserve-3d' }}>
              <div className="absolute inset-0 rounded-full border-[3px] border-orange-400/50 bg-orange-500/10 shadow-[0_0_50px_rgba(249,115,22,0.2)] backdrop-blur-md"></div>
              <div className="absolute inset-2 rounded-full border border-orange-300/30"></div>
              <div className="absolute left-1/2 top-1/2 flex items-center gap-2" style={{ transform: 'translate(-50%, -50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                <Zap className="w-5 h-5 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                <span className="text-sm font-bold tracking-widest text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]">TASK</span>
              </div>
              <div className="absolute -right-24 top-1/2 text-[10px] text-orange-100/90 tracking-wider hidden md:block drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" style={{ transform: 'translateY(-50%) translateZ(40px) rotateZ(20deg) rotateX(-65deg)' }}>
                Steps<br/>Tool calls<br/>Execution state
              </div>
            </div>
            
            {/* Center Core Beam */}
            <div 
              ref={coreRef}
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-12 h-[260px] bg-gradient-to-t from-orange-500/0 via-blue-400/30 to-blue-400/0 blur-xl pointer-events-none"
              style={{ transform: 'rotateX(-90deg)', transformOrigin: 'bottom' }}
            ></div>
          </div>

        </div>

        {/* Right Side: Quote Block */}
        <div className="flex-1 max-w-sm z-20 hidden lg:block">
          <div className="p-8 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-xl relative">
            <div className="absolute -left-2 top-8 w-1 h-12 bg-blue-electric"></div>
            <p className="text-sm font-light text-text-primary leading-relaxed italic mb-4">
              "Memory turns isolated outputs into compounding intelligence."
            </p>
            <div className="text-[10px] tracking-widest text-text-muted font-semibold uppercase">
              Sudarshan
            </div>
          </div>
        </div>

      </div>
    </section>
  );
}
