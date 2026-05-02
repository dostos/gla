// SOURCE: https://github.com/mrdoob/three.js/issues/33201
// Minimal repro of r182 PR #32330 regression: per-channel diffuse energy
// conservation (1.0 - totalScattering) combined with unsaturated anisotropic
// visibility V_GGX_SmithCorrelated_Anisotropic produces black pixels where the
// arithmetic goes out of [0,1] under direct light on a rough anisotropic
// dielectric ("glass"). A full-screen quad sweeps (N.V, N.L) across UV; the
// broken math produces black patches that correctly-clamped math does not.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *VS =
"#version 330 core\n"
"layout(location=0) in vec2 p;\n"
"out vec2 vUv;\n"
"void main(){ vUv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

static const char *FS =
"#version 330 core\n"
"in vec2 vUv;\n"
"out vec4 fragColor;\n"
// Post-PR #32330: saturate() removed; visibility term is NOT truly bounded
// under grazing anisotropic configurations.
"float V_Aniso(float aT,float aB,float dTV,float dBV,float dTL,float dBL,float dNV,float dNL){\n"
"  float gv = dNL*length(vec3(aT*dTV, aB*dBV, dNV));\n"
"  float gl = dNV*length(vec3(aT*dTL, aB*dBL, dNL));\n"
"  return 0.5/(gv+gl+1e-7);\n" // NO saturate
"}\n"
"void main(){\n"
"  float alphaT = 0.9, alphaB = 0.02;\n" // strong anisotropy: alphaT >> alphaB
"  float thetaV = vUv.x*1.5707;\n"
"  float thetaL = vUv.y*1.5707;\n"
"  vec3 N = vec3(0,0,1);\n"
"  vec3 V = normalize(vec3(sin(thetaV)*0.9, sin(thetaV)*0.3, cos(thetaV)+0.05));\n"
"  vec3 L = normalize(vec3(sin(thetaL)*0.3, sin(thetaL)*0.95, cos(thetaL)+0.05));\n"
"  vec3 T = vec3(1,0,0), B = vec3(0,1,0);\n"
"  float dTV=dot(T,V), dBV=dot(B,V), dTL=dot(T,L), dBL=dot(B,L);\n"
"  float dNV=max(dot(N,V),0.0), dNL=max(dot(N,L),0.0);\n"
"  float Vis = V_Aniso(alphaT,alphaB,dTV,dBV,dTL,dBL,dNV,dNL);\n"
// F_Schlick-ish colored specular with IOR-ish F0; intentionally large/colored
// to stress per-channel energy conservation.
"  vec3 F0 = vec3(0.16, 0.10, 0.04);\n"
"  vec3 spec = (F0 + (1.0-F0)*pow(1.0-dNV,5.0)) * Vis * dNL * 4.0;\n"
// Per-PR #32330: 1.0 - totalScatteringDielectric PER CHANNEL (not max comp).
// When spec exceeds 1 on any channel (unsaturated Vis lets this happen), the
// diffuse scaling goes negative and the final sum -> negative -> clamped black.
"  vec3 totalScatter = spec;\n"
"  vec3 diffuseScale = vec3(1.0) - totalScatter;\n" // per-channel, may be <0
"  vec3 diffuseColor = vec3(0.7, 0.75, 0.85);\n"
"  vec3 color = diffuseColor * diffuseScale + spec;\n"
"  fragColor = vec4(color, 1.0);\n"
"}\n";

static GLuint compile(GLenum t, const char *s){
    GLuint sh = glCreateShader(t);
    glShaderSource(sh,1,&s,NULL);
    glCompileShader(sh);
    GLint ok; glGetShaderiv(sh,GL_COMPILE_STATUS,&ok);
    if(!ok){ char log[2048]; glGetShaderInfoLog(sh,2048,NULL,log); fprintf(stderr,"shader: %s\n",log); exit(1);}
    return sh;
}

int main(void){
    Display *dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa = {0}; swa.colormap = cmap; swa.event_mask = 0;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 512, 512, 0,
        vi->depth, InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER, VS));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    glLinkProgram(prog);
    GLint ok; glGetProgramiv(prog,GL_LINK_STATUS,&ok);
    if(!ok){ char log[2048]; glGetProgramInfoLog(prog,2048,NULL,log); fprintf(stderr,"link: %s\n",log); return 1;}

    float verts[] = { -1,-1,  1,-1,  -1,1,  1,1 };
    GLuint vao, vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

    glViewport(0,0,512,512);
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glXSwapBuffers(dpy, win);

    glFinish();
    return 0;
}