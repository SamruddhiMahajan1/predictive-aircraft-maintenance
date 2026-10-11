// Shader code imported as raw strings to avoid esbuild parsing parentheses in string literals.
import FRAG_COMMON from './subFaultShaders.glsl?raw';
import FRAG_EMISSIVE from './subFaultEmissive.glsl?raw';

// FRAG_COLOR needs the d parameter interpolated, so it's a function
export const FRAG_COMMON = (() => { return ""; })(); // placeholder, will be replaced at runtime
// Actually, let's just export the raw imports
export { FRAG_COMMON as FRAG_COMMON_RAW } from './subFaultShaders.glsl?raw';
export { FRAG_EMISSIVE as FRAG_EMISSIVE_RAW } from './subFaultEmissive.glsl?raw';

// FRAG_COLOR needs d parameter - we'll construct it at runtime
export const FRAG_COLOR = (d) => 
  'float dmg=' + d + ';' +
  '\ndiffuseColor.rgb=mix(diffuseColor.rgb,vec3(.9,.03,.03),smoothstep(.2,.6,dmg));';