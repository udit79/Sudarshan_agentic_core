import { useRef, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useTexture, ContactShadows, Float, Environment } from '@react-three/drei';
import * as THREE from 'three';

function MascotModel({ reducedMotion }: { reducedMotion: boolean }) {
  const texture = useTexture('/sudarshan-mascot.png');
  const groupRef = useRef<THREE.Group>(null);
  
  useFrame((state, delta) => {
    if (reducedMotion || !groupRef.current) return;
    
    const targetX = (state.pointer.x * Math.PI) / 12; 
    const targetY = (state.pointer.y * Math.PI) / 12;

    groupRef.current.rotation.y = THREE.MathUtils.damp(groupRef.current.rotation.y, targetX, 4, delta);
    groupRef.current.rotation.x = THREE.MathUtils.damp(groupRef.current.rotation.x, -targetY, 4, delta);
  });

  return (
    <group ref={groupRef}>
      <Float 
        speed={reducedMotion ? 0 : 2} 
        rotationIntensity={reducedMotion ? 0 : 0.2} 
        floatIntensity={reducedMotion ? 0 : 1.5}
        floatingRange={[-0.2, 0.2]}
      >
        <mesh position={[0, 0, 0]}>
          <planeGeometry args={[7, 7]} />
          <meshStandardMaterial 
            map={texture} 
            transparent 
            alphaTest={0.01} 
            roughness={0.4} 
            metalness={0.1} 
          />
        </mesh>
        
        <mesh position={[0, 0, -0.5]}>
          <circleGeometry args={[2.8, 64]} />
          <meshBasicMaterial 
            color="#FF9819" 
            transparent 
            opacity={0.08} 
            blending={THREE.AdditiveBlending}
          />
        </mesh>
        <mesh position={[0, 0, -0.6]}>
          <circleGeometry args={[3.2, 64]} />
          <meshBasicMaterial 
            color="#88A7FF" 
            transparent 
            opacity={0.05} 
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      </Float>
    </group>
  );
}

export function Mascot3D() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mediaQuery.matches);
    const handler = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  return (
    <div className="w-full h-full pointer-events-auto">
      <Canvas 
        camera={{ position: [0, 0, 10], fov: 45 }}
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
      >
        <ambientLight intensity={0.6} />
        <spotLight position={[10, 10, 10]} angle={0.15} penumbra={1} intensity={1.5} color="#88A7FF" />
        <spotLight position={[-10, -10, 10]} angle={0.15} penumbra={1} intensity={1} color="#FF9819" />
        
        <MascotModel reducedMotion={prefersReducedMotion} />
        
        {!prefersReducedMotion && (
          <ContactShadows position={[0, -3.5, 0]} opacity={0.5} scale={12} blur={2.5} far={4} color="#000000" />
        )}
        <Environment preset="city" environmentIntensity={0.2} />
      </Canvas>
    </div>
  );
}
