import { ArrowRight } from 'lucide-react';

export function Navbar() {
  return (
    <nav className="fixed top-0 left-0 w-full z-50 px-6 lg:px-12 py-6 flex items-center justify-between bg-bg/50 backdrop-blur-xl border-b border-white/5">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 flex items-center justify-center">
          <img
            src="/sudarshan-icon.png"
            alt="Sudarshan"
            className="w-full h-full object-contain mix-blend-screen"
          />
        </div>
        <span className="text-xl font-bold tracking-[0.2em] text-text-primary uppercase">Sudarshan</span>
      </div>
      
      <div className="hidden lg:flex items-center gap-8 text-sm text-text-muted font-medium">
        <a href="#product" className="hover:text-text-primary transition-colors">Product</a>
        <a href="#capabilities" className="hover:text-text-primary transition-colors">Capabilities</a>
        <a href="#architecture" className="hover:text-text-primary transition-colors">Architecture</a>
        <a href="/about.html" className="hover:text-text-primary transition-colors">About</a>
      </div>
      
      <a href="/login.html" className="group relative inline-flex items-center gap-3 pl-6 pr-2 py-1.5 rounded-full bg-white/5 border border-white/10 hover:border-blue-electric hover:bg-white/10 text-text-primary text-sm font-medium transition-all duration-300">
        Sign in
        <div className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center group-hover:bg-blue-electric transition-colors">
          <ArrowRight className="w-3 h-3" />
        </div>
      </a>
    </nav>
  );
}
