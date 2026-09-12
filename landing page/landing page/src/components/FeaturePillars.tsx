import { Brain, Database, Network, Puzzle } from 'lucide-react';

const PILLARS = [
  {
    title: 'Multimodal Intelligence',
    desc: 'Work across text, documents, images, audio and video.',
    icon: Brain,
  },
  {
    title: 'Memory-Native AI',
    desc: 'User, case and task context retrieved intelligently.',
    icon: Database,
  },
  {
    title: 'Agent Orchestration',
    desc: 'Coordinate specialized agents through structured workflows.',
    icon: Network,
  },
  {
    title: 'Extensible Execution',
    desc: 'Modular pipelines and plugins for limitless capabilities.',
    icon: Puzzle,
  }
];

export function FeaturePillars() {
  return (
    <section id="capabilities" className="scroll-mt-24 px-6 lg:px-12 relative z-30 -mt-8">
      <div className="max-w-[1600px] mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {PILLARS.map((pillar) => (
            <div
              key={pillar.title}
              className="group relative p-[1px] rounded-2xl bg-gradient-to-b from-white/20 to-white/5 backdrop-blur-2xl shadow-[0_8px_32px_rgba(0,0,0,0.4)] hover:-translate-y-1 transition-transform duration-500"
            >
              <div className="h-full px-6 py-6 rounded-[calc(1rem-1px)] bg-[#0A1024]/80 flex flex-col items-start overflow-hidden relative">
                {/* Internal Glow */}
                <div className="absolute inset-0 bg-gradient-to-tr from-blue-electric/0 via-blue-electric/5 to-cyan-highlight/10 opacity-0 group-hover:opacity-100 transition-opacity duration-700"></div>
                
                <div className="flex items-center gap-4 mb-3 relative z-10">
                  <div className="w-10 h-10 rounded-xl bg-bg border border-blue-electric/30 flex items-center justify-center shadow-[inset_0_0_15px_rgba(136,167,255,0.2)]">
                    <pillar.icon className="w-5 h-5 text-blue-300 group-hover:text-cyan-highlight transition-colors duration-500" strokeWidth={1.5} />
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary tracking-wide leading-tight">{pillar.title}</h3>
                </div>
                
                <p className="text-xs text-text-muted leading-relaxed font-light relative z-10">{pillar.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
