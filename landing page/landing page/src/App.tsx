import { useEffect } from 'react';
import Lenis from 'lenis';
import { Navbar } from './components/Navbar';
import { HeroSection } from './components/HeroSection';
import { FeaturePillars } from './components/FeaturePillars';
import { ArchitectureFlow } from './components/ArchitectureFlow';
import { MemoryScopes } from './components/MemoryScopes';
import { UseCases } from './components/UseCases';
import { Footer } from './components/Footer';

function App() {
  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      orientation: 'vertical',
      gestureOrientation: 'vertical',
      smoothWheel: true,
    });

    function raf(time: number) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);

    return () => lenis.destroy();
  }, []);

  return (
    <div className="bg-bg min-h-screen selection:bg-blue-electric/30 selection:text-cyan-highlight relative overflow-hidden text-text-primary">
      {/* Global Cosmic Background */}
      <div className="fixed inset-0 z-[-1] pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[120%] h-[60%] rounded-[100%] border-[2px] border-blue-electric/10 bg-gradient-to-b from-blue-electric/5 to-transparent blur-[2px] transform -rotate-12"></div>
        <div className="absolute bottom-0 left-0 w-full h-[40%] bg-gradient-to-t from-black via-bg to-transparent"></div>
        {/* Subtle Starfield */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(255,255,255,0.15)_1px,_transparent_1px)] bg-[size:40px_40px] opacity-30"></div>
      </div>

      <Navbar />
      <HeroSection />
      
      {/* The rest of the page components */}
      <div className="relative z-20 bg-gradient-to-b from-transparent via-bg to-bg">
        <FeaturePillars />
        <UseCases />
        <MemoryScopes />
        <ArchitectureFlow />
        <Footer />
      </div>
    </div>
  );
}

export default App;
