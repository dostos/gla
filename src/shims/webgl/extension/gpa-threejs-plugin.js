// COPY of clients/threejs/index.js — kept here for the Chrome extension's <script>-tag loader.
// Edit clients/threejs/index.js (lines 1–112), then re-copy those lines only.
// The export block below (module.exports / window) intentionally differs from
// clients/threejs/index.js and must NOT be overwritten during re-sync.
/**
 * OpenGPA Three.js Plugin
 *
 * Captures scene graph data (objects, materials, hierarchy) and sends
 * it to the OpenGPA engine's metadata endpoint after each render.
 *
 * Usage:
 *   const gpa = new OpenGPAThreePlugin(renderer, 'http://127.0.0.1:18080', 'your-token');
 *   // In your render loop:
 *   renderer.render(scene, camera);
 *   gpa.capture(scene, camera);
 */
class OpenGPAThreePlugin {
  constructor(renderer, url = 'http://127.0.0.1:18080', token = '') {
    this.renderer = renderer;
    this.url = url.replace(/\/$/, '');
    this.token = token;
    this.frameCount = 0;
  }

  capture(scene, camera) {
    const objects = [];
    const materialsMap = new Map();

    scene.traverse(obj => {
      const entry = {
        name: obj.name || `${obj.type}_${obj.id}`,
        type: obj.type || 'Object3D',
        parent: this._getPath(obj.parent),
        draw_call_ids: [],
        transform: {
          position: obj.position ? obj.position.toArray() : [0, 0, 0],
          rotation: obj.rotation ? [obj.rotation.x, obj.rotation.y, obj.rotation.z] : [0, 0, 0],
          scale: obj.scale ? obj.scale.toArray() : [1, 1, 1]
        },
        visible: obj.visible !== false,
        properties: {}
      };

      if (obj.isLight) {
        entry.properties.color = obj.color ? obj.color.toArray() : [1, 1, 1];
        entry.properties.intensity = obj.intensity || 1;
        if (obj.isPointLight) entry.properties.distance = obj.distance || 0;
        if (obj.isDirectionalLight) entry.type = 'DirectionalLight';
        if (obj.isPointLight) entry.type = 'PointLight';
        if (obj.isSpotLight) entry.type = 'SpotLight';
      }

      if (obj.isCamera) {
        entry.properties.fov = obj.fov || 0;
        entry.properties.near = obj.near || 0.1;
        entry.properties.far = obj.far || 1000;
        entry.properties.aspect = obj.aspect || 1;
      }

      objects.push(entry);

      if (obj.isMesh && obj.material) {
        const mat = obj.material;
        const matName = mat.name || mat.uuid;
        if (!materialsMap.has(matName)) {
          materialsMap.set(matName, {
            name: matName,
            shader: mat.type || 'unknown',
            used_by: [],
            properties: {},
            textures: {}
          });
          if (mat.color) materialsMap.get(matName).properties.color = mat.color.toArray();
          if (mat.metalness !== undefined) materialsMap.get(matName).properties.metallic = mat.metalness;
          if (mat.roughness !== undefined) materialsMap.get(matName).properties.roughness = mat.roughness;
          if (mat.opacity !== undefined) materialsMap.get(matName).properties.opacity = mat.opacity;
          if (mat.map) materialsMap.get(matName).textures.map = mat.map.name || 'texture';
          if (mat.normalMap) materialsMap.get(matName).textures.normalMap = mat.normalMap.name || 'normal';
        }
        materialsMap.get(matName).used_by.push(entry.name);
      }
    });

    const materials = Array.from(materialsMap.values());

    const metadata = {
      framework: 'threejs',
      version: typeof THREE !== 'undefined' ? THREE.REVISION : 'unknown',
      objects,
      materials,
      render_passes: []
    };

    const headers = { 'Content-Type': 'application/json' };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;

    fetch(`${this.url}/api/v1/frames/${this.frameCount}/metadata`, {
      method: 'POST',
      headers,
      body: JSON.stringify(metadata)
    }).catch(() => {}); // Silently ignore network errors

    this.frameCount++;
  }

  _getPath(obj) {
    if (!obj || !obj.parent) return '';
    const parts = [];
    let current = obj;
    while (current && current.parent) {
      parts.unshift(current.name || current.type || 'node');
      current = current.parent;
    }
    return parts.join('/');
  }
}

// Export for both module and script tag usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = OpenGPAThreePlugin;
}
if (typeof window !== 'undefined') {
  window.OpenGPAThreePlugin = OpenGPAThreePlugin;
}
