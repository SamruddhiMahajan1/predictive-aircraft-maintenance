#include <common>
varying float vT;
uniform vec3 uH;
uniform float uT;
float zn(float a,float b,float t){return smoothstep(a-.02,a+.02,t)*(1.-smoothstep(b-.02,b+.02,t));}
