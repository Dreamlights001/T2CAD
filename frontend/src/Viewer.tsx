import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Box, Camera, Focus, Grid2X2, Ruler, Scan, View } from "lucide-react";
import type { Metrics } from "./types";

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  model: THREE.Group;
  grid: THREE.GridHelper;
  dimensions: THREE.Group;
  center: THREE.Vector3;
  radius: number;
  labels: { element: HTMLDivElement; point: THREE.Vector3 }[];
}

function dispose(group: THREE.Object3D) {
  group.traverse((object) => {
    const mesh = object as THREE.Mesh;
    mesh.geometry?.dispose();
    if (mesh.material)
      (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(
        (m) => m.dispose(),
      );
  });
  group.clear();
}

export default function Viewer({
  url,
  metrics,
  title,
  busy,
}: {
  url?: string;
  metrics?: Metrics;
  title: string;
  busy: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    sceneRef = useRef<SceneState | null>(null);
  const [wire, setWire] = useState(false),
    [dims, setDims] = useState(true),
    [grid, setGrid] = useState(true),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false);
  const fitted = useRef(false);
  const fit = (direction = new THREE.Vector3(1.3, -1.7, 1.25)) => {
    const s = sceneRef.current;
    if (!s) return;
    s.camera.up.set(0, 0, 1);
    s.controls.target.copy(s.center);
    const distance = (s.radius * 2.9) / Math.min(1, s.camera.aspect);
    s.camera.position
      .copy(s.center)
      .add(direction.normalize().multiplyScalar(distance));
    s.camera.near = Math.max(s.radius / 1000, 0.01);
    s.camera.far = Math.max(s.radius * 100, 10000);
    s.camera.updateProjectionMatrix();
    s.controls.update();
  };
  useEffect(() => {
    const el = host.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        preserveDrawingBuffer: true,
      });
    } catch {
      setError("WebGL 初始化失败，请启用浏览器硬件加速");
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0xf2f5f7, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "零件三维视图");
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
    camera.up.set(0, 0, 1);
    camera.position.set(130, -160, 130);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6c7983, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 3.5);
    light.position.set(80, -100, 180);
    scene.add(light);
    const fill = new THREE.DirectionalLight(0xa3dddf, 1.5);
    fill.position.set(-100, 50, 60);
    scene.add(fill);
    const gridHelper = new THREE.GridHelper(400, 40, 0xb8c5cd, 0xdce3e8);
    gridHelper.rotation.x = Math.PI / 2;
    gridHelper.position.z = -0.1;
    scene.add(gridHelper);
    const axes = new THREE.AxesHelper(24);
    axes.position.set(0, 0, 0.1);
    scene.add(axes);
    const model = new THREE.Group(),
      dimensions = new THREE.Group();
    scene.add(model, dimensions);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    const state: SceneState = {
      renderer,
      scene,
      camera,
      controls,
      model,
      grid: gridHelper,
      dimensions,
      center: new THREE.Vector3(0, 0, 15),
      radius: 60,
      labels: [],
    };
    sceneRef.current = state;
    const resize = () => {
      const { width, height } = el.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      for (const { element, point } of state.labels) {
        const projected = point.clone().project(camera);
        const half = element.offsetWidth / 2 + 8;
        element.style.left = `${Math.max(half, Math.min(el.clientWidth - half, ((projected.x + 1) * el.clientWidth) / 2))}px`;
        element.style.top = `${Math.max(48, Math.min(el.clientHeight - 42, ((-projected.y + 1) * el.clientHeight) / 2))}px`;
        element.style.visibility =
          projected.z > 1 || !dimensions.visible ? "hidden" : "visible";
      }
    };
    animate();
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      state.labels.forEach((l) => l.element.remove());
      dispose(scene);
      renderer.dispose();
      renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, []);
  useEffect(() => {
    const s = sceneRef.current;
    if (s) {
      s.grid.visible = grid;
      s.dimensions.visible = dims;
      s.model.traverse((o) => {
        if (o instanceof THREE.Mesh)
          (o.material as THREE.MeshStandardMaterial).wireframe = wire;
      });
    }
  }, [wire, dims, grid, loaded]);
  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    const abort = new AbortController();
    setError("");
    setLoaded(false);
    if (!url) {
      dispose(s.model);
      dispose(s.dimensions);
      s.labels.forEach((l) => l.element.remove());
      s.labels = [];
      fitted.current = false;
      return;
    }
    fetch(url, { signal: abort.signal })
      .then((r) => {
        if (!r.ok) throw Error("模型文件读取失败");
        return r.arrayBuffer();
      })
      .then((buffer) => {
        if (abort.signal.aborted) return;
        const geometry = new STLLoader().parse(buffer);
        geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        dispose(s.model);
        dispose(s.dimensions);
        s.labels.forEach((l) => l.element.remove());
        s.labels = [];
        const mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: 0x438f9d,
            roughness: 0.32,
            metalness: 0.3,
            wireframe: wire,
          }),
        );
        s.model.add(mesh);
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 24),
          new THREE.LineBasicMaterial({
            color: 0x225963,
            transparent: true,
            opacity: 0.55,
          }),
        );
        s.model.add(edges);
        const bounds = metrics
          ? new THREE.Box3(
              new THREE.Vector3(...metrics.bounds.slice(0, 3)),
              new THREE.Vector3(...metrics.bounds.slice(3, 6)),
            )
          : geometry.boundingBox!;
        bounds.getCenter(s.center);
        const size = bounds.getSize(new THREE.Vector3());
        s.radius = Math.max(size.length() / 2, 1);
        const offset = s.radius * 0.18,
          z = bounds.min.z;
        const lines: [THREE.Vector3, THREE.Vector3, string][] = [
          [
            new THREE.Vector3(bounds.min.x, bounds.min.y - offset, z),
            new THREE.Vector3(bounds.max.x, bounds.min.y - offset, z),
            `${size.x.toFixed(1)} mm`,
          ],
          [
            new THREE.Vector3(bounds.max.x + offset, bounds.min.y, z),
            new THREE.Vector3(bounds.max.x + offset, bounds.max.y, z),
            `${size.y.toFixed(1)} mm`,
          ],
          [
            new THREE.Vector3(bounds.max.x + offset, bounds.max.y + offset, z),
            new THREE.Vector3(
              bounds.max.x + offset,
              bounds.max.y + offset,
              bounds.max.z,
            ),
            `${size.z.toFixed(1)} mm`,
          ],
        ];
        lines.forEach(([a, b, text]) => {
          s.dimensions.add(
            new THREE.Line(
              new THREE.BufferGeometry().setFromPoints([a, b]),
              new THREE.LineBasicMaterial({ color: 0x596f86 }),
            ),
          );
          [a, b].forEach((p) => {
            const tick = new THREE.Mesh(
              new THREE.SphereGeometry(s.radius * 0.009, 8, 6),
              new THREE.MeshBasicMaterial({ color: 0x596f86 }),
            );
            tick.position.copy(p);
            s.dimensions.add(tick);
          });
          const element = document.createElement("div");
          element.className = "dimension-label";
          element.textContent = text;
          host.current!.appendChild(element);
          s.labels.push({ element, point: a.clone().lerp(b, 0.5) });
        });
        if (!fitted.current) {
          fit();
          fitted.current = true;
        }
        setLoaded(true);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => abort.abort();
  }, [url]);
  const screenshot = () => {
    const s = sceneRef.current;
    if (!s) return;
    s.renderer.render(s.scene, s.camera);
    const a = document.createElement("a");
    a.download = `${title || "T2CAD"}.png`;
    a.href = s.renderer.domElement.toDataURL();
    a.click();
  };
  return (
    <div className="viewport">
      <div className="canvas-host" ref={host} />
      <div className="viewport-header">
        <span className="view-label">
          <Box size={15} />
          {title || "新建零件"}
        </span>
        <span className="view-unit">mm · Z ↑</span>
      </div>
      <div className="view-tools">
        <button title="适配视图" aria-label="适配视图" onClick={() => fit()}>
          <Focus size={18} />
        </button>
        <button
          title="实体 / 线框"
          aria-label="实体 / 线框"
          className={wire ? "active" : ""}
          onClick={() => setWire(!wire)}
        >
          <Scan size={18} />
        </button>
        <button
          title="尺寸标注"
          aria-label="尺寸标注"
          className={dims ? "active" : ""}
          onClick={() => setDims(!dims)}
        >
          <Ruler size={18} />
        </button>
        <button
          title="网格"
          aria-label="网格"
          className={grid ? "active" : ""}
          onClick={() => setGrid(!grid)}
        >
          <Grid2X2 size={18} />
        </button>
        <button
          title="保存视图截图"
          aria-label="保存视图截图"
          onClick={screenshot}
        >
          <Camera size={18} />
        </button>
        <div className="tool-divider" />
        <button
          title="俯视图"
          aria-label="俯视图"
          onClick={() => fit(new THREE.Vector3(0, 0.001, 1))}
        >
          <View size={18} />
        </button>
        <button
          title="正视图"
          aria-label="正视图"
          onClick={() => fit(new THREE.Vector3(0, -1, 0.001))}
        >
          <Box size={18} />
        </button>
      </div>
      {!!metrics?.dimensions?.length && (
        <div className="feature-dimensions">
          {metrics.dimensions.map((d, i) => (
            <span key={i}>
              {d.label}
              <b>
                {d.value.toFixed(1)} {d.unit}
              </b>
            </span>
          ))}
        </div>
      )}
      {!url && (
        <div className="canvas-empty">
          <Box size={38} strokeWidth={1} />
          <span>尚未生成几何模型</span>
        </div>
      )}
      {error && <div className="canvas-error">{error}</div>}
      {url && !loaded && !error && (
        <div className="canvas-loading">加载几何…</div>
      )}
      <div className="view-bottom">
        <span>
          <i className={busy ? "dot amber" : "dot"} />
          {busy ? "构建中" : loaded ? "几何已加载" : "就绪"}
        </span>
        {metrics && (
          <span>
            {metrics.solids} 个实体 <b>·</b>{" "}
            {(metrics.volume / 1000).toFixed(2)} cm³
          </span>
        )}
        <span className="axis-key">
          <i>X</i>
          <i>Y</i>
          <i>Z</i>
        </span>
      </div>
    </div>
  );
}
