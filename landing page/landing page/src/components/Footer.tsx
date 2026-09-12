export function Footer() {
  return (
    <footer id="docs" className="scroll-mt-24 py-16 px-6 lg:px-12 bg-bg border-t border-white/5 relative z-10">
      <div className="max-w-screen-2xl mx-auto flex flex-col md:flex-row justify-between items-center gap-8">
        
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 flex items-center justify-center">
            <img
              src="/sudarshan-icon.png"
              alt="Sudarshan"
              className="w-full h-full object-contain mix-blend-screen"
            />
          </div>
          <span className="text-2xl font-bold tracking-tighter text-text-primary">Sudarshan</span>
        </div>
        
        <div className="text-sm text-text-muted font-light tracking-wide">
          &copy; {new Date().getFullYear()} Sudarshan Platform. All rights reserved.
        </div>
        
        <div className="p-1 rounded-full bg-white/5 border border-white/10">
          <a href="/login.html" className="inline-flex px-6 py-2 rounded-full bg-panel hover:bg-white/10 text-sm font-medium text-text-primary transition-colors duration-300">
            Get Started
          </a>
        </div>

      </div>
    </footer>
  );
}
