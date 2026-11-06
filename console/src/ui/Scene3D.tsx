import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { driftColor } from "../lib/heat";
import type { Projection } from "../lib/projection";

/**
 * Behavioural-state path in a 3-axis projection. The translucent green box is the contract's
 * safe region; the path is coloured by drift; larger red points are excursions and cyan
 * diamonds are turns where a correction fired. Rendered on demand (no animation loop).
 */
export function Scene3D({ projection, index }: { projection: Projection; index: number }) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ setIndex: (i: number) => void } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFailed("This browser couldn't start WebGL.");
      return;
    }
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
    camera.position.set(1.9, 1.35, 2.1);
    renderer.setClearColor(0x0b0e12, 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0.5, 0.5, 0.5);
    controls.enableDamping = false;
    controls.update();

    const disposables: Array<{ dispose: () => void }> = [];
    const track = <T extends { dispose: () => void }>(o: T): T => (disposables.push(o), o);
    const render = () => renderer.render(scene, camera);

    // unit cube frame + axes
    const frame = track(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)));
    const frameLine = new THREE.LineSegments(frame, track(new THREE.LineBasicMaterial({ color: 0x2a313c })));
    frameLine.position.set(0.5, 0.5, 0.5);
    scene.add(frameLine);
    const axis = (to: [number, number, number], color: number) => {
      const g = track(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(...to)]));
      scene.add(new THREE.Line(g, track(new THREE.LineBasicMaterial({ color }))));
    };
    axis([1.08, 0, 0], 0xe06a8a);
    axis([0, 1.08, 0], 0x7ddb8a);
    axis([0, 0, 1.08], 0x46c8d2);

    // safe region
    const [sx, sy, sz] = projection.safe;
    const size = new THREE.Vector3(Math.max(sx[1] - sx[0], 0.001), Math.max(sy[1] - sy[0], 0.001), Math.max(sz[1] - sz[0], 0.001));
    const centre = new THREE.Vector3(sx[0] + size.x / 2, sy[0] + size.y / 2, sz[0] + size.z / 2);
    const boxGeo = track(new THREE.BoxGeometry(size.x, size.y, size.z));
    const box = new THREE.Mesh(boxGeo, track(new THREE.MeshBasicMaterial({ color: 0x7ddb8a, transparent: true, opacity: 0.1, depthWrite: false })));
    box.position.copy(centre);
    scene.add(box);
    const boxEdges = new THREE.LineSegments(track(new THREE.EdgesGeometry(boxGeo)), track(new THREE.LineBasicMaterial({ color: 0x7ddb8a, transparent: true, opacity: 0.55 })));
    boxEdges.position.copy(centre);
    scene.add(boxEdges);

    // path coloured by drift
    const pts = projection.points;
    if (pts.length > 1) {
      const pos = new Float32Array(pts.length * 3);
      const col = new Float32Array(pts.length * 3);
      pts.forEach((p, i) => {
        pos.set([p.x, p.y, p.z], i * 3);
        const c = new THREE.Color(driftColor(p.drift));
        col.set([c.r, c.g, c.b], i * 3);
      });
      const g = track(new THREE.BufferGeometry());
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      scene.add(new THREE.Line(g, track(new THREE.LineBasicMaterial({ vertexColors: true }))));
    }
    const dot = (list: typeof pts, color: number, radius: number, geom?: THREE.BufferGeometry) => {
      if (!list.length) return;
      const geo = geom ?? track(new THREE.SphereGeometry(radius, 12, 8));
      const mat = track(new THREE.MeshBasicMaterial({ color }));
      for (const p of list) {
        const m = new THREE.Mesh(geo, mat);
        m.position.set(p.x, p.y, p.z);
        scene.add(m);
      }
    };
    dot(pts.filter((p) => p.excursion && !p.corrected), 0xff6b5e, 0.014);
    dot(pts.filter((p) => p.corrected), 0x46c8d2, 0, track(new THREE.OctahedronGeometry(0.022)));

    const head = new THREE.Mesh(track(new THREE.SphereGeometry(0.026, 16, 12)), track(new THREE.MeshBasicMaterial({ color: 0xeef2f6 })));
    scene.add(head);
    const setIndex = (i: number) => {
      const p = pts[Math.min(Math.max(i, 0), pts.length - 1)];
      if (p) head.position.set(p.x, p.y, p.z);
      render();
    };
    api.current = { setIndex };

    const resize = () => {
      const w = Math.max(el.clientWidth, 200);
      const h = Math.max(el.clientHeight, 200);
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    ro?.observe(el);
    controls.addEventListener("change", render);
    resize();
    setIndex(0);

    return () => {
      api.current = null;
      ro?.disconnect();
      controls.removeEventListener("change", render);
      controls.dispose();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [projection]);

  useEffect(() => api.current?.setIndex(index), [index]);

  return (
    <div className="scene well">
      <div ref={host} role="img" style={{ position: "absolute", inset: 0 }}
        aria-label={`3D path of the run through ${projection.axes.join(", ")}. The same facts are in the summary beside it.`} />
      {/* outside role="img": children of an img role are presentational and would be hidden from assistive tech */}
      {failed && <div className="fallback" role="status"><p>{failed} The summary beside this panel carries the same information.</p></div>}
    </div>
  );
}
