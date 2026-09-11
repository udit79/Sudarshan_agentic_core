(() => {
  const host = document.getElementById('hero-3d-scene');
  const canvas = document.getElementById('hero-3d-canvas');
  const THREE = window.THREE;
  if (!host || !canvas || !THREE) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isLowCapability = /Android|iPhone|iPad/i.test(navigator.userAgent)
    || (navigator.hardwareConcurrency || 4) <= 4;
  const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!gl) {
    host.classList.add('hero-3d-fallback');
    return;
  }

  const renderer = new THREE.WebGLRenderer({
    canvas,
    context: gl,
    alpha: true,
    antialias: !isLowCapability,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isLowCapability ? 1 : 1.75));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 0, 6.2);

  const core = new THREE.Group();
  const orbitalSystem = new THREE.Group();
  scene.add(core, orbitalSystem);

  const coreMaterial = new THREE.MeshBasicMaterial({
    color: 0x7de8ff,
    transparent: true,
    opacity: 0.18,
    wireframe: true,
  });
  const coreMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.72, 1), coreMaterial);
  core.add(coreMesh);

  const innerMaterial = new THREE.MeshBasicMaterial({
    color: 0x7894ff,
    transparent: true,
    opacity: 0.12,
    wireframe: true,
  });
  const innerMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.49, 1), innerMaterial);
  innerMesh.rotation.set(0.4, 0.2, 0.7);
  core.add(innerMesh);

  const ringMaterials = [
    new THREE.MeshBasicMaterial({ color: 0x88a7ff, transparent: true, opacity: 0.52 }),
    new THREE.MeshBasicMaterial({ color: 0xff9819, transparent: true, opacity: 0.34 }),
    new THREE.MeshBasicMaterial({ color: 0x7de8ff, transparent: true, opacity: 0.3 }),
  ];
  const ringSpecs = [
    { radius: 1.35, tube: 0.012, rotation: [0.62, 0.12, 0.16], material: ringMaterials[0] },
    { radius: 1.55, tube: 0.009, rotation: [-0.18, 0.72, 0.28], material: ringMaterials[1] },
    { radius: 1.82, tube: 0.007, rotation: [1.06, -0.28, 0.52], material: ringMaterials[2] },
  ];
  ringSpecs.forEach((spec) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(spec.radius, spec.tube, 8, 128), spec.material);
    ring.rotation.set(...spec.rotation);
    orbitalSystem.add(ring);
  });

  const particleCount = isLowCapability ? 90 : 220;
  const particlePositions = new Float32Array(particleCount * 3);
  for (let index = 0; index < particleCount; index += 1) {
    const radius = 2.2 + Math.random() * 1.6;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos((Math.random() * 2) - 1);
    particlePositions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
    particlePositions[(index * 3) + 1] = radius * Math.sin(phi) * Math.sin(theta);
    particlePositions[(index * 3) + 2] = radius * Math.cos(phi) - 0.8;
  }
  const particleGeometry = new THREE.BufferGeometry();
  particleGeometry.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
  const particleMaterial = new THREE.PointsMaterial({
    color: 0x88a7ff,
    size: isLowCapability ? 0.025 : 0.035,
    transparent: true,
    opacity: 0.52,
    depthWrite: false,
  });
  const particles = new THREE.Points(particleGeometry, particleMaterial);
  scene.add(particles);

  const pointer = { x: 0, y: 0 };
  const target = { x: 0, y: 0 };
  let animationFrame = null;
  let resizeObserver = null;

  const resize = () => {
    const rect = host.getBoundingClientRect();
    const width = Math.max(rect.width, 1);
    const height = Math.max(rect.height, 1);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  };
  const onPointerMove = (event) => {
    target.x = ((event.clientX / window.innerWidth) - 0.5) * 2;
    target.y = ((event.clientY / window.innerHeight) - 0.5) * 2;
  };
  const render = (time = 0) => {
    animationFrame = null;
    const elapsed = time * 0.001;
    pointer.x += (target.x - pointer.x) * 0.045;
    pointer.y += (target.y - pointer.y) * 0.045;
    const motion = reducedMotion ? 0 : 1;
    core.position.x = pointer.x * 0.11;
    core.position.y = pointer.y * -0.08;
    orbitalSystem.position.x = pointer.x * 0.18;
    orbitalSystem.position.y = pointer.y * -0.14;
    particles.position.x = pointer.x * -0.16;
    particles.position.y = pointer.y * 0.12;
    core.rotation.x = elapsed * 0.16 * motion + pointer.y * 0.12;
    core.rotation.y = elapsed * 0.24 * motion + pointer.x * 0.16;
    orbitalSystem.rotation.x = elapsed * 0.055 * motion;
    orbitalSystem.rotation.y = elapsed * -0.08 * motion;
    particles.rotation.y = elapsed * 0.018 * motion;
    particles.rotation.x = elapsed * 0.008 * motion;
    camera.position.x += (pointer.x * 0.08 - camera.position.x) * 0.025;
    camera.position.y += (pointer.y * -0.06 - camera.position.y) * 0.025;
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
    if (!reducedMotion) animationFrame = window.requestAnimationFrame(render);
  };

  resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  window.addEventListener('pointermove', onPointerMove, { passive: true });
  resize();
  render();

  window.addEventListener('pagehide', () => {
    if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    resizeObserver?.disconnect();
    window.removeEventListener('pointermove', onPointerMove);
    particleGeometry.dispose();
    particleMaterial.dispose();
    coreMesh.geometry.dispose();
    coreMaterial.dispose();
    innerMesh.geometry.dispose();
    innerMaterial.dispose();
    orbitalSystem.children.forEach((ring) => {
      ring.geometry.dispose();
      ring.material.dispose();
    });
    renderer.dispose();
  }, { once: true });
})();
