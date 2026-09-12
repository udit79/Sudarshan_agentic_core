import { ArrowUpRight, Play, FileText, Image, Mic, Video, Sparkles, Database, Network, Workflow, Target } from 'lucide-react';
import { TypewriterCycle } from './TypewriterCycle';
import { Mascot3D } from './Mascot3D';

export function HeroSection() {
  return (
    <section id="product" className="scroll-mt-24 relative w-full min-h-[100dvh] flex items-center pt-32 lg:pt-40 pb-32 px-6 lg:px-12">
      
      {/* Background Glowing Logo */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-[60%] w-[600px] h-[600px] pointer-events-none flex flex-col items-center justify-center opacity-30 mix-blend-screen">
        <div className="relative w-full h-full flex items-center justify-center">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--color-blue-electric)_0%,_transparent_70%)] blur-2xl opacity-20"></div>
          <span className="text-[400px] font-black italic text-transparent bg-clip-text bg-gradient-to-tr from-accent-orange via-blue-electric to-cyan-highlight leading-none blur-[2px]">S</span>
          <span className="absolute text-[400px] font-black italic text-transparent bg-clip-text bg-gradient-to-tr from-accent-orange via-blue-electric to-cyan-highlight leading-none">S</span>
        </div>
      </div>

      <div className="relative z-10 w-full max-w-[1600px] mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-8 items-center">
        
        {/* Left Column: Text content */}
        <div className="flex flex-col items-start gap-8 z-20">
          <div className="uppercase tracking-[0.2em] text-xs font-bold text-text-muted flex items-center gap-3">
            <span className="w-8 h-[1px] bg-blue-electric"></span>
            Agentic AI Execution Platform
          </div>

          <h1 className="text-6xl md:text-7xl lg:text-[5.5rem] font-bold tracking-tighter leading-[1.05] uppercase">
            <span className="text-transparent bg-clip-text bg-gradient-to-b from-white to-blue-200">From</span><br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-b from-blue-300 to-blue-electric">Information</span><br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-accent-orange to-orange-300">To Impact.</span>
          </h1>

          <p className="text-lg text-text-muted max-w-lg font-light leading-relaxed">
            Sudarshan turns complex multimodal information into coordinated intelligent execution — with memory, context and agent orchestration built into the system.
          </p>

          <div className="text-xl font-medium text-blue-300 h-[1.5em] flex items-center">
            <TypewriterCycle />
          </div>

          <div className="flex flex-col sm:flex-row gap-4 mt-4 w-full sm:w-auto">
            <a href="#capabilities" className="group relative inline-flex items-center gap-4 pl-8 pr-2 py-2 rounded-full bg-blue-bright hover:bg-blue-electric text-white font-semibold shadow-[0_0_40px_rgba(96,121,232,0.4)] transition-all duration-500 active:scale-[0.98]">
              <span className="tracking-wide text-sm">Explore Sudarshan</span>
              <div className="w-8 h-8 rounded-full bg-white/20 backdrop-blur-md flex items-center justify-center transition-transform group-hover:translate-x-1 group-hover:bg-white/30">
                <ArrowUpRight className="w-4 h-4 text-white" strokeWidth={2.5} />
              </div>
            </a>
            <a href="#architecture" className="group relative inline-flex items-center gap-4 px-8 py-3 rounded-full bg-transparent border border-white/20 hover:border-white/40 text-text-primary text-sm font-semibold transition-all duration-500 active:scale-[0.98]">
              View Architecture
            </a>
          </div>
        </div>

        {/* Right Column: 3D Mascot & Floating Nodes */}
        <div className="relative w-full h-[600px] lg:h-[800px] flex items-center justify-center">
          
          {/* Floating Data Input Nodes (Left Side of Mascot) */}
          <div className="absolute left-0 lg:-left-12 top-1/2 -translate-y-1/2 flex flex-col gap-4 z-20">
            {[
              { label: 'Documents', icon: FileText },
              { label: 'Images', icon: Image },
              { label: 'Audio', icon: Mic },
              { label: 'Video', icon: Video },
            ].map((node, i) => (
              <div key={node.label} className="flex items-center gap-3 animate-[float_4s_ease-in-out_infinite]" style={{ animationDelay: `${i * 0.5}s` }}>
                <div className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 backdrop-blur-md shadow-[0_8px_32px_rgba(0,0,0,0.5)] flex items-center gap-3 transition-transform hover:scale-105 hover:border-blue-electric/50 cursor-default">
                  <node.icon className="w-4 h-4 text-blue-300" strokeWidth={2} />
                  <span className="text-xs font-semibold tracking-wide text-text-primary">{node.label}</span>
                </div>
                <div className="w-8 h-[1px] bg-gradient-to-r from-blue-electric/50 to-transparent"></div>
              </div>
            ))}
          </div>

          {/* The R3F Mascot Canvas */}
          <div className="absolute inset-0 z-10 w-full h-full">
            <Mascot3D />
          </div>

          {/* Floating Pipeline Nodes (Right Side of Mascot) */}
          <div className="absolute right-0 lg:-right-8 top-1/2 -translate-y-1/2 flex flex-col gap-6 z-20">
            <div className="absolute left-[9px] top-4 bottom-4 w-[1px] bg-gradient-to-b from-cyan-highlight/50 via-blue-electric/20 to-accent-orange/50"></div>
            {[
              { label: 'Understand', icon: Sparkles, color: 'text-cyan-highlight' },
              { label: 'Remember', icon: Database, color: 'text-blue-300' },
              { label: 'Plan', icon: Network, color: 'text-blue-electric' },
              { label: 'Orchestrate', icon: Workflow, color: 'text-purple-400' },
              { label: 'Execute', icon: Play, color: 'text-accent-orange' },
              { label: 'Impact', icon: Target, color: 'text-orange-500' },
            ].map((node, i) => (
              <div key={node.label} className="relative flex items-center gap-4 animate-[float_4s_ease-in-out_infinite_reverse]" style={{ animationDelay: `${i * 0.3}s` }}>
                <div className="relative w-5 h-5 flex items-center justify-center bg-bg rounded-full border border-white/20 z-10">
                  <node.icon className={`w-3 h-3 ${node.color}`} strokeWidth={2} />
                </div>
                <span className="text-xs font-medium text-text-muted">{node.label}</span>
              </div>
            ))}
          </div>

        </div>

      </div>

      {/* Centered Logo Bar underneath hero */}
      <div className="absolute bottom-12 left-1/2 -translate-x-1/2 flex flex-col items-center gap-4 z-30">
        <div className="flex items-center gap-4 text-3xl md:text-4xl font-bold tracking-[0.2em] uppercase text-text-primary">
          Sudarshan <span className="text-blue-electric font-light">|</span>
        </div>
        <div className="text-[10px] md:text-xs tracking-[0.3em] font-semibold text-text-muted uppercase">
          Intelligence in Motion
        </div>
        <div className="flex gap-4 md:gap-8 mt-2 text-[9px] tracking-widest text-white/30 uppercase">
          <span>Understand</span>|<span>Remember</span>|<span>Orchestrate</span>|<span>Execute</span>|<span>Impact</span>
        </div>
      </div>
    </section>
  );
}


