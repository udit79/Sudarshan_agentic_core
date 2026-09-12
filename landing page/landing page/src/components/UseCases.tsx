import { BarChart3, Clapperboard, FileStack, FlaskConical, Presentation, Search } from 'lucide-react';

const USE_CASES = [
  { title: 'Research', desc: 'Turn scattered sources into clear, evidence-backed briefs.', icon: Search },
  { title: 'Content Generation', desc: 'Move from a source brief to structured, publishable output.', icon: FileStack },
  { title: 'Video', desc: 'Coordinate scripts, assets, scenes and delivery in one workflow.', icon: Clapperboard },
  { title: 'Presentations', desc: 'Transform complex ideas into concise, visual narratives.', icon: Presentation },
  { title: 'Analysis', desc: 'Compare multimodal inputs and surface the decisions that matter.', icon: BarChart3 },
  { title: 'Experiments', desc: 'Prototype new agent workflows without rebuilding the system.', icon: FlaskConical },
];

export function UseCases() {
  return (
    <section id="use-cases" className="scroll-mt-24 px-6 lg:px-12 py-24 lg:py-32 relative z-10">
      <div className="max-w-[1600px] mx-auto">
        <div className="max-w-2xl mb-12">
          <div className="uppercase tracking-[0.3em] text-[10px] font-bold text-text-muted mb-4">Use cases</div>
          <h2 className="text-4xl md:text-5xl lg:text-6xl font-black tracking-tighter text-white uppercase leading-[1.1]">
            One control layer.<br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-300 to-cyan-highlight">Many ways to move.</span>
          </h2>
          <p className="text-sm md:text-base text-text-muted font-light leading-relaxed mt-5 max-w-xl">
            Start with the work in front of you. Sudarshan brings the right context, agents and pipelines together around the outcome.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {USE_CASES.map(({ title, desc, icon: Icon }) => (
            <a
              key={title}
              href="#architecture"
              className="group rounded-2xl border border-white/10 bg-white/[0.03] p-6 transition-all duration-300 hover:-translate-y-1 hover:border-blue-electric/50 hover:bg-white/[0.06]"
            >
              <Icon className="w-5 h-5 text-blue-300 mb-8 transition-colors group-hover:text-cyan-highlight" strokeWidth={1.5} />
              <h3 className="text-lg font-semibold text-text-primary mb-2">{title}</h3>
              <p className="text-sm text-text-muted font-light leading-relaxed">{desc}</p>
              <span className="inline-flex mt-5 text-xs font-semibold tracking-wide text-blue-300 group-hover:text-cyan-highlight">Explore workflow →</span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
