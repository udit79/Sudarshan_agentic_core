import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { FileText, Cpu, Workflow, CheckCircle, Database } from 'lucide-react';

gsap.registerPlugin(ScrollTrigger);

const STAGES = [
  { id: 'inputs', title: 'Inputs', items: ['Documents', 'Images', 'Audio', 'Video', 'URLs'], icon: FileText },
  { id: 'intelligence', title: 'Intelligence Layer', items: ['Request Understanding', 'Context Retrieval', 'Planning', 'Pipeline Routing', 'Context Assembly', 'Agent Collaboration', 'Parallel Execution'], icon: Cpu },
  { id: 'pipelines', title: 'Pipelines', items: ['Research', 'Content Generation', 'Video', 'Presentations', 'Infographics', 'Analysis', 'Plugins'], icon: Workflow },
  { id: 'outputs', title: 'Outputs', items: ['Actionable Results', 'Generated Assets'], icon: CheckCircle },
  { id: 'knowledge', title: 'Persistent Knowledge', items: ['Feedback Loop', 'Updated Memory'], icon: Database }
];

export function ArchitectureFlow() {
  const containerRef = useRef<HTMLDivElement>(null);
  const stagesRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const ctx = gsap.context(() => {
      // Instead of pinning, we just trigger highlights as they scroll into view
      stagesRef.current.forEach((stage) => {
        if (!stage) return;
        
        ScrollTrigger.create({
          trigger: stage,
          start: 'top center+=100',
          end: 'bottom center-=100',
          toggleClass: { targets: stage, className: 'is-active' }
        });
      });
    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <section id="architecture" className="scroll-mt-24 py-24 lg:py-40 px-6 lg:px-12 bg-bg relative z-10" ref={containerRef}>
      <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-white/10 to-transparent"></div>
      
      <div className="max-w-screen-xl mx-auto flex flex-col lg:flex-row gap-16 lg:gap-24 items-start">
        
        {/* Left: Sticky Header */}
        <div className="lg:sticky lg:top-[25vh] flex-shrink-0 lg:w-[400px]">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 mb-6 rounded-full bg-white/5 border border-white/5 backdrop-blur-md">
            <span className="text-[10px] uppercase font-bold text-text-muted tracking-[0.2em]">Data Pipeline</span>
          </div>
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight text-text-primary mb-6">Architecture Flow</h2>
          <p className="text-lg text-text-muted font-light leading-relaxed">
            How Sudarshan transforms raw, multimodal information into actionable impact through a coordinated network of specialized agents.
          </p>
        </div>

        {/* Right: The Pipeline Diagram */}
        <div className="flex-1 w-full relative">
          {/* Vertical Timeline Line */}
          <div className="absolute top-8 bottom-8 left-[31px] w-[2px] bg-white/5 z-0"></div>

          <div className="flex flex-col gap-12 relative z-10">
            {STAGES.map((stage, i) => (
              <div 
                key={stage.id}
                ref={el => { stagesRef.current[i] = el; }}
                className="arch-stage relative group flex gap-8 transition-all duration-700 opacity-60 [&.is-active]:opacity-100 [&.is-active]:scale-[1.02]"
              >
                {/* Node indicator */}
                <div className="relative mt-2 flex-shrink-0 z-10">
                  <div className="w-16 h-16 rounded-full bg-bg border border-white/10 flex items-center justify-center transition-all duration-500 group-[.is-active]:border-cyan-highlight group-[.is-active]:bg-cyan-highlight/10 group-[.is-active]:shadow-[0_0_30px_rgba(125,232,255,0.3)]">
                    <stage.icon className="w-6 h-6 text-text-muted group-[.is-active]:text-cyan-highlight transition-colors duration-500" strokeWidth={1.5} />
                  </div>
                </div>

                {/* Content Card */}
                <div className="flex-1 p-8 rounded-[2rem] bg-white/5 border border-white/10 transition-colors duration-500 group-[.is-active]:border-white/20 group-[.is-active]:bg-panel group-[.is-active]:shadow-[0_20px_40px_-15px_rgba(0,0,0,0.5)]">
                  <h3 className="text-2xl font-semibold text-text-primary mb-6 tracking-tight">{stage.title}</h3>
                  <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
                    {stage.items.map(item => (
                      <li key={item} className="text-sm md:text-base text-text-muted font-light flex items-center gap-3">
                        <span className="w-1.5 h-1.5 rounded-full bg-white/20 group-[.is-active]:bg-blue-electric transition-colors duration-500"></span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
        </div>
        
      </div>
    </section>
  );
}

